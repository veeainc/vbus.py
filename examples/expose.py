"""
    This example demonstrate how to expose static files.
"""
import asyncio

from vbus import Client
import logging


logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "client_python", static_path="./")
    await client.connect()
    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
