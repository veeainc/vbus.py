"""
    This example demonstrate how to create a node and how to discover it.
"""
import asyncio
from vbus import Client
import logging
from vbus import definitions
import json

logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "server_python")
    await client.connect()

    async def on_scan(time: int, **kwargs) -> None:
        print("scanning...")

    async def on_attribute_write(data: any, **kwargs):
        print(data, kwargs)

    async def on_read_attr(data: any, **kwargs):
        return 42

    # json-like building:
    node = await client.add_node("device", {
        'uuid': "foo",
        'name': definitions.A("name", "Veea"),
        'scan': definitions.MethodDef(on_scan),
    })

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
