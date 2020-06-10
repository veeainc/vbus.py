"""
    This example demonstrate how to remove a Zigbee devices.
"""
import asyncio
from vbus import Client
import logging
import socket

logging.basicConfig(level=logging.DEBUG)

SENSOR_IEEE = "00:0d:6f:00:12:24:8a:9e"
SENSOR_HOST = socket.gethostname()


async def main():
    client = Client("system", "test")
    await client.connect()

    if not await client.ask_permission("system.zigbee"):
        exit("not authorized")
    if not await client.ask_permission("system.zigbee.>"):
        exit("not authorized")

    remove_device = await client.get_remote_method("system", "zigbee", SENSOR_HOST, "controller", "remove_device")
    res = await remove_device.call(SENSOR_IEEE, timeout_sec=45)
    print(res)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
