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
from .nats import ExtendedNatsClient

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
        definition = definitions.NodeDef(raw_node, on_set=on_set)  # create the definition
        node = Node(self._client, uuid, definition, self)  # create the connected node
        self._definition.add_child(uuid, definition)  # add it

        # send the node definition on Vbus
        packet = {uuid: await definition.to_repr()}
        await self._client.async_publish(join_path(self.path, NOTIF_ADDED), packet)
        return node

    async def add_attribute(self, uuid: str, value: any, on_set: definitions.SetCallback = None,
                            on_get: definitions.GetCallback = None) -> 'Attribute':
        definition = definitions.AttributeDef(uuid, value, on_set=on_set, on_get=on_get)  # create the definition
        node = Attribute(self._client, uuid, definition, self)  # create the connected node
        self._definition.add_child(uuid, definition)  # add it

        # send the node definition on Vbus
        packet = {uuid: await definition.to_repr()}
        await self._client.async_publish(join_path(self.path, NOTIF_ADDED), packet)
        return node

    async def add_method(self, uuid: str, method: Callable) -> 'Method':
        definition = definitions.MethodDef(method)  # create the definition
        node = Method(self._client, uuid, definition, self)  # create the connected node
        self._definition.add_child(uuid, definition)  # add it

        # send the node definition on Vbus
        packet = {uuid: await definition.to_repr()}
        await self._client.async_publish(join_path(self.path, NOTIF_ADDED), packet)
        return node

    async def get_attribute(self, *parts: str) -> Optional['Attribute']:
        """ Retrieve a local attribute. """
        definition = await self._definition.search_path(*parts)
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

    async def get_remote_node(self, *segments: str) -> proxies.NodeProxy:
        return await proxies.NodeProxy(self._nats, "", {}).get_node(*segments)

    async def get_remote_method(self, *segments: str) -> proxies.MethodProxy:
        return await proxies.NodeProxy(self._nats, "", {}).get_method(*segments)

    async def get_remote_attr(self, *segments: str) -> proxies.AttributeProxy:
        return await proxies.NodeProxy(self._nats, "", {}).get_attribute(*segments)
