import asyncio
from vbus import Client
import logging
from vbus import definitions


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
        'scan': definitions.MethodDef(on_scan),
        'endpoints': {
            '1': {
                'attributes': {
                    '1': definitions.NodeDef({
                        'name': 'temperature',
                    }, on_write=on_attribute_write)
                }
            }
        }
    })

    await asyncio.sleep(1)

    nodes = await client.discover("system", "test", 2)



    #attr = await nodes.get_attribute("boolangery-ThinkPad-P1-Gen-2", "00:45:25:65:25:ff", "endpoints", "1", "attributes", "1")
    #if attr:
    #    await attr.set(42)

    #method = await nodes.get_method("boolangery-ThinkPad-P1-Gen-2", "00:45:25:65:25:AA", "scan")
    #if method:
    #    await method.call(42)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
