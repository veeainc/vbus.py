import logging
from .nodes import NodeManager
from .nats import ExtendedNatsClient

LOGGER = logging.getLogger(__name__)


class Client(NodeManager):
    """ A simple Vbus client that allows you to discover other bridges.
        For creating a new bridge use Bridge class. """
    def __init__(self, app_domain: str, app_id: str, loop=None, remote_host: str = None):
        self._nats = ExtendedNatsClient(app_domain, app_id, loop, remote_host)
        super().__init__(self._nats)

    @property
    def hostname(self) -> str:
        return self._nats.hostname

    @property
    def id(self) -> str:
        return self._nats.id

    async def connect(self):
        await self._nats.async_connect()
        await self.initialize()

    async def ask_permission(self, permission) -> bool:
        return await self._nats.ask_permission(permission)
