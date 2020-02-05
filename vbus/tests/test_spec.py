import sys
import unittest
import vbus
import logging
from vbus.tests.utils import async_test, setup_test
import natsplayer


class TestStringMethods(unittest.TestCase):
    def setUp(self) -> None:
        _LOGGER = logging.getLogger()
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(logging.DEBUG)
        _LOGGER.addHandler(stream_handler)

    @async_test
    async def test_ask_permission(self):
        player = setup_test("./scenarios/ask_permission.json")
        client = await self.new_client()

        resp = await client.ask_permission("should.be.true")
        self.assertEquals(resp, True)

        resp = await client.ask_permission("should.be.false")
        self.assertEquals(resp, False)

        self.assertTrue(player.is_success())

    @staticmethod
    async def new_client():
        client = vbus.Client("test", "vbuspy")
        await client.connect()
        return client


if __name__ == '__main__':
    unittest.main()
