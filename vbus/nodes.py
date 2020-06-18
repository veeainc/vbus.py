"""
    This module contains connected nodes.
    A connected node is composed of a node definition and send commands over the Vbus when the
    user performs action on it. For example: add a child node, delete a node, call a method, etc...
"""
import abc
import sys
import asyncio
import logging
from typing import Dict, Callable, Awaitable, List, Optional

from vbus.definitions import Definition
from . import definitions
from . import proxies
from .helpers import from_vbus, join_path, to_vbus, prune_dict, NOTIF_ADDED, NOTIF_REMOVED, NOTIF_VALUE_SETTED, \
    NOTIF_SETTED, NOTIF_GET
from .nats import ExtendedNatsClient, DEFAULT_TIMEOUT

LOGGER = logging.getLogger(__name__)


class Element(abc.ABC):
    """ Base class for all Vbus connected elements. """

    def __init__(self, client: ExtendedNatsClient, uuid: str, definition: Definition, parent: 'Element'):
        self._client = client
        self._uuid = uuid
        self._definition = definition
        self._parent = parent

    @property
    def uuid(self) -> str:
        return self._uuid

    @property
    def definition(self) -> Definition:
        return self._definition

    @property
    def path(self) -> str:
        """ Returns the full path recursively. """
        if self._parent:
            return join_path(self._parent.path, self._uuid)
        else:
            return self._uuid


class Node(Element):
    """ A VBus connected node.
        This node contains a node definition and send update over VBus.
    """

    def __init__(self, client: ExtendedNatsClient, uuid: str, definition: definitions.NodeDef, parent: Element = None):
        super().__init__(client, uuid, definition, parent)
        self._definition = definition

    async def add_node(self, uuid: str, raw_node: definitions.RawNode, on_set: Callable = None) -> 'Node':
        """ Add a new node in this tree.

            >>> node = await client.add_node("00:45:25:65:25:ff", {
            >>>     'name': definitions.A("name", None),    # add an attribute
            >>>     'scan': definitions.MethodDef(on_scan), # add a method
            >>>     }
            >>> })

            The 'raw_node' param contains a node definition in a Python dictionary style. For this you can use node
            definition contained in `vbus.definition` with these alias:
            - N = NodeDef
            - A = AttributeDef
            - M = MethodDef

            :param uuid: Node uuid
            :param raw_node: Raw node definition
            :param on_set: A callback called when setted
        """
        definition = definitions.NodeDef(raw_node, on_set=on_set)  # create the definition
        node = Node(self._client, uuid, definition, self)  # create the connected node
        self._definition.add_child(uuid, definition)  # add it

        # send the node definition on Vbus
        packet = {uuid: await definition.to_repr()}
        await self._client.async_publish(join_path(self.path, NOTIF_ADDED), packet)
        return node

    async def add_attribute(self, uuid: str, value: any, on_set: definitions.SetCallback = None,
                            on_get: definitions.GetCallback = None) -> 'Attribute':
        """ Add a new attribute in this tree. Prefer the use of add_node() with nested attributes directly.

            >>> attr = await client.add_attribute("name", "Phillips")

            :param uuid: Attribute uuid
            :param value: Attribute initial value
        """
        definition = definitions.AttributeDef(uuid, value, on_set=on_set, on_get=on_get)  # create the definition
        node = Attribute(self._client, uuid, definition, self)  # create the connected node
        self._definition.add_child(uuid, definition)  # add it

        # send the node definition on Vbus
        packet = {uuid: await definition.to_repr()}
        await self._client.async_publish(join_path(self.path, NOTIF_ADDED), packet)
        return node

    async def add_method(self, uuid: str, method: Callable) -> 'Method':
        """ Add a new method in this tree.

            >>> async def scan(time: int = 180, **kwargs) -> None:
            >>>     # kwargs will receive the Vbus path
            >>>     pass  # some work
            >>>
            >>> attr = await client.add_method("scan", scan)

            :param uuid: Method uuid
            :param method: Method callable
        """
        definition = definitions.MethodDef(method)  # create the definition
        node = Method(self._client, uuid, definition, self)  # create the connected node
        self._definition.add_child(uuid, definition)  # add it

        # send the node definition on Vbus
        packet = {uuid: await definition.to_repr()}
        await self._client.async_publish(join_path(self.path, NOTIF_ADDED), packet)
        return node

    async def get_attribute(self, *parts: str) -> Optional['Attribute']:
        """ Retrieve a local attribute.

            :return: None if not found in local tree
         """
        definition = await self._definition.search_path(list(parts))
        if not definition:
            return None

        # test that the definition is an attribute def
        if isinstance(definition, definitions.AttributeDef):
            return Attribute(self._client, join_path(*parts), definition, self)
        else:
            return None

    async def remove_element(self, uuid: str) -> None:
        """ Delete a node and notify VBus. """
        definition = self._definition.remove_child(uuid)

        if not definition:
            LOGGER.warning('trying to remove unknown node: %s', uuid)
            return

        data = {uuid: await definition.to_repr()}
        await self._client.async_publish(join_path(self.path, NOTIF_REMOVED), data)


class Attribute(Element):
    """ A VBus connected attribute. """

    def __init__(self, client: ExtendedNatsClient, uuid: str, definition: definitions.AttributeDef,
                 parent: Element = None):
        super().__init__(client, uuid, definition, parent)
        self._definition = definition

    async def set_value(self, value: any):
        await self._client.async_publish(join_path(self.path, NOTIF_VALUE_SETTED), value)


class Method(Element):
    """ A VBus connected method. """

    def __init__(self, client: ExtendedNatsClient, uuid: str, definition: definitions.MethodDef,
                 parent: Element = None):
        super().__init__(client, uuid, definition, parent)
        self._definition = definition


class ModuleStatus:
    def __init__(self, heap_size: int):
        self.heap_size = heap_size

    def to_repr(self) -> Dict:
        return {
            "heapSize": self.heap_size,
        }

    @staticmethod
    def from_repr(d: Dict) -> 'ModuleStatus':
        return ModuleStatus(heap_size=d['heapSize'])


class ModuleInfo:
    def __init__(self, _id, hostname, client: str, has_static_files: bool, status: ModuleStatus):
        self.id = _id
        self.hostname = hostname
        self.client = client
        self.has_static_files = has_static_files
        self.status = status

    def to_repr(self) -> Dict:
        return {
            "id"            : self.id,
            "hostname"      : self.hostname,
            "client"        : self.client,
            "hasStaticFiles": self.has_static_files,
            "status"        : self.status.to_repr(),
        }

    @staticmethod
    def from_repr(d: Dict) -> 'ModuleInfo':
        return ModuleInfo(
            _id=d['id'],
            hostname=d['hostname'],
            client=d['client'],
            has_static_files=d['hasStaticFiles'],
            status=ModuleStatus.from_repr(d['status']),
        )


class NodeManager(Node):
    """ This is the VBus nodes manager.
        It manage local nodes lifecycle and allow to retrieve remote nodes.
        The node manager is also the root node of your app.

        Note: The client inherits from the NodeManager
    """

    def __init__(self, nats: ExtendedNatsClient, static_path: str = None):
        """ Creates a new NodeManager.

            :param nats: The extended nats client
            :param static_path: Static file path
        """
        super().__init__(nats, "", definitions.NodeDef({}))
        self._nats = nats
        self._static_path = static_path

    async def initialize(self):
        await self._nats.async_subscribe("", cb=self._on_get_nodes, with_host=False)
        await self._nats.async_subscribe(">", cb=self._on_get_path)

    async def discover(self, domain: str, app_name: str, timeout: int = 1, level: int = None) -> proxies.UnknownProxy:
        """ Discover a remote bus tree (A Vbus tree is composed of Vbus elements).

            >>> async def traverse_node(node: NodeProxy, level: int):
            >>>     for name, elem in node.items():
            >>>         if elem.is_node():
            >>>             n = elem.as_node()
            >>>             print('node: ', name)
            >>>             await traverse_node(n, level + 1)
            >>>         elif elem.is_attribute():
            >>>             attr = elem.as_attribute()
            >>>             print('attribute: ', name)
            >>>         elif elem.is_method():
            >>>             print('method: ', name)
            >>>
            >>> element = await client.discover("system", "zigbee")
            >>> if element.is_node():
            >>>     await traverse_node(element.as_node(), 0)

            :param domain: Remote app domain
            :param app_name: Remote app name
            :param timeout: Timeout in sec
            :param level: (not yet supported)
            :return: An unknown proxy
        """
        json_node = {}

        async def async_on_discover(msg):
            nonlocal json_node
            json_data = from_vbus(msg.data)
            json_node = {**json_node, **json_data}

        filters = {}
        if level:
            filters["max_level"] = level

        sid = await self._nats.nats.request(f"{domain}.{app_name}",
                                            to_vbus(filters),
                                            expected=sys.maxsize,
                                            cb=async_on_discover)
        await asyncio.sleep(timeout)
        await self._nats.nats.unsubscribe(sid)
        return proxies.UnknownProxy(self._nats, f"{domain}.{app_name}", json_node)

    async def discover_modules(self, timeout: int = 1) -> List[ModuleInfo]:
        """ Discover running vBus modules.
        """
        resp: List[ModuleInfo] = []

        async def async_on_discover(msg):
            nonlocal resp
            json_data = from_vbus(msg.data)
            info = ModuleInfo.from_repr(json_data)
            resp.append(info)

        sid = await self._nats.nats.request(f"info",
                                            b"",
                                            expected=sys.maxsize,
                                            cb=async_on_discover)
        await asyncio.sleep(timeout)
        await self._nats.nats.unsubscribe(sid)
        return resp

    async def _on_get_nodes(self, data):
        """ Get all nodes. """
        if data and isinstance(data, dict) and "max_level" in data:
            level = data["max_level"]
            data = {self._nats.hostname: await self._definition.to_repr()}
            prune_dict(data, level)
            return data
        else:
            return {
                self._nats.hostname: await self._definition.to_repr()
            }

    async def _handle_set(self, parts: List[str], data) -> Node:
        node_builder = await self._definition.search_path(parts)
        if node_builder:
            try:
                return await node_builder.handle_set(data, parts)
            except Exception as e:
                LOGGER.exception(e)
                return await definitions.ErrorDefinition.InternalError(e).to_repr()
        else:
            return await definitions.ErrorDefinition.PathNotFoundError().to_repr()

    async def _handle_get(self, parts: List[str], data) -> Node:
        node_builder = await self._definition.search_path(parts)
        if node_builder:
            try:
                return await node_builder.handle_get(data, parts)
            except Exception as e:
                LOGGER.exception(e)
                return await definitions.ErrorDefinition.InternalError(e).to_repr()
        else:
            return await definitions.ErrorDefinition.PathNotFoundError().to_repr()

    async def _on_get_path(self, data, path: str):
        """ Get a specific path in a node. """
        parts = path.split('.')
        if len(parts) < 2:
            return

        method = parts.pop()
        if method == NOTIF_GET:
            return await self._handle_get(parts, data)
        elif method == NOTIF_SETTED:
            return await self._handle_set(parts, data)
        return None

    async def get_remote_node(self, *segments: str, timeout: float = DEFAULT_TIMEOUT) -> proxies.NodeProxy:
        """ Retrieve a remote node proxy.

            >>> remote_node = await client.get_remote_node("system", "zigbee", "host", "path", "to", "node")
            >>> remote_node = await client.get_remote_node("system", "zigbee", "host", "path", "to", "node", timeout=0.8)

            :param segments: path segments
            :param timeout: timeout in seconds (optional)
        """
        return await proxies.NodeProxy(self._nats, "", {}).get_node(*segments, timeout=timeout)

    async def get_remote_method(self, *segments: str, timeout: float = DEFAULT_TIMEOUT) -> proxies.MethodProxy:
        """ Retrieve a remote method proxy.

            >>> remote_method = await client.get_remote_method("system", "zigbee", "host", "path", "to", "method")
            >>> remote_method = await client.get_remote_method("system", "zigbee", "host", "path", "to", "method", timeout=0.8)

            :param segments: path segments
            :param timeout: timeout in seconds (optional)
        """
        return await proxies.NodeProxy(self._nats, "", {}).get_method(*segments, timeout=timeout)

    async def get_remote_attr(self, *segments: str, timeout: float = DEFAULT_TIMEOUT) -> proxies.AttributeProxy:
        """ Retrieve a remote attribute proxy.

            >>> remote_attr = await client.get_remote_attr("system", "zigbee", "host", "path", "to", "attr")
            >>> remote_attr = await client.get_remote_attr("system", "zigbee", "host", "path", "to", "attr", timeout=0.8)

            :param segments: path segments
            :param timeout: timeout in seconds (optional)
        """
        return await proxies.NodeProxy(self._nats, "", {}).get_attribute(*segments, timeout=timeout)
