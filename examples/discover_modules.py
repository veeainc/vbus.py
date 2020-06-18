"""
    This example demonstrate how to discover modules.
"""
import asyncio

from vbus import Client
import logging


logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "client_python")
    await client.connect()


    modules = await client.discover_modules(1)
    for m in modules:
        print(vars(m))

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
