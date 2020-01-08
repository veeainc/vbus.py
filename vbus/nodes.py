"""
    This module contains connected nodes.
    A connected node is composed of a node definition and send commands over the Vbus when the
    user performs action on it. For example: add a child node, delete a node, call a method, etc...
"""
import sys
import asyncio
import logging
from typing import Dict, Callable, Awaitable, List, Optional

from vbus.definitions import Definition
from . import definitions
from . import proxies
from .helpers import from_vbus, join_path, to_vbus, prune_dict
from .nats import ExtendedNatsClient


LOGGER = logging.getLogger(__name__)

# The callable user to retrieve node definition
GetNodeDefCallable = Callable[[], Awaitable[Dict]]
NodeType = Dict or definitions.NodeDef or definitions.MethodDef


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
        assert isinstance(self._definition, definitions.NodeDef)
        node_def = definitions.NodeDef(node_raw_def, on_set=on_write)
        self._definition.add_child(uuid, node_def)
        node = Node(self._nats, uuid, node_def, self)

        # send the node definition on Vbus
        data = {uuid: node_def.to_json()}
        await self._nats.async_publish(join_path(self.path, "add"), data)
        return Node(self._nats, uuid, node_def, self)

    async def remove_node(self, uuid: str) -> None:
        """ Delete a node and notify VBus. """
        assert isinstance(self._definition, definitions.NodeDef)
        node_def = self._definition.remove_child(uuid)

        if not node_def:
            LOGGER.warning('trying to remove unknown node: %s', uuid)
            return

        data = {uuid: node_def.to_json()}
        await self._nats.async_publish(join_path(self.path, "del"), data)

    async def get_attribute(self, *parts: str) -> Optional[proxies.AttributeProxy]:
        """ Retrieve an attribute proxy. """
        node_def = self._definition.search_path(list(parts))
        if node_def:
            return proxies.AttributeProxy(self._nats, self.path + "." + ".".join(parts), node_def)
        else:
            return None

    async def get_method(self, *parts: str) -> Optional[proxies.MethodProxy]:
        """ Retrieve a method proxy. """
        # check if already loaded
        method_def = self._definition.search_path(list(parts))
        if method_def:
            return proxies.MethodProxy(self._nats, join_path(self.path, *parts), method_def)
        else:
            # try to load from vbus
            method_def = await self._nats.async_request(join_path(*parts, 'get'), None, with_host=False, with_id=False)
            return proxies.MethodProxy(self._nats,join_path(self.path, *parts), method_def)

    async def get_node(self, *parts: str) -> Optional[proxies.NodeProxy]:
        """ Retrieve a node proxy. """
        # check if already loaded
        node_def = self._definition.search_path(list(parts))
        if node_def:
            return proxies.NodeProxy(self._nats, join_path(self.path, *parts), node_def)
        else:
            # try to load from vbus
            node_def = await self._nats.async_request(join_path(*parts, 'get'), None, with_host=False, with_id=False)
            return proxies.NodeProxy(self._nats,join_path(self.path, *parts), node_def)

    async def add_method(self, uuid: str, method: Callable) -> 'Node':
        """ Register a new callback as a method.
            The callback must be annotated with Python type.
            See: https://docs.python.org/3/library/typing.html

            :example:
            def scan(self, time: int) -> None:
                pass
        """
        assert isinstance(self._definition, definitions.NodeDef)
        method_def = definitions.MethodDef(method)
        method_def.validate_callback()  # raise exception
        self._definition.add_child(uuid, method_def)
        node = Node(self._nats, uuid, method_def, self)

        data = {uuid: method_def.to_json()}
        await self._nats.async_publish(join_path(self.path, "add"), data)
        return node

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

    async def initialize(self):
        await self._nats.async_subscribe("", cb=self._on_get_nodes, with_host=False)
        await self._nats.async_subscribe(">", cb=self._on_get_path)

    async def discover(self, domain: str, app_id: str, timeout: int = 1, level: int = None) -> proxies.NodeProxy:
        json_node = {}

        async def async_on_discover(msg):
            nonlocal json_node
            json_data = from_vbus(msg.data)
            json_node = {**json_node, **json_data}

        filters = {}
        if level:
            filters["max_level"] = level

        sid = await self._nats.nats.request(f"{domain}.{app_id}",
                                            to_vbus(filters),
                                            expected=sys.maxsize,
                                            cb=async_on_discover)
        await asyncio.sleep(timeout)
        await self._nats.nats.unsubscribe(sid)
        # node_builder = builder.Node(json_node)
        return proxies.NodeProxy(self._nats, f"{domain}.{app_id}", json_node)

    async def _on_get_nodes(self, data):
        """ Get all nodes. """
        level = None
        if data and isinstance(data, dict) and "max_level" in data:
            level = data["max_level"]
            data = {self._nats.hostname: self._definition.to_json()}
            prune_dict(data, level)
            return data
        else:
            return {
                self._nats.hostname: self._definition.to_json()
            }

    async def handle_set(self, parts: List[str], data) -> Node:
        node_builder = self._definition.search_path(parts)
        if node_builder:
            try:
                return await node_builder.handle_set(data, parts)
            except Exception as e:
                LOGGER.exception(e)

    async def _on_get_path(self, data, path: str):
        """ Get a specific path in a node. """
        parts = path.split('.')
        if len(parts) < 2:
            return

        method = parts.pop()
        if method == "get":
            definition = self._definition.search_path(parts)
            if definition:
                return definition.to_json()
        elif method == "set":
            return await self.handle_set(parts, data)
        return None

    async def subscribe_add(self, path: str, cb: Callable):
        return await self._nats.async_subscribe(join_path(path, "add"), cb, with_id=False, with_host=False)

    async def subscribe_del(self, path: str, cb: Callable):
        return await self._nats.async_subscribe(join_path(path, "del"), cb, with_id=False, with_host=False)

    async def subscribe_set(self, path: str, cb: Callable):
        return await self._nats.async_subscribe(join_path(path, "set"), cb, with_id=False, with_host=False)
