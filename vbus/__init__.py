import logging
from .nodes import NodeManager
from .nats import ExtendedNatsClient

LOGGER = logging.getLogger(__name__)


class Client(NodeManager):
    """ A Vbus client that allows you to discover other bridges.
        Before using it, you must connect it with :func:`~vbus.Client.connect`

        >>> from vbus import Client
        >>> client = Client("system", "myapp")
        >>> await client.connect()
    """

    def __init__(self, app_domain: str, app_id: str, loop=None, hub_id: str = None, password: str = None, static_path: str = None):
        """ Creates a new Client.
            :param app_domain: Application domain : "system" for now
            :param app_id: Application identifier
            :param loop: Asyncio loop
            :param hub_id: Hub id
            :param static_path: If set, it indicates that the service expose static files
        """
        self._nats = ExtendedNatsClient(app_domain, app_id, loop, hub_id)
        super().__init__(self._nats, static_path=static_path)

    @property
    def hostname(self) -> str:
        """ The current hostname.

            :getter: Returns the current hostname
            :type: str
        """
        return self._nats.hostname

    @property
    def id(self) -> str:
        """ The app id.
            The app id is equal to ${app_domain}.${app_name}

            >>> client.id
            >>> "system.myapp"

            :getter: Returns the app id
            :type: str
        """
        return self._nats.id

    async def connect(self):
        """ Connect this client to the Vbus."""
        await self._nats.async_connect()
        await self.initialize()

    async def ask_permission(self, permission: str) -> bool:
        """ Request authorization for a vbus path.

            >>> ok = await client.ask_permission("system.zigbee.>")

            :param permission: A Vbus path, for example "system.zigbee.>"
         """
        return await self._nats.ask_permission(permission)
