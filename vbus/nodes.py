import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from collections import ChainMap
from typing import Dict, Callable, List, Awaitable

from vbus.helpers import from_vbus
from .nats import ExtendedNatsClient


LOGGER = logging.getLogger(__name__)

# The callable user to retrieve node definition
GetNodeDefCallable = Callable[[], Awaitable[Dict]]


class Node(ABC):
    """ Base node class. """
    def __init__(self, nats: ExtendedNatsClient, uuid: str, parent: 'Node' = None):
        self._nats = nats
        self._uuid = uuid
        self._parent = parent
        self._children: Dict[str, Node] = {}  # contains node by uuid

    async def _unregister_node(self, node: 'Node'):
        await self._nats.async_publish(f"{node.base_path}.del", await node.tree)
        del self._children[node.uuid]

    async def _register_node(self, node: 'Node'):
        await self._nats.async_publish(f"{node.base_path}.add", await node.tree)
        self._children[node.uuid] = node

    @property
    def uuid(self):
        """ Returns the node uuid. """
        return self._uuid

    async def get(self, *parts: str):
        """ Find a sub-element in node tree. """
        root = self.tree
        for part in parts:
            if part in root:
                root = root[part]
            else:
                return None  # not found
        return root

    @property
    def base_path(self) -> str:
        """ Returns node base path. """
        if self._parent:
            return f"{self._parent.base_path}.{self._uuid}"
        else:
            return self._uuid

    @property
    @abstractmethod
    async def tree(self) -> Dict:
        """ Returns the raw tree as a Python dictionary. """
        pass

    @abstractmethod
    async def add_attribute(self, key: str, value: any) -> 'Node':
        pass

    @abstractmethod
    async def set_attribute(self, key: str, value: any) -> 'Node':
        pass

    @abstractmethod
    def __setitem__(self, key, value):
        """ The pythonish way to set attributes. """
        pass

    @abstractmethod
    async def add(self, key: str, node_def: Dict) -> 'Node':
        pass


class CachedNode(Node):
    """ A node that store data in ram. """
    def __init__(self, nats: ExtendedNatsClient, uuid: str, node_def: Dict, parent: Node = None):
        super().__init__(nats, uuid, parent)
        self._node_def = node_def

    @property
    async def tree(self) -> Dict:
        return {
            **self._node_def,
            **ChainMap({k: await n.tree for k, n in self._children.items()})
        }

    async def add_attribute(self, key: str, value: any) -> Node:
        if key in self._node_def:
            LOGGER.warning("trying to add an existing attribute, use set instead")
            return await self.set_attribute(key, value)

        self._node_def[key] = value
        await self._nats.async_publish('.'.join(filter(None, [self.base_path, key, 'add'])), value)
        return self

    async def set_attribute(self, key: str, value: any) -> Node:
        if key not in self._node_def:
            LOGGER.warning("trying to set an unknown attribute, use add instead")
            return await self.add_attribute(key, value)

        self._node_def[key] = value
        await self._nats.async_publish(f"{self.base_path}.{key}.set", value)
        return self

    def __setitem__(self, key, value):
        if key in self._node_def:
            asyncio.get_event_loop().create_task(self.set_attribute(key, value))
        else:
            asyncio.get_event_loop().create_task(self.add_attribute(key, value))

    async def add(self, key: str, node_def: Dict) -> Node:
        """ Add a child cached node. """
        node = CachedNode(self._nats, key, node_def, self)
        await self._register_node(node)
        return node

    async def add_dyn(self, key: str, on_get_node: GetNodeDefCallable) -> Node:
        """ Add a child dynamic node. """
        node = DynamicNode(self._nats, key, on_get_node, self)
        await self._register_node(node)
        return node


class DynamicNode(Node):
    """ A dynamic node do not store its tree. The tree is asked to user side when needed. """
    def __init__(self, nats: ExtendedNatsClient, uuid: str, on_get_node: GetNodeDefCallable, parent: Node = None):
        super().__init__(nats, uuid, parent)
        self._on_get_node = on_get_node

    @property
    async def tree(self) -> Dict:
        return await self._on_get_node()

    async def add_attribute(self, key: str, value: any) -> Node:
        raise NotImplementedError("Not relevant on a dynamic node.")

    async def set_attribute(self, key: str, value: any) -> Node:
        raise NotImplementedError("Not relevant on a dynamic node.")

    def __setitem__(self, key, value):
        raise NotImplementedError("Not relevant on a dynamic node.")

    async def add(self, key: str, node_def: Dict) -> 'Node':
        raise NotImplementedError("Not relevant on a dynamic node.")


class NodeManager(CachedNode):
    """ This is the VBus nodes manager.
        It manage node lifecycle.
        """
    def __init__(self, nats: ExtendedNatsClient):
        super().__init__(nats, "", {})
        self._nats = nats

    async def initialize(self):
        await self._nats.async_subscribe("", cb=self._on_get_nodes, with_host=False)
        await self._nats.async_subscribe(">", cb=self._on_get_path)

    async def discover(self, domain: str, app_id: str, timeout: int = 1) -> Node:
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
        return CachedNode(self._nats, "", json_node)

    async def _on_get_nodes(self, data):
        """ Get all nodes. """
        return {
            self._nats.hostname: {n.uuid: await n.tree for n in self._children.values()}
        }

    async def _on_get_path(self, data, path: str):
        """ Get all a specific path in a node. """
        parts = path.split('.')
        if len(parts) < 2:
            return

        method = parts[-1]
        if method == "get":
            if parts[0] in self._children:
                return await self._children[parts[0]].get(*parts[1:-1])
        return None
