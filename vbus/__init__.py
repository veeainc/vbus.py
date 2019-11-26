import asyncio
import sys
import logging
from typing import List

from vbus.bridges import VBusBridge
from vbus.utils import from_vbus, to_vbus
from .system import get_hostname
from .methods import VBusMethods
from .nodes import VBusNodes
from .client import ExtendedNatsClient

LOGGER = logging.getLogger(__name__)


class VBusClient:
    def __init__(self, app_domain: str, app_id: str, loop=None):
        self._client = ExtendedNatsClient(app_domain, app_id, loop)
        self._methods = VBusMethods(self._client)
        self._nodes = VBusNodes(self._client)
        self._attributes = {}
        self._permissions = {
            "subscribe": [
                f"{self._client.id}",
                f"{self._client.id}.>",
                f"{self._client.hostname}.{self._client.id}.>",
            ],
            "publish": [
                f"{self._client.id}",
                f"{self._client.id}.>",
                f"{self._client.hostname}.{self._client.id}.>",
            ],
        }

    @property
    def hostname(self) -> str:
        return self._client.hostname

    @property
    def id(self) -> str:
        return self._client.id

    async def async_connect(self):
        await self._client.async_connect()
        await self._client.async_subscribe(cb=self._async_on_describe, with_host=False)

    async def _async_on_describe(self, data):
        return {
            "host": self._client.hostname,
            "bridge": self._client.id,
            **self._attributes,
            "methods": self.methods.get_methods(),
            "nodes": self.nodes.get_nodes(),
        }

    @property
    def methods(self) -> VBusMethods:
        return self._methods

    @property
    def nodes(self) -> VBusNodes:
        return self._nodes

    def set_attribute(self, key: str, value: any):
        self._attributes[key] = value

    async def async_discover(self, domain: str, app_id: str, timeout: int = 1) -> List[VBusBridge]:
        bridges = []

        async def async_on_discover(msg):
            bridges.append(VBusBridge(self._client, from_vbus(msg.data)))

        sid = await self._client.nats.request(f"{domain}.{app_id}", b"", expected=sys.maxsize,
                                              cb=async_on_discover)
        await asyncio.sleep(timeout)
        await self._client.nats.unsubscribe(sid)
        return bridges

    async def async_ask_subscribe_permission(self, permission):
        self._permissions["subscribe"].append(permission)
        await self._client.nats.publish("system.auth.addpermissions", to_vbus(self._permissions))

    async def async_ask_publish_permission(self, permission):
        self._permissions["publish"].append(permission)
        await self._client.nats.publish("system.auth.addpermissions", to_vbus(self._permissions))











