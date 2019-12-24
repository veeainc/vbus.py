import asyncio
from vbus import Client
import logging

logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "test")
    await client.connect()

    nodes = await client.discover("system", "zigbee")

    async def on_attr_change(data, parts):
        print(data)

    for hub_id, hub_node in nodes.items():
        for node_id, device_node in hub_node.items():
            if node_id == 'methods':
                for method_name, method_def in device_node.items():
                    print(f"new controller method found: {method_name}")
                    print(f"args   : {method_def['params']}")
                    print(f"returns: {method_def['returns']}")
            else:
                print(f"new zigbee device found: {node_id}")
                print(f"name: {device_node['name']}")
                print(f"path: {device_node.path}")

                attr = await nodes.get_attribute("endpoints", "1", "attributes", "1")
                if attr:
                    await attr.subscribe_set(on_set=on_attr_change)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
