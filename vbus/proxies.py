"""
    Proxies are object used to communicate with a remote VBus element.
    For example, reading a remote attribute, calling a remote method.
"""
from typing import Callable, Dict, Iterator

from .helpers import join_path, get_path_in_dict
from .nats import ExtendedNatsClient
from .definitions import Definition


class Proxy:
    """ Base class for proxy object. """
    def __init__(self, nats: ExtendedNatsClient, path: str):
        self._nats = nats
        self._path = path
        self._sids = []
        self._name = path.split('.')[-1]

    @property
    def path(self):
        return self._path

    @property
    def name(self) -> str:
        return self._name

    async def unsubscribe(self):
        """ Unsubscribe from all. """
        for sid in self._sids:
            await self._nats.nats.unsubscribe(sid)


class AttributeProxy(Proxy):
    """ Represents remote attributes actions. """
    def __init__(self, nats: ExtendedNatsClient, path: str, attr_def: dict):
        super().__init__(nats, path)
        self._attr_def = attr_def

    def __str__(self):
        return f"{self._name} = {self.value} ({self.schema})"

    @property
    def has_value(self):
        return "value" in self._attr_def

    @property
    def value(self):
        if "value" in self._attr_def:
            return self._attr_def["value"]

    @property
    def schema(self):
        if "schema" in self._attr_def:
            return self._attr_def["schema"]

    async def set(self, value: any):
        return await self._nats.async_publish(self._path + ".set", value, with_host=False, with_id=False)

    async def get_value(self, in_cache=False, timeout=1):
        return await self._nats.async_request(self._path + ".value.get", {"in_cache": in_cache}, with_host=False, with_id=False, timeout=timeout)

    async def subscribe_set(self, on_set: Callable):
        async def wrap_raw_node(raw_node):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_set(node)

        sis = await self._nats.async_subscribe(join_path(self._path, "set"), cb=wrap_raw_node, with_id=False, with_host=False)
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

    async def get_method(self, *parts: str) -> 'MethodProxy' or None:
        node_json = get_path_in_dict(self._node_json, *parts)
        if node_json:
            return MethodProxy(self._nats, self._path + "." + ".".join(parts), node_json)
        else:
            return None

    async def set(self, value: any):
        return await self._nats.async_publish(self._path + ".set", value, with_host=False, with_id=False)

    def items(self):
        for k, v in self._node_json.items():
            yield k, NodeProxy(self._nats, join_path(self._path, k), v)

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

    async def get_attribute(self, *parts: str) -> AttributeProxy:
        attr_def = get_path_in_dict(self._node_json, *parts)
        if not attr_def:
            # TODO: implement fetch
            raise NotImplementedError("Lazy loading nodes is not yet implemented, consider loading the parent first")
        else:
            return AttributeProxy(self._nats, join_path(self._path, *parts), attr_def)

    async def get_node(self, *parts: str) -> 'NodeProxy' or None:
        n = get_path_in_dict(self._node_json, *parts)
        if n:
            return NodeProxy(self._nats, join_path(self._path, *parts), n)
        return None

    def __getitem__(self, item):
        return self._node_json[item]

    async def subscribe_add(self, *parts: str, on_add: Callable):
        async def wrap_raw_node(raw_node, *args):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_add(node, *args)

        sis = await self._nats.async_subscribe(join_path(self._path, *parts, "add"), cb=wrap_raw_node, with_id=False, with_host=False)
        self._sids.append(sis)

    async def subscribe_del(self, *parts: str, on_del: Callable):
        async def wrap_raw_node(raw_node, *args):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_del(node, *args)

        sis = await self._nats.async_subscribe(join_path(self._path, *parts, "del"), cb=wrap_raw_node, with_id=False, with_host=False)
        self._sids.append(sis)


class WildcardNodeProxy(Proxy):
    """ Represents remote node actions on wildcard path ('*'). """
    def __init__(self, nats: ExtendedNatsClient, path: str):
        super().__init__(nats, path)

    async def subscribe_set(self, *parts: str, on_set: Callable):
        async def wrap_raw_node(raw_node, *args):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_set(node, *args)

        sis = await self._nats.async_subscribe(join_path(self._path, *parts, "set"), cb=wrap_raw_node, with_id=False, with_host=False)
        self._sids.append(sis)

    async def subscribe_add(self, *parts: str, on_add: Callable):
        async def wrap_raw_node(raw_node, *args):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_add(node, *args)

        sis = await self._nats.async_subscribe(join_path(self._path, *parts, "add"), cb=wrap_raw_node, with_id=False, with_host=False)
        self._sids.append(sis)

    async def subscribe_del(self, *parts: str, on_del: Callable):
        async def wrap_raw_node(raw_node, *args):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_del(node, *args)

        sis = await self._nats.async_subscribe(join_path(self._path, *parts, "del"), cb=wrap_raw_node, with_id=False, with_host=False)
        self._sids.append(sis)


class WildcardAttrProxy(Proxy):
    """ Represents remote attribute actions on wildcard path ('*'). """
    def __init__(self, nats: ExtendedNatsClient, path: str):
        super().__init__(nats, path)

    async def subscribe_set(self, *parts: str, on_set: Callable):
        async def wrap_raw_node(raw_node, *args):
            node = NodeProxy(self._nats, self._path, raw_node)
            await on_set(node, *args)

        sis = await self._nats.async_subscribe(join_path(self._path, *parts, "value", "set"),
                                               cb=wrap_raw_node, with_id=False, with_host=False)
        self._sids.append(sis)


class MethodProxy(Proxy):
    """ Represents remote method actions. """
    def __init__(self, nats: ExtendedNatsClient, path: str, node_def: Dict):
        super().__init__(nats, path)
        self._node_def = node_def

    @property
    def params_schema(self):
        return self._node_def["params"]["schema"]

    @property
    def returns_schema(self):
        return self._node_def["returns"]["schema"]

    async def call(self, *args: any, timeout_sec: float = 0.5,  with_host=False, with_id=False,):
        return await self._nats.async_request(self._path + ".set", tuple(args),
                                              with_host=with_host,
                                              with_id=with_id,
                                              timeout=timeout_sec)

    async def subscribe_set(self, on_set: Callable):
        sis = await self._nats.async_subscribe(join_path(self._path, "set"), cb=on_set, with_id=False, with_host=False)
        self._sids.append(sis)
