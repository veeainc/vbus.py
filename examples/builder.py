import asyncio
import logging
import json
from vbus.builder import Method

logging.basicConfig(level=logging.DEBUG)



class Test:
    def __init__(self):
        self._foo = 'bar'


class VBusEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Test):
            return {
                "foo": "bar"
            }
        else:
            raise ValueError("unknown type: " + type(o))




async def main():
    async def on_get_node(uuid: str) -> int:
        pass

    test = {
        'scan': Test()
    }

    print(json.dumps(test, cls=VBusEncoder))
    # print(test)

    stopped = asyncio.Event()
    await stopped.wait()


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
