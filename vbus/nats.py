import re
import os
import json
import bcrypt
import logging
import asyncio
from typing import Dict
from nats.aio.client import Client

from .helpers import get_hostname, to_vbus, from_vbus

ELEMENT_NODES = "nodes"
VBUS_PATH = 'VBUS_PATH'
VBUS_URL = 'VBUS_URL'

LOGGER = logging.getLogger(__name__)


class ExtendedNatsClient:
    def __init__(self, app_domain: str, app_id: str, loop=None):
        self._loop = loop or asyncio.get_event_loop()
        self._hostname: str = get_hostname()
        self._id = f"{app_domain}.{app_id}"
        self._root_path = f"{self._id}.{self._hostname}"
        self._env = self._read_env_vars()
        self._root_folder = self._env[VBUS_PATH]
        if not self._root_folder:
            self._root_folder = self._env['HOME']
            self._root_folder = self._root_folder + "/vbus/"
        self._nats = Client()

    @property
    def hostname(self) -> str:
        return self._hostname

    @property
    def id(self) -> str:
        return self._id

    @property
    def nats(self) -> Client:
        return self._nats

    @staticmethod
    def _read_env_vars():
        return {
            'HOME': os.environ.get('HOME'),
            VBUS_PATH: os.environ.get(VBUS_PATH),
            VBUS_URL: os.environ.get(VBUS_URL),
        }

    async def async_connect(self):
        config = self._read_or_create_config_file()
        server_url = await self._find_vbus_url(config)
        config["vbus"]["url"] = server_url
        self._save_config_file(config)
        await self._publish_auth(server_url, config)
        await asyncio.sleep(1, loop=self._loop)
        await self._nats.connect(server_url, io_loop=self._loop, user=config["auth"]["user"],
                                 password=config["private"]["key"], connect_timeout=1, max_reconnect_attempts=2,
                                 name=config["auth"]["user"], closed_cb=self._async_nats_closed)

    async def _async_nats_closed(self):
        await self._nats.close()

    async def _publish_auth(self, server_url: str, config):
        nats = Client()
        await nats.connect(server_url, loop=self._loop,
                           user="anonymous", password="anonymous",
                           connect_timeout=1, max_reconnect_attempts=2)
        data = json.dumps(config["auth"]).encode('utf-8')
        await nats.publish("system.authorization." + self._hostname + ".add", data)
        await nats.flush()
        await nats.close()
        await asyncio.sleep(3)  # wait server restart

    async def _find_vbus_url(self, config):
        # find Vbus server - strategy 1: get url from config file
        def get_from_config_file() -> str:
            return config["vbus"]["url"]

        # find vbus server  - strategy 2: get url from ENV:VBUS_URL
        def get_from_env() -> str:
            return os.environ.get("VBUS_URL")

        # find vbus server  - strategy 3: try default url nats://hostname:21400
        def get_default() -> str:
            return f"nats://{self._hostname}.veeamesh.local:21400"

        # find vbus server  - strategy 4: find it using avahi
        def get_from_zeroconf() -> str:
            from .helpers import zeroconf_search
            return zeroconf_search()

        find_server_url_strategies = [
            get_from_config_file,
            get_from_env,
            get_default,
            get_from_zeroconf,
        ]

        success = False
        server_url = ""
        for strategy in find_server_url_strategies:
            server_url = strategy()
            if await self._test_vbus_url(server_url):
                LOGGER.debug("url found using strategy '%s': %s", strategy.__name__, server_url)
                success = True
                break
            else:
                LOGGER.debug("cannot find a valid url using strategy '%s': %s", strategy.__name__, server_url)

        if not success:
            raise ConnectionError("cannot find a valid Vbus url")
        else:
            return server_url

    async def _test_vbus_url(self, url: str, user="anonymous", pwd="anonymous") -> bool:
        if not url:
            return False

        nc = Client()
        LOGGER.debug("test connection to: " + url + " with user: " + user + " and pwd: " + pwd)
        try:
            await nc.connect(url, loop=self._loop, user=user, password=pwd, connect_timeout=1, max_reconnect_attempts=2)
        except Exception:
            return False
        else:
            return True

    def _read_or_create_config_file(self) -> Dict:
        from .helpers import generate_password

        if not os.access(self._root_folder, os.F_OK):
            os.mkdir(self._root_folder)

        LOGGER.debug("check if we already have a Vbus config file in " + self._root_folder)
        config_file = os.path.join(self._root_folder, self._id + ".conf")
        if os.path.isfile(config_file):
            LOGGER.debug("load existing configuration file for " + self._id)
            return json.loads(open(config_file).read())
        else:
            LOGGER.debug("create new configuration file for " + self._id)
            # TODO: this template should be in a git repo shared between all vbus impl
            password = generate_password()
            public_key = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=11, prefix=b"2a"))
            return {
                "elements": {
                    "path": self._id,
                    "name": self._id,
                    "host": self._hostname,
                    "uuid": f"{self._hostname}.{self._id}",
                    "bridge": "None",
                },
                "auth": {
                    "user": f"{self._hostname}.{self._id}",
                    "password": public_key.decode('utf-8'),
                    "permissions": {
                        "subscribe": [
                            ">",
                            f"{self._id}",
                            f"{self._id}.>",
                            f"{self._hostname}.{self._id}.>",
                        ],
                        "publish": [
                            ">",
                            f"{self._id}",
                            f"{self._id}.>",
                            f"{self._hostname}.{self._id}.>",
                        ],
                    }
                },
                "private": {
                    "key": password
                },
                "vbus": {
                    "url": None
                }
            }

    def _save_config_file(self, config):
        config_file = os.path.join(self._root_folder, self._id + ".conf")
        LOGGER.debug("try to open config file " + config_file)
        with open(config_file, 'w+') as f:
            json.dump(config, f)

    async def async_subscribe(self, path, cb, with_id: bool = True, with_host: bool = True) -> int:
        """ Utility method that automatically parse subject wildcard to arguments and
            if a value is returned, publish this value on the reply subject.

            :param path: Path
            :param cb: The handler
            :param with_id: Prepend the app id without host
            :param with_host: Prepend full root app_id + host
            :return: nats sid

            :example:
            async def handler(data, reply, e_id, c_id):
                print(data, e_id, c_id)
                return 42

            await async_subscribe("zigbee", "endpoints", "*", "clusters", "*", cb=handler)
        """
        path = self._get_path(path, with_id, with_host)
        # create a regex that capture wildcard and chevron
        regex = path.replace(".", r"\.").replace("*", r"([^.]+)").replace(">", r"(.+)")

        async def on_data(msg):
            m = re.match(regex, msg.subject)
            if m:
                ret = await cb(from_vbus(msg.data), *m.groups())
                if msg.reply:
                    await self._nats.publish(msg.reply, to_vbus(ret))

        return await self.nats.subscribe(path, cb=on_data)

    def _get_path(self, path: str, with_id: bool, with_host: bool):
        if with_host:
            path = '.'.join(filter(None, [self.hostname, path]))
        if with_id:
            path = '.'.join(filter(None, [self.id, path]))
        return path

    async def async_request(self, path: str, data: any, timeout: float = 0.5, with_id: bool = True, with_host: bool = True) -> any:
        path = self._get_path(path, with_id, with_host)
        msg = await self._nats.request(path, to_vbus(data), timeout=timeout)
        return from_vbus(msg.data)

    async def async_publish(self, path: str, data: any, with_id: bool = True, with_host: bool = True):
        path = self._get_path(path, with_id, with_host)
        await self._nats.publish(path, to_vbus(data))
