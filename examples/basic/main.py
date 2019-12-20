import asyncio
from vbus import Client
import logging

logging.basicConfig(level=logging.DEBUG)


async def main():
    client = Client("system", "test")

    await client.connect()

    # node into cache
    node = await client.nodes.add("00:45:25:65:25:ff", {
        'uuid': "foo",
        'name': "Heiman",
    })
    node2 = await client.nodes.add("00:45:25:65:25:AA", {
        'uuid': "bar",
        'name': "Philips",
    })

    await node.add_attribute("manufacturer", "Heiman")
    await node.add('endpoints', {
        42: {
            "name": "temperature"
        }
    })

    await asyncio.sleep(1)

    n = await client.nodes.discover("system", "test", 2)
    print(await n.tree)

    #await node.set_attribute("manufacturer", "Heiman")
    #node['foo'] = 'bar'  # add
    #node['foo'] = 'bar'  # set

    # dynamic node
    #async def on_get_node():
    #    return {
    #        'uuid': "bar",
    #        'name': "Sensor",
    #    }

    #dyn_node = await client.nodes.add_dyn("00:45:25:65:25:AA", on_get_node)


    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
