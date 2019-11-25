import os
import json
import bcrypt
import asyncio
import logging
from typing import Dict
from nats.aio.client import Client

from .system import get_hostname

LOGGER = logging.getLogger(__name__)

ELEMENT_NODES = "nodes"
VBUS_PATH = 'VBUS_PATH'
VBUS_URL = 'VBUS_URL'


class VBusClient:
    def __init__(self, app_domain: str, app_id: str, loop=None):
        self._element_handlers: Dict[str, any] = {}
        self._app_domain = app_domain
        self._app_id = app_id
        self._id = f"{app_domain}.{app_id}"
        self._loop = loop or asyncio.get_event_loop()
        self._hostname: str = ""
        self._env = self._read_env_vars()
        self._root_folder = self._env[VBUS_PATH]
        if not self._root_folder:
            self._root_folder = self._env['HOME']
            self._root_folder = self._root_folder + "/vbus/"
        self._nats = Client()

    @staticmethod
    def _read_env_vars():
        return {
            'HOME': os.environ.get('HOME'),
            VBUS_PATH: os.environ.get(VBUS_PATH),
            VBUS_URL: os.environ.get(VBUS_URL),
        }

    async def async_connect(self):
        self._hostname = get_hostname()
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
        await nats.publish("system.auth.adduser", data)
        await nats.flush()
        await nats.close()

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

    def on_get_nodes(self, node_type: str, callback):
        self._element_handlers[f"{ELEMENT_NODES}.{node_type}"] = callback

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
                            f"{self._id}.>",
                            f"{self._hostname}.{self._id}.>",
                        ],
                        "publish": [
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
