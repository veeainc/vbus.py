import asyncio
from vbus import Client
import logging
from vbus import builder


logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "test")
    await client.connect()

    async def on_scan(time: int) -> None:
        print("scanning...")

    async def on_attribute_write(path: str):
        print(path)

    # json-like building:
    node = await client.add_node("00:45:25:65:25:ff", {
        'uuid': "foo",
        'name': "Heiman",
        'scan': builder.Method(on_scan),
        'endpoints': {
            '1': {
                'attributes': {
                    '1': builder.Node({
                        'name': 'temperature',
                    }, on_write=on_attribute_write)
                }
            }
        }
    })

    # fluent building:
    node = await client.add_node("00:45:25:65:25:AA", {
        'name': 'Philips'
    })
    await node.add_method('scan', on_scan)
    endpoints = await node.add_node('endpoints', {})
    endpoint_1 = await endpoints.add_node('1', {})
    attrs = await endpoint_1.add_node('attributes', {})
    attr_1 = await attrs.add_node('1', {
        'name': 'humidity'
    })

    await asyncio.sleep(1)

    nodes = await client.discover("system", "test", 2)
    attr = await nodes.get_attribute("boolangery-ThinkPad-P1-Gen-2", "00:45:25:65:25:ff", "endpoints", "1", "attributes", "1")
    if attr:
        await attr.set(42)

    method = await nodes.get_method("boolangery-ThinkPad-P1-Gen-2", "00:45:25:65:25:AA", "scan")
    if method:
        await method.call(42)

    print(await nodes.tree)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
