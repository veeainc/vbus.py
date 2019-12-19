import asyncio
import logging
import sys
from typing import Dict, Callable, List

from vbus.helpers import from_vbus
from .nats import ExtendedNatsClient

LOGGER = logging.getLogger(__name__)

OnGetNodeCallback = Callable[[str or None], any]


class Element:
    """ Base of all VBus elements. """

    def __init__(self, nats: ExtendedNatsClient, path: str):
        self._nats = nats
        self._path = path


class Attribute(Element):
    """ Represents a key value pair. """

    def __init__(self, nats: ExtendedNatsClient, path: str, key: str, value: any):
        super().__init__(nats, path)
        self._key = key
        self._value = value


class AttributeManager(Element):
    def __init__(self, nats: ExtendedNatsClient, path: str):
        super().__init__(nats, path)


class Node(Element):
    def __init__(self, nats: ExtendedNatsClient, key: str, node_def: Dict, parent: 'Node' = None):
        super().__init__(nats, "")
        self._parent = parent
        self._key = key
        self._node_def = node_def
        self._sub_id: int = -1
        self._nodes: Dict[str, Node] = {}  # contains node by uuid

    async def _unregister_node(self, node: 'Node'):
        await self._nats.async_publish(f"{node.base_path}.del", node.tree)
        del self._nodes[node.uuid]

    async def _register_node(self, node: 'Node'):
        await self._nats.async_publish(f"{node.base_path}.add", node.tree)
        self._nodes[node.uuid] = node

    @property
    def tree(self):
        return self._node_def

    @property
    def uuid(self):
        return self._key

    def get(self, *parts: str):
        """ Find a sub-element in node tree. """
        root = self._node_def
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
            return f"{self._parent.base_path}.{self._key}"
        else:
            return self._key

    async def add_attribute(self, key: str, value: any) -> 'Node':
        if key in self._node_def:
            LOGGER.warning("trying to add an existing attribute, use set instead")
            return await self.set_attribute(key, value)

        self._node_def[key] = value
        await self._nats.async_publish('.'.join(filter(None, [self.base_path, key, 'add'])), value)
        return self

    async def set_attribute(self, key: str, value: any) -> 'Node':
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

    async def add(self, key: str, node_def: Dict) -> 'Node':
        node = Node(self._nats, key, node_def, self)
        await self._register_node(node)
        return node

    async def add_node_(self, key: str, node_def: Dict):
        await self._nats.async_publish(f"{self._path}.{key}", node_def)

    PY_TYPES_TO_JSON_SCHEMA = {
        int: "integer",
        float: "number",
        bool: "boolean",
        str: "string",
    }

    @staticmethod
    def _check_value_type(value: any) -> bool:
        """ Check if it's a supported type. """
        return type(value) in [int, float, bool, str]

    async def add_attribute_(self, key: str, value: any) -> Attribute:
        """ Add a new attribute. """
        if not self._check_value_type(value):
            raise TypeError(value)

        json_element = {
            key: value,
            'schema': {
                'properties': {
                    key: {
                        'type': self.PY_TYPES_TO_JSON_SCHEMA[type(value)]
                    }
                }
            }
        }
        await self._nats.async_publish(f"{self._path}.add", json_element)
        return Attribute(self._nats, self._path + "." + key, key, value)


class DynNode(Node):
    def __init__(self, nats: ExtendedNatsClient, key: str, node_def: Dict, parent: 'Node' = None):
        super().__init__(nats, key, node_def, parent)


class RemoteNode:
    def __init__(self, nats: ExtendedNatsClient, node_def: Dict):
        self._nats = nats
        self._node_def = node_def

    @property
    def uuid(self) -> str:
        return self._node_def["uuid"]

    @property
    def raw(self) -> Dict:
        return self._node_def

    async def publish(self, *args, data: any) -> None:
        path_segment = [self._node_def['bridge'], self._node_def['host'], 'nodes', self.uuid]
        path_segment.extend([str(a) for a in args])
        await self._nats.async_publish(".".join(path_segment), data, with_host=False, with_id=False)

    async def request(self, *args, data: any) -> any:
        path_segment = [self._node_def['bridge'], self._node_def['host'], 'nodes', self.uuid]
        path_segment.extend([str(a) for a in args])
        return await self._nats.async_request(".".join(path_segment), data, with_host=False, with_id=False)

    async def subscribe(self, *args, cb: Callable):
        path_segment = [self._node_def['bridge'], self._node_def['host'], 'nodes', self.uuid]
        path_segment.extend([str(a) for a in args])
        await self._nats.async_subscribe(".".join(path_segment), cb, with_host=False, with_id=False)

    def __getitem__(self, attr: str):
        return self._node_def[attr]


class RemoteNodeManager:
    """ Manages remote nodes (nodes located on a remote bridge). """

    def __init__(self, nats: ExtendedNatsClient, nodes_def: Dict):
        self._nats = nats
        self._nodes_def = nodes_def

    def list(self) -> List[RemoteNode]:
        return [RemoteNode(self._nats, n) for n in self._nodes_def.values()]

    def get(self, node_uuid: str) -> RemoteNode or None:
        if node_uuid in self._nodes_def:
            return RemoteNode(self._nats, self._nodes_def[node_uuid])
        else:
            return None


class NodeManager(Node):
    """ This is the VBus nodes manager.
        It manage node lifecycle.
        """

    def __init__(self, nats: ExtendedNatsClient):
        super().__init__(nats, "", {})

        self._nats = nats
        self._nodes: Dict[str, Node] = {}  # contains node by uuid
        self._node_sid: Dict[str, List[int]] = {}  # contains node Nats subscribe id

    async def initialize(self):
        await self._nats.async_subscribe("", cb=self._nats_get_nodes, with_host=False)
        await self._nats.async_subscribe(">", cb=self._nats_get_path)
        # await self._nats.async_subscribe("nodes.*", cb=self._nats_get_node)

    async def discover(self, domain: str, app_id: str, timeout: int = 1) -> Node:
        json_node = {}

        async def async_on_discover(msg):
            global json_node
            json_data = from_vbus(msg.data)
            json_node = {**json_node, **json_data}

        sid = await self._nats.nats.request(f"{domain}.{app_id}", b"",
                                            expected=sys.maxsize,
                                            cb=async_on_discover)
        await asyncio.sleep(timeout)
        await self._nats.nats.unsubscribe(sid)
        return Node(self._nats, json_node, f"{domain}.{app_id}")

    async def add(self, key: str, node_def: Dict) -> Node:
        node = Node(self._nats, key, node_def)
        await self._register_node(node)
        return node

    async def add_dyn(self, key: str, on_get_node: Callable):
        node_def = await on_get_node()
        node = DynNode(self._nats, key, node_def)
        await self._register_node(node)
        return node

    async def _nats_get_nodes(self, data):
        """ Get all nodes. """
        return {
            self._nats.hostname: {n.uuid: n.tree for n in self._nodes.values()}
        }

    async def _nats_get_path(self, data, path: str):
        """ Get all nodes. """
        parts = path.split('.')
        if len(parts) < 2:
            return

        method = parts[-1]
        if method == "get":
            if parts[0] in self._nodes:
                return self._nodes[parts[0]].get(*parts[1:-1])
        return None

    async def _nats_get_node(self, data, reply: str, node_uuid: str):
        """ Get one node. """
        if node_uuid not in self._nodes:
            LOGGER.warning("trying to get unknown node: %s", node_uuid)
            return {}
        else:
            return self._nodes[node_uuid].to_definition()

    async def add_(self, node: Node):
        """ Add a new node. """
        if node.get_uuid() not in self._nodes:
            await self._register_node(node)
        else:
            LOGGER.warning("overriding existing node: %s", node.get_uuid())
            await self._unregister_node(node)
            await self._register_node(node)

    async def remove(self, node_uuid: str):
        if node_uuid not in self._nodes:
            await self._unregister_node(self._nodes[node_uuid])
        else:
            LOGGER.warning("trying to remove unknown node: %s", node_uuid)

    async def _unregister_node(self, node: Node):
        await self._nats.async_publish(f"{node.base_path}.del", node.tree)
        del self._nodes[node.uuid]

    async def _register_node(self, node: Node):
        await self._nats.async_publish(f"{node.base_path}.add", node.tree)
        self._nodes[node.uuid] = node

    async def _on_publish(self, path: str, value):
        await self._client.async_publish(path, value)

    async def get_node_definition(self, node: Node):
        """ Add required attributes. """
        return {
            "uuid": node.get_uuid(),
            "bridge": self._client.id,
            "host": self._client.hostname,
            **await node.get_attributes()
        }

    async def get_nodes(self):
        return {n.get_uuid(): await self.get_node_definition(n) for n in self._nodes.values()}
