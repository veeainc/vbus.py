import sys
import asyncio
import logging
from collections import ChainMap
from abc import ABC, abstractmethod
from typing import Dict, Callable, Awaitable, List

from vbus.builder import NodeBuilder
from . import builder
from .helpers import from_vbus, join_path, get_path_in_dict
from .nats import ExtendedNatsClient


LOGGER = logging.getLogger(__name__)

# The callable user to retrieve node definition
GetNodeDefCallable = Callable[[], Awaitable[Dict]]
NodeType = Dict or builder.Node or builder.Method


class AttributeProxy:
    """ Represents remote attributes actions. """
    def __init__(self, nats: ExtendedNatsClient, path: str):
        self._nats = nats
        self._path = path

    async def set(self, value: any):
        return await self._nats.async_publish(self._path + ".set", value, with_host=False, with_id=False)


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

    async def set(self, value: any):
        return await self._nats.async_publish(self._path + ".set", value, with_host=False, with_id=False)


class MethodProxy:
    """ Represents remote method actions. """
    def __init__(self, nats: ExtendedNatsClient, path: str, node_def: Dict):
        self._nats = nats
        self._path = path
        self._node_def = node_def

    async def call(self, value: any):
        return await self._nats.async_request(self._path + ".set", value, with_host=False, with_id=False)


class Node(ABC):
    """ Base node class. """
    def __init__(self, nats: ExtendedNatsClient, uuid: str, node_builder: NodeBuilder, parent: 'Node' = None):
        self._nats = nats
        self._uuid = uuid
        self._builder = node_builder
        self._parent = parent

    @property
    def uuid(self):
        """ Returns the node uuid. """
        return self._uuid

    @property
    def base_path(self) -> str:
        """ Returns node base path. """
        if self._parent:
            return join_path(self._parent.base_path, self._uuid)
        else:
            return self._uuid

    @abstractmethod
    async def add_node(self, key: str, node_def: NodeType) -> 'Node':
        pass

    async def get_attribute(self, *parts: str) -> AttributeProxy or None:
        node_builder = self._builder.search(list(parts))
        if node_builder:
            return NodeProxy(self._nats, self.base_path + "." + ".".join(parts), node_builder)
        else:
            return None

    async def get_method(self, *parts: str) -> MethodProxy or None:
        node_builder = self._builder.search(list(parts))
        if node_builder:
            return MethodProxy(self._nats, self.base_path + "." + ".".join(parts), node_builder)
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
        pass

    async def subscribe_set(self, path: str, callback: Callable[[], Awaitable[any]]):
        pass

    async def handle_set(self, parts: List[str], data) -> 'Node':
        node_builder = self._builder.search(parts)
        if node_builder:
            return await node_builder.handle_set(data)


class CachedNode(Node):
    """ A node that store data in ram. """
    def __init__(self, nats: ExtendedNatsClient, uuid: str, node_builder: NodeBuilder, parent: Node = None):
        super().__init__(nats, uuid, node_builder, parent)

    async def add_node(self, uuid: str, node_def: Dict, on_write: Callable = None) -> Node:
        """ Add a child cached node. """
        node_builder = builder.Node(node_def, on_write=on_write)
        self._builder.add_node(uuid, node_builder)
        node = CachedNode(self._nats, uuid, node_builder, self)

        # send the node definition on Vbus
        await self._nats.async_publish(join_path(node.base_path, "add"), node_builder.to_json())
        return CachedNode(self._nats, uuid, node_builder, self)

    async def add_method(self, uuid: str, method: Callable) -> 'MethodNode':
        node_builder = builder.Method(method)
        node_builder.validate_callback()  # raise exception
        self._builder.add_node(uuid, node_builder)
        node = CachedNode(self._nats, uuid, node_builder, self)

        await self._nats.async_publish(join_path(node.base_path, "add"), node_builder.to_json())
        return node


NodeHandler = Callable[[str or None], Awaitable[Dict]]


class NodeManager(CachedNode):
    """ This is the VBus nodes manager.
        It manage node lifecycle.
        """
    def __init__(self, nats: ExtendedNatsClient):
        super().__init__(nats, "", builder.Node({}))
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
            self._nats.hostname: self._builder.definition
        }

    async def _on_get_path(self, data, path: str):
        """ Get a specific path in a node. """
        parts = path.split('.')
        if len(parts) < 2:
            return

        method = parts[-1]
        if method == "get":
            pass
            # TODO: get path
        elif method == "set":
            return await self.handle_set(parts[:-1], data)
        return None

    def set_node_handler(self, node_handler: NodeHandler):
        if self._node_handler is not None:
            LOGGER.warning("overriding node handler")
        self._node_handler = node_handler

