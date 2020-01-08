from typing import Callable, Dict

from .helpers import join_path, get_path_in_dict
from .nats import ExtendedNatsClient


class Proxy:
    """ Base class for proxy object. """
    def __init__(self, nats: ExtendedNatsClient, path: str):
        self._nats = nats
        self._path = path
        self._sids = []

    @property
    def path(self):
        return self._path

    async def unsubscribe(self):
        for sid in self._sids:
            await self._nats.nats.unsubscribe(sid)


class AttributeProxy(Proxy):
    """ Represents remote attributes actions. """
    def __init__(self, nats: ExtendedNatsClient, path: str, attr_def: dict):
        super().__init__(nats, path)
        self._attr_def = attr_def

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

    async def subscribe_set(self, on_set: Callable):
        sis = await self._nats.async_subscribe(join_path(self._path, "set"), cb=on_set, with_id=False, with_host=False)
        self._sids.append(sis)


class NodeProxy(Proxy):
    """ Represents remote node actions. """
    def __init__(self, nats: ExtendedNatsClient, path: str, node_json: Dict):
        super().__init__(nats, path)
        self._node_json = node_json

    @property
    def tree(self) -> Dict:
        return self._node_json

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

    async def subscribe_add(self, on_add: Callable):
        sis = await self._nats.async_subscribe(join_path(self._path, "add"), cb=on_add, with_id=False, with_host=False)
        self._sids.append(sis)

    async def subscribe_del(self, on_del: Callable):
        sis = await self._nats.async_subscribe(join_path(self._path, "del"), cb=on_del, with_id=False, with_host=False)
        self._sids.append(sis)


class MethodProxy(Proxy):
    """ Represents remote method actions. """
    def __init__(self, nats: ExtendedNatsClient, path: str, node_def: Dict):
        super().__init__(nats, path)
        self._node_def = node_def

    async def call(self, *args: any, timeout_sec: float = 0.5):
        return await self._nats.async_request(self._path + ".set", tuple(args), with_host=False, with_id=False,
                                              timeout=timeout_sec)
