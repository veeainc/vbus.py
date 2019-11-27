import sys
import asyncio
import logging
from typing import List, Dict

from .nodes import NodesManager
from .methods import MethodManager
from .nats import ExtendedNatsClient
from .methods import RemoteMethods
from .helpers import from_vbus, to_vbus

LOGGER = logging.getLogger(__name__)


class RemoteBridge:
    def __init__(self, client: ExtendedNatsClient, bridge_def: Dict):
        self._client = client
        self._methods = RemoteMethods(client, bridge_def["methods"])

    @property
    def methods(self):
        return self._methods


class Bridge:
    """ The VBusClient allows to connect to Veea vbus. """
    def __init__(self, app_domain: str, app_id: str, loop=None):
        self._nats = ExtendedNatsClient(app_domain, app_id, loop)
        self._methods = MethodManager(self._nats)
        self._nodes = NodesManager(self._nats)
        self._attributes = {}
        self._permissions = {
            "subscribe": [
                f"{self._nats.id}",
                f"{self._nats.id}.>",
                f"{self._nats.hostname}.{self._nats.id}.>",
            ],
            "publish": [
                f"{self._nats.id}",
                f"{self._nats.id}.>",
                f"{self._nats.hostname}.{self._nats.id}.>",
            ],
        }

    @property
    def hostname(self) -> str:
        return self._nats.hostname

    @property
    def id(self) -> str:
        return self._nats.id

    async def async_connect(self):
        await self._nats.async_connect()
        await self._methods.async_initialize()
        await self._nodes.initialize()
        await self._nats.async_subscribe("", cb=self._async_on_describe, with_host=False)

    async def _async_on_describe(self, data):
        return {
            "host": self._nats.hostname,
            "bridge": self._nats.id,
            **self._attributes,
            "methods": self.methods.get_methods(),
            "nodes": await self.nodes.get_nodes(),
        }

    @property
    def methods(self) -> MethodManager:
        return self._methods

    @property
    def nodes(self) -> NodesManager:
        return self._nodes

    def set_attribute(self, key: str, value: any):
        self._attributes[key] = value

    async def async_discover(self, domain: str, app_id: str, timeout: int = 1) -> List[RemoteBridge]:
        bridges = []

        async def async_on_discover(msg):
            bridges.append(RemoteBridge(self._nats, from_vbus(msg.data)))

        sid = await self._nats.nats.request(f"{domain}.{app_id}", b"", expected=sys.maxsize,
                                            cb=async_on_discover)
        await asyncio.sleep(timeout)
        await self._nats.nats.unsubscribe(sid)
        return bridges

    async def async_ask_subscribe_permission(self, permission):
        self._permissions["subscribe"].append(permission)
        await self._nats.nats.publish("system.auth.addpermissions", to_vbus(self._permissions))

    async def async_ask_publish_permission(self, permission):
        self._permissions["publish"].append(permission)
        await self._nats.nats.publish("system.auth.addpermissions", to_vbus(self._permissions))
