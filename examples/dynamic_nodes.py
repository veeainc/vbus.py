import asyncio
from vbus import Client
import logging

logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "test")
    await client.connect()

    async def on_get_node():
        return {
            'uuid': "bar",
            'name': "Sensor",
        }

    dyn_node = await client.add_dyn("00:45:25:65:25:AA", on_get_node)

    await asyncio.sleep(1)
    n = await client.discover("system", "test", 2)
    print(await n.tree)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
