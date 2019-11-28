import logging
from typing import Dict, Callable, List
from .nats import ExtendedNatsClient

LOGGER = logging.getLogger(__name__)


OnGetNodeCallback = Callable[[str or None], any]


class Node:
    def __init__(self):
        self.on_publish: Callable[[str, any], None] = lambda p, v: None

    """ Base class to create custom nodes. """
    def get_uuid(self) -> str:
        """ Get node unique identifier as string. """
        raise NotImplementedError()

    async def to_definition(self) -> Dict:
        """ Returns node attributes. """
        raise NotImplementedError()

    def get_readable_paths(self) -> Dict[str, Callable]:
        """ Returns a dictionary with path as key and action as value (callable).
            The path implicitly starts with <domain>.<app_name>.<host>.nodes.<node_uuid>.<your_path>

            Each wildcard are automatically mapped to a function parameter as shown below.

            :example:
            async def _async_on_attribute_read(self, cluster_id, attr_id):
                return self._clusters[cluster_id][attr_id]

            async def _async_on_command_call(self, cluster_id, cmd_id):
                pass

            def get_readable_paths(self):
                return {
                    "clusters.*.attributes.*": self._async_on_attribute_read,
                    "clusters.*.commands.*": self._async_on_command_call,
                }
        """
        raise NotImplementedError()

    async def push_value(self, path: str, value: any):
        await self.on_publish(".".join([self.get_uuid(), path]), value)


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

    async def subscribe(self, *args, data: any):
        path_segment = [self._node_def['bridge'], self._node_def['host'], 'nodes', self.uuid]
        path_segment.extend([str(a) for a in args])
        await self._nats.async_subscribe(".".join(path_segment), data, with_host=False, with_id=False)

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


class NodeManager:
    """ This is the VBus nodes manager.
        It manage node lifecycle.
        """
    def __init__(self, client: ExtendedNatsClient):
        self._client = client
        self._nodes: Dict[str, Node] = {}  # contains node by uuid
        self._node_sid: Dict[str, List[int]] = {}  # contains node Nats subscribe id

    async def initialize(self):
        await self._client.async_subscribe("nodes", cb=self._nats_get_nodes)
        await self._client.async_subscribe("nodes.*", cb=self._nats_get_node)

    async def _nats_get_nodes(self, data, reply: str):
        """ Get all nodes. """
        return [n.to_definition() for n in self._nodes.values()]

    async def _nats_get_node(self, data, reply: str, node_uuid: str):
        """ Get one node. """
        if node_uuid not in self._nodes:
            LOGGER.warning("trying to get unknown node: %s", node_uuid)
            return {}
        else:
            return self._nodes[node_uuid].to_definition()

    async def add(self, node: Node):
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
        # unsubscribe all path
        if node.get_uuid() in self._node_sid:
            for sid in self._node_sid[node.get_uuid()]:
                await self._client.nats.unsubscribe(sid)
        node.on_publish = None
        del self._nodes[node.get_uuid()]

    async def _register_node(self, node: Node):
        self._node_sid.get(node.get_uuid(), [])  # create sid default list

        for path, async_handler in node.get_readable_paths():
            sid = await self._client.async_subscribe(node.get_uuid(), cb=async_handler)
            self._node_sid[node.get_uuid()].append(sid)

        node.on_publish = self._on_publish
        self._nodes[node.get_uuid()] = node

    async def _on_publish(self, path: str, value):
        await self._client.async_publish(path, value)

    async def get_nodes(self):
        return {n.get_uuid(): await n.to_definition() for n in self._nodes.values()}

