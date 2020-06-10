"""
    This example demonstrate how to toggle a on/off cluster with a IAS zone device.
"""
import os
import asyncio
from vbus import Client
import logging
import socket

logging.basicConfig(level=logging.DEBUG)
HOST = socket.gethostname()
ON_OFF_DEVICE = "7c:b0:3e:aa:0a:00:15:62"
IAS_ZONE_DEVICE = "00:0d:6f:00:14:f7:1d:37"


async def main():
    client = Client("system", "test")
    await client.connect()

    if not await client.ask_permission("system.zigbee"):
        exit("not authorized")
    if not await client.ask_permission("system.zigbee.>"):
        exit("not authorized")

    element = await client.discover("system", "zigbee")
    nodes = element.as_node()

    # retrieve the on/off device
    on_off_device = await nodes.get_node(HOST, "devices", ON_OFF_DEVICE)

    if not on_off_device:
        exit("on_off_device not found")

    toggle = await on_off_device.get_method('endpoints', '3', 'in_clusters', '6', 'server_commands', '2')

    # retrieve the ias zone device
    zone_device = await nodes.get_node(HOST, "devices", IAS_ZONE_DEVICE)

    if not zone_device:
        exit("zone_device not found")

    status_change_cmd = await zone_device.get_method('endpoints', '1', 'in_clusters', '1280', 'client_commands', '0')
    if not status_change_cmd:
        exit("cannot find status_change_cmd")

    async def on_client_command(data):
        print('zone device changed')
        await toggle.call(timeout_sec=15)

    await status_change_cmd.subscribe_set(on_set=on_client_command)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
