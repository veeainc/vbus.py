import sys
import asyncio
import logging
from vbus import Client

logging.basicConfig(level=logging.DEBUG)

SENSOR_IEEE = '00:0d:6f:00:11:08:71:f7'
CONTROLLER_IEEE = [0x00, 0x0d, 0x6f, 0x00, 0x0b, 0x44, 0x8e, 0xaf]
HOST = 'boolangery-ThinkPad-P1-Gen-2'


async def on_client_command(data):
    print('received enrollment command')
    return [0, 0]


async def main():
    client = Client("system", "test")
    await client.connect()

    nodes = await client.discover("system", "zigbee")

    # retrieve the sensor
    sensor_node = await nodes.get_node(HOST, SENSOR_IEEE)

    if not sensor_node:
        sys.exit("sensor not found")

    cmd = await sensor_node.get_attribute('endpoints', '1', 'in_clusters', '1280', 'client_commands', '1')
    if not cmd:
        sys.exit("cannot find client command 1")

    await cmd.subscribe_set(on_set=on_client_command)

    cie_attr = await sensor_node.get_attribute('endpoints', '1', 'in_clusters', '1280', 'attributes', '16')
    if not cie_attr:
        sys.exit("cannot find cie attr")

    await cie_attr.set(CONTROLLER_IEEE)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
