import re
from nats.aio.client import Client

from vbus import from_vbus


class ExtendedClient:
    """ Just for typing. """
    @property
    def hostname(self) -> str:
        raise NotImplementedError()

    @property
    def id(self) -> str:
        raise NotImplementedError()

    @property
    def nats(self) -> Client:
        raise NotImplementedError()

    async def async_subscribe(self, *args, cb):
        """ Utility method that automatically parse subject wildcard to arguments.

            :param nodes: Node type name
            :param args: Path segment
            :param cb: The handler
            :return:

            :example:
            async def handler(data, reply, e_id, c_id):
                print(data, e_id, c_id)

            await async_subscribe("zigbee", "endpoints", "*", "clusters", "*", cb=handler)
        """
        path = f"{self.id}.{self.hostname}.{'.'.join(args)}"
        # create a regex that capture wildcard
        regex = path.replace(".", r"\.").replace("*", r"([^.]+)")

        async def on_data(msg):
            m = re.match(regex, msg.subject)
            if m:
                await cb(from_vbus(msg.data), msg.reply, *m.groups())

        await self.nats.subscribe(path, cb=on_data)
