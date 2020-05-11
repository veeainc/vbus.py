"""
    Proxies are object used to communicate with a remote VBus element.
    For example, reading a remote attribute, calling a remote method.
"""
import logging
from typing import Callable, Dict, Iterator, Optional, Awaitable

from .helpers import join_path, get_path_in_dict, NOTIF_GET, is_wildcard_path
from .nats import ExtendedNatsClient, DEFAULT_TIMEOUT
from .definitions import Definition
from .helpers import NOTIF_ADDED, NOTIF_REMOVED, NOTIF_SETTED, NOTIF_VALUE_SETTED

LOGGER = logging.getLogger(__name__)


class Proxy:
    """ Base class for proxy object.
        Proxies are object used to access remote elements.
    """

    def __init__(self, nats: ExtendedNatsClient, path: str):
        self._nats = nats
        self._path = path
        self._sids = []
        self._name = path.split('.')[-1]

    @property
    def path(self) -> str:
        """ Retrieve element path in the Vbus tree.

            :getter: Returns the path.
        """
        return self._path

    @property
    def name(self) -> str:
        """ Retrieve element name (the last part of the path).

            :getter: Returns element name.
        """
        return self._name

    async def unsubscribe(self):
        """ Unsubscribe from all. """
        for sid in self._sids:
            await self._nats.nats.unsubscribe(sid)


class UnknownProxy(Proxy):
    """ Represents an unknown remote element.
        It can be a node, an attribute or a method.
    """

    def __init__(self, nats: ExtendedNatsClient, path: str, attr_def: dict):
        super().__init__(nats, path)
        self._raw_node = attr_def

    def is_attribute(self) -> bool:
        """ Test if it's an attribute element. If yes use :func:`as_attribute`.

            >>> if remote_element.is_attribute():
            >>>     remote_attr = remote_element.as_attribute()
        """
        return Definition.is_attribute(self._raw_node)

    def as_attribute(self) -> 'AttributeProxy':
        """ Retrieve an attribute proxy."""
        return AttributeProxy(self._nats, self._path, self._raw_node)

    def is_method(self) -> bool:
        """ Test if it's a method element. If yes use :func:`as_method`.

            >>> if remote_element.is_method():
            >>>     remote_method = remote_element.as_method()
        """
        return Definition.is_method(self._raw_node)

    def as_method(self) -> 'MethodProxy':
        """ Retrieve a method proxy."""
        return MethodProxy(self._nats, self._path, self._raw_node)

    def is_node(self) -> bool:
        """ Test if it's a node. If yes use :func:`as_node`.

            >>> if remote_element.is_node():
            >>>     remote_node = remote_element.as_node()
        """
        return Definition.is_node(self._raw_node)

    def as_node(self) -> 'NodeProxy':
        """ Retrieve a node proxy."""
        return NodeProxy(self._nats, self._path, self._raw_node)


AttrSubscribeSetCallable = Callable[['NodeProxy'], Awaitable[None]]


class AttributeProxy(Proxy):
    """ Represents remote attributes actions. """

    def __init__(self, nats: ExtendedNatsClient, path: str, attr_def: dict):
        super().__init__(nats, path)
        self._attr_def = attr_def

    def __str__(self):
        return f"{self._name} = {self.value} ({self.schema})"

    @property
    def has_value(self) -> bool:
        """ Check if this attribute has a value in cache (the value in the tree).

            :getter: Returns True if a value is in cache.
        """
        return "value" in self._attr_def

    @property
    def value(self) -> Optional[any]:
        """ Retrieve value in cache.

            :getter: Returns value in cache or None.
        """
        if "value" in self._attr_def:
            return self._attr_def["value"]

    @property
    def schema(self) -> Dict:
        """ Retrieve attribute Json-Schema.

            :getter: Returns the Jso-schema or None.
        """
        if "schema" in self._attr_def:
            return self._attr_def["schema"]

    async def set(self, value: any):
        """ Set attribute value.

            :param value: The value (must match the Json-schema)
        """
        return await self._nats.async_publish(self._path + ".set", value, with_host=False, with_id=False)

    async def get_value(self, in_cache=False, timeout=1):
        """ A synchronous read operation. It ask to the remote app to read a new value for this attribute.
            (for example, if it's a device, to read this value directly in the device)

            :param in_cache: no yet supported
            :param timeout: The timeout in sec
        """
        return await self._nats.async_request(self._path + ".value.get", {"in_cache": in_cache}, with_host=False,
                                              with_id=False, timeout=timeout)

    async def subscribe_set(self, on_set: AttrSubscribeSetCallable):
        """ Subscribe to 'set' notifications. It is fired when someone set a new value for this attribute.

            >>> async def on_attr_change(value: NodeProxy):
            >>>     print(node.tree)  # value
            >>>
            >>> await attr.subscribe_set(on_attr_change)

            :param on_set: The callback
        """

        async def wrap_raw_node(raw_node):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_set(node)

        sis = await self._nats.async_subscribe(join_path(self._path, NOTIF_VALUE_SETTED), cb=wrap_raw_node,
                                               with_id=False,
                                               with_host=False)
        self._sids.append(sis)


class NodeProxy(Proxy):
    """ Represents remote node actions. """

    def __init__(self, nats: ExtendedNatsClient, path: str, node_json: Dict):
        super().__init__(nats, path)
        self._node_json = node_json

    @property
    def tree(self) -> Dict:
        return self._node_json

    def __str__(self):
        return str(self.tree)

    async def get_method(self, *parts: str, timeout: float = DEFAULT_TIMEOUT) -> 'MethodProxy' or None:
        if is_wildcard_path(*parts):
            raise ValueError("wildcard path not supported")

        node_json = get_path_in_dict(self._node_json, *parts)
        if node_json:
            return MethodProxy(self._nats, self._path + "." + ".".join(parts), node_json)
        # try to load from Vbus
        element_def = await self._nats.async_request(join_path(*parts, 'get'), None, with_host=False, with_id=False,
                                                     timeout=timeout)
        return MethodProxy(self._nats, join_path(self.path, *parts), element_def)

    async def set(self, value: any):
        return await self._nats.async_publish(self._path + ".set", value, with_host=False, with_id=False)

    def items(self) -> Iterator[UnknownProxy]:
        for k, v in self._node_json.items():
            if isinstance(v, dict):
                yield k, UnknownProxy(self._nats, join_path(self._path, k), v)
            else:
                LOGGER.warning("skipping unknown object: %s", v)

    def attributes(self) -> Iterator[AttributeProxy]:
        """ Yield only attributes. """
        for k, n in self._node_json.items():
            if Definition.is_attribute(n):
                yield AttributeProxy(self._nats, join_path(self.path, k), n)

    def methods(self) -> Iterator['MethodProxy']:
        """ Yield only nodes. """
        for k, n in self._node_json.items():
            if Definition.is_method(n):
                yield MethodProxy(self._nats, join_path(self.path, k), n)

    def nodes(self) -> Iterator['NodeProxy']:
        """ Yield only nodes. """
        for k, n in self._node_json.items():
            if Definition.is_node(n):
                yield NodeProxy(self._nats, join_path(self.path, k), n)

    def attribute(self, name: str) -> AttributeProxy:
        try:
            return AttributeProxy(self._nats, join_path(self.path, name), self._node_json[name])
        except:
            raise TypeError(f"{name} is not an attribute, use node.has_attribute(\"{name}\") before")

    def has_attribute(self, name: str):
        return name in self._node_json and Definition.is_attribute(self._node_json[name])

    def has_method(self, name: str):
        return name in self._node_json and Definition.is_method(self._node_json[name])

    async def get_attribute(self, *parts: str, timeout: float = DEFAULT_TIMEOUT) -> AttributeProxy:
        raw_elem_def = get_path_in_dict(self._node_json, *parts)
        if raw_elem_def:
            return AttributeProxy(self._nats, join_path(self._path, *parts), raw_elem_def)
        # load from Vbus
        resp = await self._nats.async_request(join_path(*parts, NOTIF_GET), None, with_host=False, with_id=False,
                                              timeout=timeout)
        return AttributeProxy(self._nats, join_path(self.path, *parts), resp)

    async def get_node(self, *parts: str, timeout: float = DEFAULT_TIMEOUT) -> 'NodeProxy' or None:
        if is_wildcard_path(*parts):
            raise ValueError("wildcard path not supported")

        n = get_path_in_dict(self._node_json, *parts)
        if n:
            return NodeProxy(self._nats, join_path(self._path, *parts), n)
        # try to load from Vbus
        element_def = await self._nats.async_request(join_path(*parts, 'get'), None, with_host=False, with_id=False,
                                                     timeout=timeout)
        return NodeProxy(self._nats, join_path(self.path, *parts), element_def)

    def __getitem__(self, item):
        return self._node_json[item]

    async def subscribe_add(self, *parts: str, on_add: Callable):
        async def wrap_raw_node(raw_node, *args):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_add(node, *args)

        sis = await self._nats.async_subscribe(join_path(self._path, *parts,
                                                         NOTIF_ADDED), cb=wrap_raw_node, with_id=False, with_host=False)
        self._sids.append(sis)

    async def subscribe_del(self, *parts: str, on_del: Callable):
        async def wrap_raw_node(raw_node, *args):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_del(node, *args)

        sis = await self._nats.async_subscribe(join_path(self._path, *parts, NOTIF_REMOVED), cb=wrap_raw_node,
                                               with_id=False, with_host=False)
        self._sids.append(sis)


class WildcardNodeProxy(Proxy):
    """ Represents remote node actions on wildcard path ('*'). """

    def __init__(self, nats: ExtendedNatsClient, path: str):
        super().__init__(nats, path)

    async def subscribe_set(self, *parts: str, on_set: Callable):
        async def wrap_raw_node(raw_node, *args):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_set(node, *args)

        sis = await self._nats.async_subscribe(join_path(self._path, *parts, NOTIF_SETTED), cb=wrap_raw_node,
                                               with_id=False, with_host=False)
        self._sids.append(sis)

    async def subscribe_add(self, *parts: str, on_add: Callable):
        async def wrap_raw_node(raw_node, *args):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_add(node, *args)

        sis = await self._nats.async_subscribe(join_path(self._path, *parts, NOTIF_ADDED), cb=wrap_raw_node,
                                               with_id=False, with_host=False)
        self._sids.append(sis)

    async def subscribe_del(self, *parts: str, on_del: Callable):
        async def wrap_raw_node(raw_node, *args):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_del(node, *args)

        sis = await self._nats.async_subscribe(join_path(self._path, *parts, NOTIF_REMOVED), cb=wrap_raw_node,
                                               with_id=False, with_host=False)
        self._sids.append(sis)


class WildcardAttrProxy(Proxy):
    """ Represents remote attribute actions on wildcard path ('*'). """

    def __init__(self, nats: ExtendedNatsClient, path: str):
        super().__init__(nats, path)

    async def subscribe_set(self, *parts: str, on_set: Callable):
        async def wrap_raw_node(raw_node, *args):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_set(node, *args)

        sis = await self._nats.async_subscribe(join_path(self._path, *parts, "value", NOTIF_SETTED),
                                               cb=wrap_raw_node, with_id=False, with_host=False)
        self._sids.append(sis)


class MethodProxy(Proxy):
    """ Represents remote method actions. """

    def __init__(self, nats: ExtendedNatsClient, path: str, node_def: Dict):
        super().__init__(nats, path)
        self._node_def = node_def

    @property
    def params_schema(self) -> Dict:
        """ Retrieve params Json-schema.
            It describes required params.

            :getter: Returns the Json-schema.
        """
        return self._node_def["params"]["schema"]

    @property
    def returns_schema(self) -> Dict:
        """ Retrieve returns Json-schema.
            It describes the return value.

            :getter: Returns the Json-schema.
        """
        return self._node_def["returns"]["schema"]

    async def call(self, *args: any, timeout_sec: float = 0.5, with_host=False, with_id=False, ):
        """ Make a remote procedure call.

            >>> method_proxy.params_schema
            >>> {
            >>>   "type": "array",
            >>>   "items": [
            >>>     {
            >>>       "type": "string",
            >>>       "description": "id"
            >>>     },
            >>>     {
            >>>       "type": "number",
            >>>       "description": "endpoint"
            >>>     },
            >>>   ]
            >>> }

            >>> #                              id ¬      ┌ endpoint
            >>> resp = await method_proxy.call("e4fa56", 0, timeout_sec=1)

            :param args: The required params as described by the Json-schema
            :param timeout_sec: The timeout in sec
        """
        return await self._nats.async_request(self._path + ".set", tuple(args),
                                              with_host=with_host,
                                              with_id=with_id,
                                              timeout=timeout_sec)

    async def subscribe_set(self, on_set: Callable):
        sis = await self._nats.async_subscribe(join_path(self._path, NOTIF_SETTED), cb=on_set, with_id=False,
                                               with_host=False)
        self._sids.append(sis)
