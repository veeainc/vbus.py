"""
    This example demonstrate how to expose an uri.
"""
import asyncio

from vbus import Client
import logging


logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "client_python")
    await client.connect()

    await client.expose("frontend", 'http', '80', 'google')

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
