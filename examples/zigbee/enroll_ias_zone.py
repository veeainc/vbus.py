"""
    Example that demonstrate how to pair and enroll a Heiman door sensor (IAS Zone cluster) trough
    the Zigpy Vbus module.

    Steps are:
        - set cie_addr attribute with the controlle ieee address
        - wait enroll client commands
        - respond to enroll with an enroll_response server command
"""
import sys
import asyncio
import logging
from vbus import Client

logging.basicConfig(level=logging.DEBUG)

SENSOR_IEEE = '00:0d:6f:00:14:f7:1d:37'
CONTROLLER_IEEE = [0x00, 0x0d, 0x6f, 0x00, 0x0b, 0x44, 0x8e, 0xaf]
HOST = 'boolangery-ThinkPad-P1-Gen-2'


async def on_state_changed(data):
    print("state changed: ", data)


async def main():
    client = Client("system", "test")
    await client.connect()

    if not await client.ask_permission("system.zigbee"):
        exit("not authorized")
    if not await client.ask_permission("system.zigbee.>"):
        exit("not authorized")

    element = await client.discover("system", "zigbee")
    node = element.as_node()

    # retrieve the sensor
    sensor_node = await node.get_node(HOST, "devices", SENSOR_IEEE)

    if not sensor_node:
        sys.exit("sensor not found")

    cmd = await sensor_node.get_method('endpoints', '1', 'in_clusters', '1280', 'client_commands', '1')
    srv = await sensor_node.get_method('endpoints', '1', 'in_clusters', '1280', 'server_commands', '0')
    if not cmd or not srv:
        sys.exit("cannot find client command 1")

    async def on_client_command(data):
        print('received enrollment command')
        await srv.call(0, 0)

    await cmd.subscribe_set(on_set=on_client_command)

    cie_attr = await sensor_node.get_attribute('endpoints', '1', 'in_clusters', '1280', 'attributes', '16')
    if not cie_attr:
        sys.exit("cannot find cie attr")

    print("sending cie address")
    await cie_attr.set(CONTROLLER_IEEE)

    state_attr = await sensor_node.get_attribute('endpoints', '1', 'in_clusters', '1280', 'client_commands', '0')
    if not state_attr:
        sys.exit("cannot find state attr")

    await state_attr.subscribe_set(on_set=on_state_changed)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
