import asyncio
from vbus import Client
import logging

logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "test")
    await client.connect()

    async def scan(time: int) -> None:
        print("scanning with time: ", time)

    method = await client.add_method("scan", scan)

    await method.set(60)

    # await asyncio.sleep(1)
    # n = await client.discover("system", "test", 2)
    # print(await n.tree)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
