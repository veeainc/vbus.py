"""
    This example demonstrate how to read the temperature attribute from an Heiman temperature sensor.
"""
import asyncio
from vbus import Client
import logging
import socket

logging.basicConfig(level=logging.DEBUG)


SENSOR_IEEE = "00:0d:6f:00:11:fa:10:c4"
SENSOR_HOST = socket.gethostname()


async def main():
    client = Client("system", "test")
    await client.connect()

    if not await client.ask_permission("system.zigbee"):
        exit("not authorized")
    if not await client.ask_permission("system.zigbee.>"):
        exit("not authorized")

    element = await client.discover("system", "zigbee")
    node = element.as_node()

    configure_reporting = await node.get_method(SENSOR_HOST, "devices", SENSOR_IEEE, "configure_reporting")
    if not configure_reporting:
        exit("cannot find method: configure_reporting")

    # try to configure temperature reporting
    while True:
        resp = await configure_reporting.call(1, 1026, 0, 1, 900, 1, timeout_sec=45)
        if isinstance(resp, dict) and "message" in resp:
            print(resp["message"])
        else:
            break
    print("temperature reporting is enabled")

    # try to configure humidity reporting
    while True:
        resp = await configure_reporting.call(2, 1029, 0, 1, 900, 1, timeout_sec=45)
        if isinstance(resp, dict) and "message" in resp:
            print(resp["message"])
        else:
            break
    print("humidity reporting is enabled")

    # read temperature one time
    temp = await node.get_attribute(SENSOR_HOST, "devices", SENSOR_IEEE, "endpoints", "1", "in_clusters", "1026", "attributes", "0")
    if not temp:
        exit("temperature attribute not found")

    value = await temp.get_value(in_cache=False, timeout=25)
    print("temperature: ", value)

    async def temp_changed(node):
        print(node)

    print("listening temp...")
    await temp.subscribe_set(temp_changed)

    # read humidity one time
    hum = await node.get_attribute(SENSOR_HOST, "devices", SENSOR_IEEE, "endpoints", "2", "in_clusters", "1029", "attributes", "0")
    if not hum:
        exit("humidity attribute not found")

    value = await hum.get_value(in_cache=False, timeout=25)
    print("humidity: ", value)

    async def hum_changed(node):
        print(node)

    print("listening humidity...")
    await hum.subscribe_set(hum_changed)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
