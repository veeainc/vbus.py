import re
import os
import json
import socket

import bcrypt
import logging
import asyncio
from typing import Dict, List, Optional, Tuple
from nats.aio.client import Client
from nats.aio.errors import NatsError

from .helpers import get_hostname, to_vbus, from_vbus, key_exists, sanitize_nats_segment, get_ip, get_id_from_cred

ELEMENT_NODES = "nodes"
VBUS_PATH = 'VBUS_PATH'
VBUS_URL = 'VBUS_URL'
PATH_TO_INFO = "system.info"
VBUS_DNS = "vbus.service.veeamesh.local"

DEFAULT_TIMEOUT = 0.5

LOGGER = logging.getLogger(__name__)


class ExtendedNatsClient:
    def __init__(self, app_domain: str = None, app_id: str = None, creds_file: str = None, loop=None, hub_id: str = None):
        """
        Create an extended nats client.
        :param app_domain:  for now: system
        :param app_id: app name
        :param remote_host: optional, the remote hostname to use to login
        :param loop: asyncio loop
        """
        hostname, isvh = get_hostname()
        self._loop = loop or asyncio.get_event_loop()
        self._hostname: str = sanitize_nats_segment(hostname)
        self._isvh = isvh
        self._remote_hostname = sanitize_nats_segment(hub_id or self._hostname)
        self._creds = creds_file
        if self._creds != None :
            self._id =  get_id_from_cred(self._creds)
            self._vbus_port = "8421"
        else :
            self._id = f"{app_domain}.{app_id}"
            self._vbus_port = "21400"
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
        config = self.read_or_get_default_config()
        server_url, new_host = await self._find_vbus_url(config)

        # update the config file with the new url
        config["vbus"]["url"] = server_url
        if new_host:
            self._remote_hostname = sanitize_nats_segment(new_host)


        # try:
        #     containerID = int(self._hostname, 16)
        #     LOGGER.debug("hostname is numerical - change it with remote hostname")
        #     self._hostname = self._remote_hostname
        #     config["client"]["user"] = f"{self._id}.{self._hostname}"
        # except:
        #     LOGGER.debug("hostname is alphabetical: keep it")

        config["vbus"]["hostname"] = self._remote_hostname

        if self._network_ip:
            config["vbus"]["networkIp"] = self._network_ip

        self._save_config_file(config)

        if self._creds == None:
        # if connection with cred file, already done while url testing and no permission required
        # try to connect directly and push user if fail
            try:
                await self._nats.connect(server_url, io_loop=self._loop, user=config["client"]["user"],
                                        password=config["key"]["private"], connect_timeout=1, max_reconnect_attempts=2,
                                        name=config["client"]["user"], closed_cb=self._async_nats_closed)
            except NatsError:
                LOGGER.debug("unable to connect with user in config file, adding it")
                await self._publish_user(server_url, config)
                await asyncio.sleep(1, loop=self._loop)
                await self._nats.connect(server_url, io_loop=self._loop, user=config["client"]["user"],
                                        password=config["key"]["private"], connect_timeout=1, max_reconnect_attempts=2,
                                        name=config["client"]["user"], closed_cb=self._async_nats_closed)

            await asyncio.sleep(1, loop=self._loop)

            # we are connected, so we loop until permission are been sent successfully
            path = f"system.authorization.{self._remote_hostname}.{self._id}.{self._hostname}.permissions.set"
            while True:
                try:
                    await self.async_request(path, config["client"]["permissions"], timeout=10, with_id=False,
                                        with_host=False)
                    LOGGER.debug("permission sent")
                    break
                except:    
                    LOGGER.debug("permission failed to be sent, will retry in 1sec")
                    await asyncio.sleep(1, loop=self._loop)
                    pass
        
        

        LOGGER.debug("connected")

    async def ask_permission(self, permission) -> bool:
        if self._creds != None:
            LOGGER.warning("No Permission request with new Authentification system")
            return False

        config = self.read_or_get_default_config()
        file_changed = False

        subscribe = config["client"]["permissions"]["subscribe"]
        if permission not in subscribe:
            subscribe.append(permission)
            file_changed = True

        publish = config["client"]["permissions"]["publish"]
        if permission not in publish:
            publish.append(permission)
            file_changed = True

        if file_changed:
            LOGGER.debug("permissions changed, sending them to server")
            path = f"system.authorization.{self._remote_hostname}.{self._id}.{self._hostname}.permissions.set"
            resp = await self.async_request(path, config["client"]["permissions"], timeout=10, with_id=False,
                                            with_host=False)

            if resp:
                self._save_config_file(config)
            else:
                LOGGER.warning("cannot send permission to server")

            return resp

        LOGGER.debug("permissions are already ok")
        return True

    async def _async_nats_closed(self):
        await self._nats.close()

    async def _publish_user(self, server_url: str, config):
        nats = Client()
        await nats.connect(server_url, loop=self._loop,
                           user="anonymous", password="anonymous",
                           connect_timeout=1, max_reconnect_attempts=2)
        data = json.dumps(config["client"]).encode('utf-8')
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
            return [f"nats://{ip}:"+self._vbus_port], None

        # find Vbus server - strategy 1: get url from config file
        def get_from_config_file() -> Tuple[List[str], Optional[str]]:
            return [config["vbus"]["url"]], config["vbus"]["hostname"] if "vbus" in config and "hostname" in config[
                "vbus"] else None

        # find vbus server  - strategy 2: get url from ENV:VBUS_URL
        def get_from_env() -> Tuple[List[str], Optional[str]]:
            return [os.environ.get("VBUS_URL")], None

        # find vbus server  - strategy 3: try default url client://hostname.service.veeamesh.local:21400
        def get_local_default() -> Tuple[List[str], Optional[str]]:
            return [f"nats://"+self._hostname+".service.veeamesh.local:"+self._vbus_port], None

        # find vbus server  - strategy 4: find it using avahi
        def get_from_zeroconf() -> Tuple[List[str], Optional[str]]:
            if self._isvh == False:
                from .helpers import zeroconf_search
                urls, host, network_ip = zeroconf_search()
                self._network_ip = network_ip
                return urls, host
            else:
                return [f""], None
            

        # find vbus server  - strategy 5: try global (MEN) url client://vbus.service.veeamesh.local:21400
        def get_global_default() -> Tuple[List[str], Optional[str]]:
            if self._isvh == False:
                return [f"nats://vbus.service.veeamesh.local:"+self._vbus_port], None
            else:
                return [f""], None

        find_server_url_strategies = [
            get_from_hub_id,
            get_from_config_file,
            get_from_env,
            get_local_default,
            get_from_zeroconf,
            get_global_default,
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
                    if self._isvh == False:
                        newHost = await self._get_hostname_from_vBus(url)
                        if newHost != "":
                            new_host = newHost
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
            if self._creds != None:
                task = self._nats.connect(url, io_loop=self._loop, user_credentials=self._creds, connect_timeout=1, max_reconnect_attempts=2, closed_cb=self._async_nats_closed)
            else:
                task = nc.connect(url, loop=self._loop, user=user, password=pwd, connect_timeout=1,
                              max_reconnect_attempts=2)

            # Wait for at most 5 seconds, in some case nats library is stuck...
            await asyncio.wait_for(task, timeout=5)
        except Exception:
            return False
        else:
            return True

    async def _get_hostname_from_vBus(self, url: str, user="anonymous", pwd="anonymous") -> str:
        if not url:
            return ""

        serverIP = get_ip(VBUS_DNS)

        vbus_hostname = ""
        nc = Client()
        try:
            if self._creds == None :
                task = nc.connect(url, loop=self._loop, user=user, password=pwd, connect_timeout=1,
                                max_reconnect_attempts=2)

                # Wait for at most 5 seconds, in some case nats library is stuck...
                await asyncio.wait_for(task, timeout=5)

            try:
                if self._creds == None :                         
                    msg = await nc.request(PATH_TO_INFO, serverIP.encode('utf-8'), timeout=10)
                else:
                    msg = await self._nats.request(PATH_TO_INFO, serverIP.encode('utf-8'), timeout=10)
                data = msg.data.decode()
                LOGGER.debug(data)                          
                vbus_info = json.loads(data)
                vbus_hostname = vbus_info["hostname"]                      
            except ErrTimeout:
                print("Request vbus.info timed out")
        except Exception:
            return ""
        else:
            return vbus_hostname

    @staticmethod
    def _validate_configuration(c: Dict):
        """ Validate the config file structure. """
        return key_exists(c, 'client', 'user') and \
               key_exists(c, 'client', 'password') and \
               key_exists(c, 'client', 'permissions') and \
               key_exists(c, 'key', 'private') and \
               key_exists(c, 'vbus', 'url') and \
               key_exists(c, 'vbus', 'hostname') and \
               key_exists(c, 'vbus', 'networkIp')

    @staticmethod
    def _validate_configuration_v2(c: Dict):
        """ Validate the config file structure. """
        return key_exists(c, 'vbus', 'url') and \
               key_exists(c, 'vbus', 'hostname') and \
               key_exists(c, 'vbus', 'networkIp')
    
    def _check_config_hostname(self, c: Dict):
        _extracted_conf_name = c["client"]["user"].split('.')[2]
        if _extracted_conf_name != self._hostname:
            LOGGER.debug("Replace user: " + c["client"]["user"])
            c["client"]["user"] = c["client"]["user"].replace(_extracted_conf_name, self._hostname)
            LOGGER.debug("with: " + c["client"]["user"])

    def read_or_get_default_config(self) -> Dict:

        if not os.access(self._root_folder, os.F_OK):
            os.mkdir(self._root_folder)

        LOGGER.debug("check if we already have a Vbus config file in " + self._root_folder)
        config_file = os.path.join(self._root_folder, self._id + ".conf")
        if os.path.isfile(config_file):
            LOGGER.debug("load existing configuration file for " + self._id)
            with open(config_file, 'r') as content_file:
                content = content_file.read()
                config = json.loads(content)
                if self._creds != None :
                    if self._validate_configuration_v2(config):
                        return config
                    else:
                        LOGGER.warning('invalid configuration v2 detected, the file will be reset to the default one (%s)', config)
                        return self._create_default_config_v2()
                else :
                    if self._validate_configuration(config):
                        self._check_config_hostname(config)
                        return config
                    else:
                        LOGGER.warning('invalid configuration detected, the file will be reset to the default one (%s)', config)
                        return self._create_default_config()
        else:
            if self._creds != None :
                return self._create_default_config_v2()
            else:
                return self._create_default_config()

    def _create_default_config_v2(self):
        """ Creates the default configuration. """
        LOGGER.debug("create new configuration file v2 for " + self._id)
        # TODO: this template should be in a git repo shared between all vbus impl
        return {
            "vbus"  : {
                "url"      : None,
                "hostname" : None,
                "networkIp": None,
            }
        }

    def _create_default_config(self):
        """ Creates the default configuration. """
        from .helpers import generate_password

        LOGGER.debug("create new configuration file for " + self._id)

        password = generate_password()
        public_key = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=11, prefix=b"2a"))
        return {
            "client": {
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
            "key"   : {
                "private": password
            },
            "vbus"  : {
                "url"      : None,
                "hostname" : None,
                "networkIp": None,
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
            # start a task
            # we don't want to await here because it will block everything while computing the callback.
            asyncio.get_event_loop().create_task(self._subscribe_on_data_task(cb, regex, msg))

        return await self.nats.subscribe(path, cb=on_data)

    async def _subscribe_on_data_task(self, cb, regex, msg):
        m = re.match(regex, msg.subject)
        if m:
            try:
                ret = await cb(from_vbus(msg.data), *m.groups())
                if msg.reply:
                    await self._nats.publish(msg.reply, to_vbus(ret))
            except Exception as e:
                LOGGER.exception(e)

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
