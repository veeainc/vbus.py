import re
import os
import json
import socket

import bcrypt
import logging
import asyncio
from typing import Dict, List, Optional, Tuple
from nats.aio.client import Client

from .helpers import get_hostname, to_vbus, from_vbus, key_exists

ELEMENT_NODES = "nodes"
VBUS_PATH = 'VBUS_PATH'
VBUS_URL = 'VBUS_URL'

DEFAULT_TIMEOUT = 0.5

LOGGER = logging.getLogger(__name__)


class ExtendedNatsClient:
    def __init__(self, app_domain: str, app_id: str, loop=None, hub_id: str = None):
        """
        Create an extended nats client.
        :param app_domain:  for now: system
        :param app_id: app name
        :param remote_host: optional, the remote hostname to use to login
        :param loop: asyncio loop
        """
        self._loop = loop or asyncio.get_event_loop()
        self._hostname: str = get_hostname()
        self._remote_hostname = hub_id or self._hostname
        self._id = f"{app_domain}.{app_id}"
        self._env = self._read_env_vars()
        self._root_folder = self._env[VBUS_PATH]
        if not self._root_folder:
            self._root_folder = self._env['HOME'] + "/vbus/"
        self._nats = Client()
        self._network_ip: Optional[str] = None  # populated during mdns discovery

    @property
    def hostname(self) -> str:
        """ Get client hostname (where this program is running). """
        return self._hostname

    @property
    def id(self) -> str:
        return self._id

    @property
    def nats(self) -> Client:
        return self._nats

    @property
    def network_ip(self) -> Optional[str]:
        """ Return network ip, discovered during Mdns phase. (can be empty)"""
        return self._network_ip

    @staticmethod
    def _read_env_vars():
        return {
            'HOME'   : os.environ.get('HOME'),
            VBUS_PATH: os.environ.get(VBUS_PATH),
            VBUS_URL : os.environ.get(VBUS_URL),
        }

    async def async_connect(self):
        config = self._read_or_get_default_config()
        server_url, new_host = await self._find_vbus_url(config)

        # update the config file with the new url
        config["vbus"]["url"] = server_url
        if new_host:
            self._remote_hostname = new_host
        config["vbus"]["hostname"] = self._remote_hostname
        self._save_config_file(config)

        await self._publish_user(server_url, config)
        await asyncio.sleep(1, loop=self._loop)
        await self._nats.connect(server_url, io_loop=self._loop, user=config["auth"]["user"],
                                 password=config["private"]["key"], connect_timeout=1, max_reconnect_attempts=2,
                                 name=config["auth"]["user"], closed_cb=self._async_nats_closed)

    async def ask_permission(self, permission) -> bool:
        config = self._read_or_get_default_config()

        subscribe = config["auth"]["permissions"]["subscribe"]
        if permission not in subscribe:
            subscribe.append(permission)

        publish = config["auth"]["permissions"]["publish"]
        if permission not in publish:
            publish.append(permission)
        path = f"system.authorization.{self._remote_hostname}.{self._id}.{self._hostname}.permissions.set"

        resp = await self.async_request(path, config["auth"]["permissions"], timeout=10, with_id=False, with_host=False)
        self._save_config_file(config)
        return resp

    async def _async_nats_closed(self):
        await self._nats.close()

    async def _publish_user(self, server_url: str, config):
        nats = Client()
        await nats.connect(server_url, loop=self._loop,
                           user="anonymous", password="anonymous",
                           connect_timeout=1, max_reconnect_attempts=2)
        data = json.dumps(config["auth"]).encode('utf-8')
        await nats.publish("system.authorization." + self._remote_hostname + ".add", data)
        await nats.flush()
        await nats.close()

    async def _find_vbus_url(self, config) -> (str, Optional[str]):
        """
            :param config: The configuration file as a Python object.
            :return: The url found
            :return: The new remote hostname
        """

        # find Vbus server - strategy 0: get from argument
        def get_from_hub_id() -> Tuple[List[str], Optional[str]]:
            ip = self._remote_hostname
            try:
                socket.inet_aton(self._remote_hostname)
            except:
                try:
                    ip = socket.gethostbyname(f"{self._remote_hostname}.local")
                except:
                    return [], None  # cannot resolve
            return [f"nats://{ip}:21400"], None

        # find Vbus server - strategy 1: get url from config file
        def get_from_config_file() -> Tuple[List[str], Optional[str]]:
            return [config["vbus"]["url"]], config["vbus"]["hostname"] if "vbus" in config and "hostname" in config[
                "vbus"] else None

        # find vbus server  - strategy 2: get url from ENV:VBUS_URL
        def get_from_env() -> Tuple[List[str], Optional[str]]:
            return [os.environ.get("VBUS_URL")], None

        # find vbus server  - strategy 3: try default url nats://hostname:21400
        def get_default() -> Tuple[List[str], Optional[str]]:
            return [f"nats://{self._hostname}.veeamesh.local:21400"], None

        # find vbus server  - strategy 4: find it using avahi
        def get_from_zeroconf() -> Tuple[List[str], Optional[str]]:
            from .helpers import zeroconf_search
            urls, host, network_ip = zeroconf_search()
            self._network_ip = network_ip
            return urls, host

        find_server_url_strategies = [
            get_from_hub_id,
            get_from_config_file,
            get_from_env,
            get_default,
            get_from_zeroconf,
        ]

        success_url = None
        new_host = None

        for strategy in find_server_url_strategies:
            if success_url:
                break

            server_urls, new_host = strategy()
            for url in server_urls:
                if await self._test_vbus_url(url):
                    LOGGER.debug("url found using strategy '%s': %s", strategy.__name__, url)
                    success_url = url
                    break
                else:
                    LOGGER.debug("cannot find a valid url using strategy '%s': %s", strategy.__name__, url)

        if not success_url:
            raise ConnectionError("cannot find a valid Vbus url")
        else:
            return success_url, new_host

    async def _test_vbus_url(self, url: str, user="anonymous", pwd="anonymous") -> bool:
        if not url:
            return False

        nc = Client()
        LOGGER.debug("test connection to: " + url + " with user: " + user + " and pwd: " + pwd)
        try:
            task = nc.connect(url, loop=self._loop, user=user, password=pwd, connect_timeout=1,
                              max_reconnect_attempts=2)

            # Wait for at most 5 seconds, in some case nats library is stuck...
            await asyncio.wait_for(task, timeout=5)
        except Exception:
            return False
        else:
            return True

    @staticmethod
    def _validate_configuration(c: Dict):
        """ Validate the config file structure. """
        return key_exists(c, 'auth', 'user') and \
               key_exists(c, 'auth', 'password') and \
               key_exists(c, 'auth', 'permissions') and \
               key_exists(c, 'private', 'key') and \
               key_exists(c, 'vbus', 'url') and \
               key_exists(c, 'vbus', 'hostname')

    def _read_or_get_default_config(self) -> Dict:

        if not os.access(self._root_folder, os.F_OK):
            os.mkdir(self._root_folder)

        LOGGER.debug("check if we already have a Vbus config file in " + self._root_folder)
        config_file = os.path.join(self._root_folder, self._id + ".conf")
        if os.path.isfile(config_file):
            LOGGER.debug("load existing configuration file for " + self._id)
            with open(config_file, 'r') as content_file:
                content = content_file.read()
                config = json.loads(content)
                if self._validate_configuration(config):
                    return config
                else:
                    LOGGER.warning('invalid configuration detected, the file will be reset to the default one (%s)',
                                   config)
                    return self._create_default_config()
        else:
            return self._create_default_config()

    def _create_default_config(self):
        """ Creates the default configuration. """
        from .helpers import generate_password

        LOGGER.debug("create new configuration file for " + self._id)
        # TODO: this template should be in a git repo shared between all vbus impl
        password = generate_password()
        public_key = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=11, prefix=b"2a"))
        return {
            "auth"   : {
                "user"       : f"{self._id}.{self._hostname}",
                "password"   : public_key.decode('utf-8'),
                "permissions": {
                    "subscribe": [
                        f"{self._id}",
                        f"{self._id}.>",
                    ],
                    "publish"  : [
                        f"{self._id}",
                        f"{self._id}.>",
                    ],
                }
            },
            "private": {
                "key": password
            },
            "vbus"   : {
                "url"     : None,
                "hostname": None,
            }
        }

    def _save_config_file(self, config):
        config_file = os.path.join(self._root_folder, self._id + ".conf")
        LOGGER.debug("saving configuration file: " + config_file)
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
                try:
                    ret = await cb(from_vbus(msg.data), *m.groups())
                    if msg.reply:
                        await self._nats.publish(msg.reply, to_vbus(ret))
                except Exception as e:
                    LOGGER.exception(e)

        return await self.nats.subscribe(path, cb=on_data)

    def _get_path(self, path: str, with_id: bool, with_host: bool):
        if with_host:
            path = '.'.join(filter(None, [self.hostname, path]))
        if with_id:
            path = '.'.join(filter(None, [self.id, path]))
        return path

    async def async_request(self, path: str, data: any, timeout: float = DEFAULT_TIMEOUT, with_id: bool = True,
                            with_host: bool = True) -> any:
        path = self._get_path(path, with_id, with_host)
        msg = await self._nats.request(path, to_vbus(data), timeout=timeout)
        return from_vbus(msg.data)

    async def async_publish(self, path: str, data: any, with_id: bool = True, with_host: bool = True):
        path = self._get_path(path, with_id, with_host)
        await self._nats.publish(path, to_vbus(data))
        await self._nats.flush()
