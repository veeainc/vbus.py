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

        self.assert_player_success(player)

    @async_test
    async def test_add_attribute(self):
        player = setup_test("./scenarios/add_attribute.json")
        client = await self.new_client()

        attr = await client.add_attribute("name", "HEIMAN")
        self.assertIsNotNone(attr)

        self.assert_player_success(player)

    @async_test
    async def test_set_attribute(self):
        player = setup_test("./scenarios/set_attribute.json")
        client = await self.new_client()

        attr = await client.add_attribute("name", "HEIMAN")
        self.assertIsNotNone(attr)
        await attr.set_value("hello world")

        self.assert_player_success(player)

    @async_test
    async def test_get_remote_attribute(self):
        player = setup_test("./scenarios/remote_attribute_get.json")
        client = await self.new_client()

        remote_attr = await client.get_remote_attr("test", "remote", client.hostname, "name")
        self.assertIsNotNone(remote_attr)
        val = await remote_attr.get_value()
        self.assertEqual("HEIMAN", val)

        self.assert_player_success(player)

    @async_test
    async def test_add_method(self):
        player = setup_test("./scenarios/add_method_python.json")
        client = await self.new_client()

        async def echo(msg: str, **kwargs) -> str:
            return msg

        meth = await client.add_method("echo", echo)
        self.assertIsNotNone(meth)

        self.assert_player_success(player)

    @staticmethod
    @retry(Exception, tries=4)
    async def new_client():
        client = vbus.Client("test", "vbuspy")
        await client.connect()
        return client

    def assert_player_success(self, p):
        p.wait_done()
        self.assertTrue(p.is_success())
        p.stop()


if __name__ == '__main__':
    unittest.main()
