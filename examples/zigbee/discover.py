"""
    This example demonstrate how to discover Zigbee devices and controller methods.
"""
import asyncio
from vbus import Client
import logging

logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "test")
    await client.connect()

    if not await client.ask_permission("system.zigbee"):
        exit("not authorized")
    if not await client.ask_permission("system.zigbee.>"):
        exit("not authorized")

    element = await client.discover("system", "zigbee")

    # we know in advance the shape of the tree (its why we can do something like this)
    for hub_id, hub_node in element.as_node().items():
        for category_id, cat_node in hub_node.as_node().items():
            if category_id == 'controller':
                for method in cat_node.as_node().methods():
                    print("\ncontroller method:")
                    print("----------------------------")
                    print(f"name   : {method.name}")
                    print(f"args   : {method.params_schema}")
                    print(f"returns: {method.returns_schema}")
                for attr in cat_node.as_node().attributes():
                    print("\ncontroller attribute:")
                    print("----------------------------")
                    print(f"{(attr.name + ':').ljust(20)} {str(attr.value).ljust(30)} {attr.schema}")
            elif category_id == 'devices':
                for device_uuid, device_node in cat_node.as_node().items():
                    print("\nnew zigbee device found:")
                    print("------------------------")
                    for attr in device_node.as_node().attributes():
                        print(f"{(attr.name + ':').ljust(20)} {str(attr.value).ljust(30)} {attr.schema}")


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
