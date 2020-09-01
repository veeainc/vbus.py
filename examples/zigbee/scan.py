"""
    This example demonstrate how to scan and listen for new Zigbee devices.
"""
import asyncio
import logging
from vbus import Client
from vbus.proxies import NodeProxy

logging.basicConfig(level=logging.DEBUG)


async def on_device_joined(data: NodeProxy):
    print("Device joined:")
    print(data, "\n")


async def on_device_left(data: NodeProxy):
    print("Device left:")
    print(data, "\n")


async def main():
    client = Client("system", "test")
    await client.connect()

    if not await client.ask_permission("system.zigbee"):
        exit("not authorized")
    if not await client.ask_permission("system.zigbee.>"):
        exit("not authorized")

    devices_node = await client.get_remote_node("system", "zigbee", client.hostname, "devices")
    await devices_node.subscribe_add(on_add=on_device_joined)
    await devices_node.subscribe_del(on_del=on_device_left)

    scan_method = await client.get_remote_method("system", "zigbee", client.hostname, "controller", "scan")
    await scan_method.call(120, timeout_sec=125)  # scan for 20 secs

    print("press Ctrl+C to stop.")
    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
