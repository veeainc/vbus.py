"""
    This module contains connected nodes.
    A connected node is composed of a node definition and send commands over the Vbus when the
    user performs action on it. For example: add a child node, delete a node, call a method, etc...
"""
import sys
import asyncio
import logging
from typing import Dict, Callable, Awaitable, List

from vbus.definitions import Definition
from . import definitions
from .helpers import from_vbus, join_path, get_path_in_dict
from .nats import ExtendedNatsClient


LOGGER = logging.getLogger(__name__)

# The callable user to retrieve node definition
GetNodeDefCallable = Callable[[], Awaitable[Dict]]
NodeType = Dict or definitions.NodeDef or definitions.MethodDef


class AttributeProxy:
    """ Represents remote attributes actions. """
    def __init__(self, nats: ExtendedNatsClient, path: str):
        self._nats = nats
        self._path = path
        self._sids = []

    async def set(self, value: any):
        return await self._nats.async_publish(self._path + ".set", value, with_host=False, with_id=False)

    async def subscribe_set(self, on_set: Callable):
        sis = await self._nats.async_subscribe(join_path(self._path, "set"), cb=on_set, with_id=False, with_host=False)
        self._sids.append(sis)

    async def unsubscribe(self):
        for sid in self._sids:
            await self._nats.nats.unsubscribe(sid)


class NodeProxy:
    """ Represents remote node actions. """
    def __init__(self, nats: ExtendedNatsClient, path: str, node_json: Dict):
        self._nats = nats
        self._path = path
        self._node_json = node_json

    async def get_method(self, *parts: str) -> 'MethodProxy' or None:
        node_json = get_path_in_dict(self._node_json, *parts)
        if node_json:
            return MethodProxy(self._nats, self._path + "." + ".".join(parts), node_json)
        else:
            return None

    @property
    def path(self):
        return self._path

    async def set(self, value: any):
        return await self._nats.async_publish(self._path + ".set", value, with_host=False, with_id=False)

    def items(self):
        for k, v in self._node_json.items():
            yield k, NodeProxy(self._nats, join_path(self._path, k), v)

    async def get_attribute(self, *parts: str) -> AttributeProxy:
        # TODO: check existence or retrieve
        return AttributeProxy(self._nats, join_path(self._path, *parts))

    async def get_node(self, *parts: str) -> 'NodeProxy' or None:
        n = get_path_in_dict(self._node_json, *parts)
        if n:
            return NodeProxy(self._nats, join_path(self._path, *parts), n)
        return None

    def __getitem__(self, item):
        return self._node_json[item]


class MethodProxy:
    """ Represents remote method actions. """
    def __init__(self, nats: ExtendedNatsClient, path: str, node_def: Dict):
        self._nats = nats
        self._path = path
        self._node_def = node_def

    async def call(self, value: any):
        return await self._nats.async_request(self._path + ".set", value, with_host=False, with_id=False)


class Node:
    """ A VBus connected node.
        This node contains a node definition and send update over VBus.
    """
    def __init__(self, nats: ExtendedNatsClient, uuid: str, node_def: Definition, parent: 'Node' = None):
        self._nats = nats
        self._uuid = uuid
        self._definition = node_def
        self._parent = parent

    @property
    def uuid(self):
        """ Returns the node uuid. """
        return self._uuid

    @property
    def path(self) -> str:
        """ Returns node path. """
        if self._parent:
            return join_path(self._parent.path, self._uuid)
        else:
            return self._uuid

    async def add_node(self, uuid: str, node_raw_def: Dict, on_write: Callable = None) -> 'Node':
        """ Add a child node and notify Vbus. """
        node_def = definitions.NodeDef(node_raw_def, on_write=on_write)
        self._definition.add_child(uuid, node_def)
        node = Node(self._nats, uuid, node_def, self)

        # send the node definition on Vbus
        await self._nats.async_publish(join_path(node.path, "add"), node_def.to_json())
        return Node(self._nats, uuid, node_def, self)

    async def remove_node(self, uuid: str) -> None:
        """ Delete a node and notify VBus. """
        node_builder = self._definition.remove_child(uuid)

        if not node_builder:
            LOGGER.warning('trying to remove unknown node: %s', uuid)
            return

        await self._nats.async_publish(join_path(self.path, uuid, "del"), node_builder.to_json())

    async def get_attribute(self, *parts: str) -> AttributeProxy or None:
        """ Retrieve an attribute proxy. """
        node_def = self._definition.search_path(list(parts))
        if node_def:
            return NodeProxy(self._nats, self.path + "." + ".".join(parts), node_def)
        else:
            return None

    async def get_method(self, *parts: str) -> MethodProxy or None:
        """ Retrieve a method proxy. """
        node_def = self._definition.search_path(list(parts))
        if node_def:
            return MethodProxy(self._nats, self.path + "." + ".".join(parts), node_def)
        else:
            return None

    async def add_method(self, uuid: str, method: Callable) -> 'MethodNode':
        """ Register a new callback as a method.
            The callback must be annotated with Python type.
            See: https://docs.python.org/3/library/typing.html

            :example:
            def scan(self, time: int) -> None:
                pass
        """
        node_def = definitions.MethodDef(method)
        node_def.validate_callback()  # raise exception
        self._definition.add_child(uuid, node_def)
        node = Node(self._nats, uuid, node_def, self)

        await self._nats.async_publish(join_path(node.path, "add"), node_def.to_json())
        return node

    async def subscribe_set(self, path: str, callback: Callable[[], Awaitable[any]]):
        pass

    async def set(self, path: str, value: any):
        await self._nats.async_publish(join_path(self.path, path, "set"), value)


NodeHandler = Callable[[str or None], Awaitable[Dict]]


class NodeManager(Node):
    """ This is the VBus nodes manager.
        It manage node lifecycle.
        """
    def __init__(self, nats: ExtendedNatsClient):
        super().__init__(nats, "", definitions.NodeDef({}))
        self._nats = nats
        self._node_handler: NodeHandler = None

    async def initialize(self):
        await self._nats.async_subscribe("", cb=self._on_get_nodes, with_host=False)
        await self._nats.async_subscribe(">", cb=self._on_get_path)

    async def discover(self, domain: str, app_id: str, timeout: int = 1) -> NodeProxy:
        json_node = {}

        async def async_on_discover(msg):
            nonlocal json_node
            json_data = from_vbus(msg.data)
            json_node = {**json_node, **json_data}

        sid = await self._nats.nats.request(f"{domain}.{app_id}", b"",
                                            expected=sys.maxsize,
                                            cb=async_on_discover)
        await asyncio.sleep(timeout)
        await self._nats.nats.unsubscribe(sid)
        # node_builder = builder.Node(json_node)
        return NodeProxy(self._nats, f"{domain}.{app_id}", json_node)

    async def _on_get_nodes(self, data):
        """ Get all nodes. """
        return {
            self._nats.hostname: self._definition.definition
        }

    async def handle_set(self, parts: List[str], data) -> Node:
        node_builder = self._definition.search_path(parts)
        if node_builder:
            try:
                return await node_builder.handle_set(data, parts)
            except Exception as e:
                LOGGER.exception(e)

    async def handle_get(self, parts: List[str]) -> Node:
        node_builder = self._definition.search_path(parts)
        if node_builder:
            return node_builder

    async def _on_get_path(self, data, path: str):
        """ Get a specific path in a node. """
        parts = path.split('.')
        if len(parts) < 2:
            return

        method = parts.pop()
        if method == "get":
            return await self.handle_get(parts)
        elif method == "set":
            return await self.handle_set(parts, data)
        return None

    def set_node_handler(self, node_handler: NodeHandler):
        if self._node_handler is not None:
            LOGGER.warning("overriding node handler")
        self._node_handler = node_handler
