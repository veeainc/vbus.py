import time
import json
import string
import socket
import pydbus
import logging
import collections
from typing import cast, Dict


LOGGER = logging.getLogger(__name__)


def get_hostname() -> str:
    """ Try to retrieve the hostname using Veea dbus api. If it fails, return
        socket.gethostname() value.
    """
    hostname = socket.gethostname()

    # try to get hostname if we are on a hub
    try:
        bus = pydbus.SystemBus()
        hostname = bus.get('io.veea.VeeaHub.Info').Hostname()
    except Exception:
        pass

    return hostname


def from_vbus(data: bytes) -> Dict:
    """ Convert json as bytes to Python object. """
    if data:
        return json.loads(data.decode('utf-8'))
    else:
        return None


def to_vbus(data: any) -> bytes:
    """ Convert Python object to json as bytes. """
    if data is None:
        return b''
    else:
        return json.dumps(data).encode('utf-8')


def join_path(*args: str) -> str:
    """ Join a path and skip ampty strings. """
    return '.'.join(filter(None, args))


def is_sequence(obj):
    if isinstance(obj, str):
        return False
    return isinstance(obj, collections.Sequence)


def generate_password(length=22, chars=string.ascii_letters+string.digits):
    from random import choice

    new_pass = []
    for i in range(length):
        new_pass.append(choice(chars))
    return ''.join(new_pass)


def zeroconf_search():
    from zeroconf import ServiceBrowser, Zeroconf, ServiceStateChange
    from socket import inet_ntoa

    vbus_url = ""

    def on_service_state_change(zeroconf: Zeroconf, service_type, name, state_change: ServiceStateChange) -> None:
        nonlocal vbus_url

        LOGGER.debug("Service %s of type %s state changed: %s" % (name, service_type, state_change))
        if state_change is ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            LOGGER.debug("Service %s added, service info: %s" % (name, info))
            LOGGER.debug("Address: %s:%d" % (inet_ntoa(cast(bytes, info.address)), cast(int, info.port)))
            if "vbus" == name.split(".")[0]:
                # next step compare host_name to choose the same one than the service if available
                LOGGER.debug("vbus found !!")
                if vbus_url == "":
                    vbus_url = "nats://" + inet_ntoa(cast(bytes, info.address)) + ":" + str(info.port)
                    LOGGER.debug("zeroconf reconstruct: " + vbus_url)

    zc = Zeroconf()
    browser = ServiceBrowser(zc, "_nats._tcp.local.", handlers=[on_service_state_change])
    time.sleep(5)
    zc.close()
    return vbus_url
