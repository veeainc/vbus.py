import sys
import unittest
import vbus
import logging
from vbus.tests.utils import async_test, setup_test, retry


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
        self.assertEqual(resp, True)

        resp = await client.ask_permission("should.be.false")
        self.assertEqual(resp, False)

        self.assertTrue(player.is_success())

    @async_test
    async def test_add_attribute(self):
        player = setup_test("./scenarios/add_attribute.json")
        client = await self.new_client()

        attr = await client.add_attribute("name", "HEIMAN")
        self.assertIsNotNone(attr)

        self.assertTrue(player.is_success())

    @async_test
    async def test_set_attribute(self):
        player = setup_test("./scenarios/set_attribute.json")
        client = await self.new_client()

        attr = await client.add_attribute("name", "HEIMAN")
        self.assertIsNotNone(attr)
        await attr.set_value("hello world")

        self.assertTrue(player.is_success())

    @async_test
    async def test_get_remote_attribute(self):
        player = setup_test("./scenarios/remote_attribute_get.json")
        client = await self.new_client()

        remote_attr = await client.get_remote_attr("test", "remote", client.hostname, "name")
        self.assertIsNotNone(remote_attr)
        val = await remote_attr.get_value()
        self.assertEqual("HEIMAN", val)

        self.assertTrue(player.is_success())

    @staticmethod
    @retry(Exception, tries=4)
    async def new_client():
        client = vbus.Client("test", "vbuspy")
        await client.connect()
        return client


if __name__ == '__main__':
    unittest.main()
