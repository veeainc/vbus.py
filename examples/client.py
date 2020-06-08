"""
    This example demonstrate how to connect to a remote service and read data.
"""
import asyncio
from vbus import Client
import logging


logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "client_python")
    await client.connect()

    await client.ask_permission("system.server_python")
    await client.ask_permission("system.server_python.>")

    nodes = await client.discover("system", "server_python", 2)
    method = await nodes.as_node().get_method(client.hostname, "device", "scan")
    if method:
        await method.call(42)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
