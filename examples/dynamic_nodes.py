import asyncio
from typing import Dict

from vbus import Client
import logging

logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "test")
    await client.connect()

    async def on_get_node(uuid: str or None) -> Dict:
        if uuid == "00:45:25:65:25:AA":
            return {
                'uuid': "bar",
                'name': "Sensor",
            }
        elif uuid is None:
            return {
                'uuid': "bar",
                'name': "Sensor",
            }

    await client.set_node_handler(on_get_node)

    await asyncio.sleep(1)
    n = await client.discover("system", "test", 2)
    print(await n.tree)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
