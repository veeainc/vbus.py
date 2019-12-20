import sys
import asyncio
import logging

from .nodes import NodeManager, Node
from .nats import ExtendedNatsClient
from .helpers import from_vbus, to_vbus

LOGGER = logging.getLogger(__name__)


class Client:
    """ A simple Vbus client that allows you to discover other bridges.
        For creating a new bridge use Bridge class. """
    def __init__(self, app_domain: str, app_id: str, loop=None):
        self._nats = ExtendedNatsClient(app_domain, app_id, loop)
        self._nodes = NodeManager(self._nats)
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

    @property
    def nodes(self) -> NodeManager:
        return self._nodes

    async def connect(self):
        await self._nats.async_connect()
        await self._nodes.initialize()

    async def discover(self, domain: str, app_id: str, timeout: int = 1) -> Node:
        json_node = {}

        async def async_on_discover(msg):
            global json_node
            json_data = from_vbus(msg.data)
            json_node = {**json_node, **json_data}

        sid = await self._nats.nats.request(f"{domain}.{app_id}", b"", expected=sys.maxsize,
                                            cb=async_on_discover)
        await asyncio.sleep(timeout)
        await self._nats.nats.unsubscribe(sid)
        return Node(self._nats, json_node, f"{domain}.{app_id}")

    async def async_ask_subscribe_permission(self, permission):
        self._permissions["subscribe"].append(permission)
        await self._nats.nats.publish("system.auth.addpermissions", to_vbus(self._permissions))

    async def async_ask_publish_permission(self, permission):
        self._permissions["publish"].append(permission)
        await self._nats.nats.publish("system.auth.addpermissions", to_vbus(self._permissions))
