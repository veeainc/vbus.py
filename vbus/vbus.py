

import os
import json
import socket
import bcrypt
import string
import asyncio
import time
import logging
from pydbus import SystemBus
from typing import cast
from random import choice
from contextlib import contextmanager

from zeroconf import ServiceBrowser, Zeroconf, ServiceStateChange
from nats.aio.client import Client as NATS
from nats.aio.errors import ErrConnectionClosed, ErrTimeout, ErrNoServers, ErrAuthorization

LOGGER = logging.getLogger(__name__)

def GenPasswd(length=22, chars=string.ascii_letters+string.digits):
    newpasswd = []
    for i in range(length):
        newpasswd.append(choice(chars))
    return ''.join(newpasswd)

async def test_vbus_url(url, loop, user="anonymous", pwd="anonymous"):
    nc = NATS()
    LOGGER.debug("test connection to: " + url + " with user: " + user + " and pwd: " + pwd)
    try:
        await nc.connect(url, loop=loop, user=user, password=pwd, connect_timeout=1, max_reconnect_attempts=2)
    except Exception as e: 
        LOGGER.warning(e)
        #raise e
        return False
    else:
        LOGGER.debug(url + " worked")
        await nc.close()
        return True

async def test_vbus_pub(to, msg, url, loop, user="anonymous", pwd="anonymous"):
    nc = NATS()
    LOGGER.debug("test pub to: " + url + " with user: " + user + " and pwd: " + pwd)
    try:
        await nc.connect(url, loop=loop, user=user, password=pwd, connect_timeout=1, max_reconnect_attempts=2)
    except Exception as e: 
        LOGGER.warning(e)
        #raise e
        return False
    else:
        LOGGER.debug(url + " worked")
        LOGGER.debug("send: " + str(msg))
        await nc.publish(to, msg)
        await nc.flush()
        await nc.close()
        return True

z_vbus_url = ""
def zeroconf_search():
    def on_service_state_change(
    zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange,
    ) -> None:
        global z_vbus_url
        LOGGER.debug("Service %s of type %s state changed: %s" % (name, service_type, state_change))

        if state_change is ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            LOGGER.debug("Service %s added, service info: %s" % (name, info))
            LOGGER.debug("Address: %s:%d" % (socket.inet_ntoa(cast(bytes, info.address)), cast(int, info.port)))
            if "vbus"==name.split("/")[0]:
            # next step compare host_name to choose the same one than the service if available
                LOGGER.debug("vbus found !!")
                if z_vbus_url == "":
                    z_vbus_url = "nats://" + socket.inet_ntoa(cast(bytes, info.address))+ ":" + str(info.port)
                    LOGGER.debug("zeroconf reconstruct: " + z_vbus_url)

    zeroconf = Zeroconf()
    #listener = MyListener()
    browser = ServiceBrowser(zeroconf, "_nats._tcp.local.", handlers=[on_service_state_change])
    
    time.sleep( 5 )
    zeroconf.close()
    return z_vbus_url
 
class Client(NATS):

    def __init__(self):
        super().__init__()
        self._loop = None
        #self.nc = self.localnc()
        self.element = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        super().__exit__()
        LOGGER.debug("vbus exit")

    def vClose(self):
        LOGGER.debug("here we close")

    async def vConnect(self,
                id,
                loop=None
                ):

        self._loop =  loop or asyncio.get_event_loop()

        # hostname = socket.gethostname()
        bus = SystemBus()
        hostname = bus.get('io.veea.VeeaHub.Info').hostname()

        rootfolder = os.environ['VBUS_PATH']
        if rootfolder == "":
            rootfolder = os.environ['HOME']
            rootfolder = rootfolder + "/vbus/"
        elif rootfolder.endswith("/") == False:
            rootfolder = rootfolder + "/"
        if os.access(rootfolder, os.F_OK) == False:
            os.mkdir(rootfolder)
        LOGGER.debug("check if we already have a vbus config file in " + rootfolder)
        if os.path.isfile(rootfolder + id + ".conf"):
            LOGGER.debug("load existing configuration file for " + id )
            self.element = json.loads(open (rootfolder + id + ".conf").read())
        else:
            LOGGER.debug("create new configuration file for " + id)
            #create user
            self.element = {}
            self.element["element"] = {}
            self.element["element"]["path"] = id
            self.element["element"]["name"] = id
            
            self.element["element"]["host"] = hostname
            self.element["element"]["uuid"] = hostname + "." + id
            self.element["element"]["bridge"] = "None"

            # Create a new User KeyPair
            password = GenPasswd()
            self.element["auth"] = {}
            self.element["auth"]["user"] = hostname + "." + id
            publickey = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=11, prefix=b"2a"))
            self.element["auth"]["password"] = publickey.decode('utf-8')
            self.element["auth"]["permissions"] = {}
            self.element["auth"]["permissions"]["subscribe"] = []
            self.element["auth"]["permissions"]["publish"] = []
            self.element["private"] = {}
            self.element["private"]["key"] = password

            self.element["vbus"] = {}
            self.element["vbus"]["url"] = None

        LOGGER.debug(self.element)

        LOGGER.debug("find vbus url")
        # find vbus server  - strategy 1: get url from config file
        if self.element["vbus"]["url"] != None:
            if await test_vbus_url(self.element["vbus"]["url"], self._loop) == True:
                LOGGER.debug("url from config file ok: " + self.element["vbus"]["url"])
            else:
                LOGGER.debug("url from config file hs: " + self.element["vbus"]["url"])
                self.element["vbus"]["url"] = None
            
        # find vbus server  - strategy 2: get url from ENV:VBUS_URL
        if self.element["vbus"]["url"] == None:
            env_vbus_url = os.environ.get("VBUS_URL")
            if (env_vbus_url != None) and (env_vbus_url != ""):
                if await test_vbus_url(env_vbus_url, self._loop) == True:
                    LOGGER.debug("url from ENV ok: " + env_vbus_url)
                    self.element["vbus"]["url"] = env_vbus_url
                else:
                    LOGGER.debug("url from ENV hs: " + env_vbus_url)

        # find vbus server  - strategy 3: try default url nats://hostname:21400
        if self.element["vbus"]["url"] == None:
            hostname = socket.gethostname()
            default_vbus_url = "nats://" + hostname + ".veeamesh.local:21400"
            if await test_vbus_url(default_vbus_url, self._loop) == True:
                LOGGER.debug("url from default ok: " + default_vbus_url)
                self.element["vbus"]["url"] = default_vbus_url
            else:
                LOGGER.debug("url from default hs: " + default_vbus_url)

        # find vbus server  - strategy 4: find it using avahi
        if self.element["vbus"]["url"] == None:
            zeroconf_vbus_url = zeroconf_search()
            if (zeroconf_vbus_url != None):
                if await test_vbus_url(zeroconf_vbus_url, self._loop) == True:
                    LOGGER.debug("url from discovery ok: " + zeroconf_vbus_url)
                    self.element["vbus"]["url"] = zeroconf_vbus_url
                else:
                    LOGGER.debug("url from discovery hs: " + zeroconf_vbus_url)
            else:
                LOGGER.debug("zeroconf found no url")

        if self.element["vbus"]["url"] == None:
            LOGGER.debug("no valid url vbus found")
            raise "error"

        # save config file
        LOGGER.debug("try to open config file " + rootfolder + id + ".conf")
        with open(rootfolder + id + ".conf", 'w+') as f:
            LOGGER.debug("record file: " + rootfolder + id + ".conf")
            json.dump(self.element, f)

        # connect to vbus server
        directconnect = True
        
        LOGGER.debug("open connection with local nats")
        if await test_vbus_url(self.element["vbus"]["url"], loop=self._loop, user=self.element["element"]["uuid"], pwd=self.element["private"]["key"]) == True:
            LOGGER.debug("vbus user already known")
        else:
            LOGGER.debug("vbus user unknown, try anonymous")
            if await test_vbus_url(self.element["vbus"]["url"], loop=self._loop) == True:
                directconnect = False
            else:
                LOGGER.error("anonymous user can't connect")
                LOGGER.error("can't connect")
                return
                
            

        LOGGER.debug("publish user")
        LOGGER.debug(json.dumps(self.element["auth"]).encode('utf-8'))
        await test_vbus_pub(to="system.auth.adduser", msg=json.dumps(self.element["auth"]).encode('utf-8'), url=self.element["vbus"]["url"], loop=self._loop)

        # if directconnect == False:
        #     print("try connect with real user")
        #     await self.nc.close()
        #     try:
        #         await self.nc.connect(self.element["vbus"]["url"], io_loop=self._loop, user=self.element["element"]["uuid"], password=self.element["private"]["key"], connect_timeout=0.5, max_reconnect_attempts=2,closed_cb=self.close)
        #     except:
        #         print("user not recognised by system")
        #         return
        await asyncio.sleep(1, loop=loop)

        try:
            await self.connect(self.element["vbus"]["url"], io_loop=self._loop, user=self.element["auth"]["user"], password=self.element["private"]["key"], connect_timeout=1, max_reconnect_attempts=2,closed_cb=self.close)
        except Exception as e: 
            LOGGER.error(e)
            LOGGER.error("user not recognised by system")
            return
        

        LOGGER.debug("publish element")
        LOGGER.debug(json.dumps(self.element["element"]).encode('utf-8'))
        try:
            await self.publish("system.db.newelement", json.dumps(self.element["element"]).encode('utf-8'))
        except:
            LOGGER.error("cannot publish new element")
            return

        try:
            await self.flush(10)
        except:
            LOGGER.error("Flush error")

    async def List(self, filter_json):
        message = None
        try:
            response = await self.request("system.db.getElementList", filter_json, 1)
            LOGGER.debug("Received response: {message}".format(
                message=response.data.decode()))
        except ErrTimeout:
            LOGGER.warning("Request timed out")
            
        return message

    async def Permission_Subscribe(self, permission):
        exist = False

        for x in self.element["auth"]["permissions"]["subscribe"]:
            if x == permission:
                exist = True
        
        if exist == False:
            self.element["auth"]["permissions"]["subscribe"].append(permission)
            await self.publish("system.auth.addpermissions", json.dumps(self.element["auth"]).encode('utf-8'))

    async def Permission_Publish(self, permission):
        exist = False

        for x in self.element["auth"]["permissions"]["publish"]:
            if x == permission:
                exist = True
        
        if exist == False:
            self.element["auth"]["permissions"]["publish"].append(permission)
            await self.publish("system.auth.addpermissions", json.dumps(self.element["auth"]).encode('utf-8'))

    # async def Request(self, dest, data):
    #     message = None
    #     try:
    #         response = await self.nc.request(dest, data, 0.5)
    #         print("Received response: {message}".format(
    #             message=response.data.decode()))
    #     except ErrTimeout:
    #         print("Request timed out")

    #     return message

    # async def Publish(self, dest, message):
    #     await self.nc.publish( dest, message)

    # async def Subscribe( self, dest, cb):

    #     async def message_handler(msg):
    #         cb(msg.data.decode())
    #         # subject = msg.subject
    #         # reply = msg.reply
    #         # data = msg.data.decode()
    #         # print("Received a message on '{subject} {reply}': {data}".format(
    #         #    subject=subject, reply=reply, data=data))

    #     # Simple publisher and async subscriber via coroutine.
    #     sid = await self.nc.subscribe(dest, cb=message_handler)