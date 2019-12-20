import asyncio
from vbus import Client
import logging

logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "test")
    await client.connect()

    # node into cache
    node_1 = await client.add("00:45:25:65:25:ff", {
        'uuid': "foo",
        'name': "Heiman",
    })
    await node_1.add_attribute("manufacturer", "Heiman")
    await node_1.add('endpoints', {
        42: {
            "name": "temperature"
        }
    })

    await asyncio.sleep(1)

    n = await client.discover("system", "test", 2)
    print(await n.tree)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
