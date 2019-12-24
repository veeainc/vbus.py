import asyncio
from vbus import Client
import logging

logging.basicConfig(level=logging.DEBUG)

SENSOR_IEEE = '00:0d:6f:00:11:08:71:f7'
CONTROLLER_IEEE = [0x00, 0x0d, 0x6f, 0x00, 0x0b, 0x44, 0x8e, 0xaf]
HOST = 'boolangery-ThinkPad-P1-Gen-2'


async def main():
    client = Client("system", "test")
    await client.connect()

    nodes = await client.discover("system", "zigbee")

    # retrieve the sensor
    sensor_node = await nodes.get_node(HOST, SENSOR_IEEE)

    if not sensor_node:
        print("sensor not found")
        return

    # system.zigbee.boolangery-ThinkPad-P1-Gen-2.00:0d:6f:00:11:08:71:f7.endpoints.1.in_clusters.1280.client_commands.1.set
    async def on_client_command(data):
        pass
        print(data)
        return [0, 0]
        # command 1 is enroll request
        #if int(cmd_id) == 1:
        #    data = [0, 0]
        #    await door_sensor.publish('endpoints', 1, 'in_clusters', 1280, 'server_commands', 0, data=data)

    cmd = await sensor_node.get_attribute('endpoints', '1', 'in_clusters', '1280', 'client_commands', '1')
    if not cmd:
        print("cannot find client command 1")
        return

    await cmd.subscribe_set(on_set=on_client_command)

    cie_attr = await sensor_node.get_attribute('endpoints', '1', 'in_clusters', '1280', 'attributes', '16')
    if not cie_attr:
        print("cannot find cie attr")
        return

    await cie_attr.set(CONTROLLER_IEEE)

    #await door_sensor.subscribe('endpoints', 1, 'in_clusters', 1280, 'client_commands', '*',
    #                            cb=on_client_command)
    #await door_sensor.publish('endpoints', 1, 'in_clusters', 1280, 'attributes', 16, data=CONTROLLER_IEEE)



    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
