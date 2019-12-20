import logging

from .nodes import NodeManager
from .nats import ExtendedNatsClient
from .helpers import to_vbus

LOGGER = logging.getLogger(__name__)


class Client(NodeManager):
    """ A simple Vbus client that allows you to discover other bridges.
        For creating a new bridge use Bridge class. """
    def __init__(self, app_domain: str, app_id: str, loop=None):
        self._nats = ExtendedNatsClient(app_domain, app_id, loop)
        super().__init__(self._nats)
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

    async def connect(self):
        await self._nats.async_connect()
        await self.initialize()

    async def async_ask_subscribe_permission(self, permission):
        self._permissions["subscribe"].append(permission)
        await self._nats.nats.publish("system.auth.addpermissions", to_vbus(self._permissions))

    async def async_ask_publish_permission(self, permission):
        self._permissions["publish"].append(permission)
        await self._nats.nats.publish("system.auth.addpermissions", to_vbus(self._permissions))
