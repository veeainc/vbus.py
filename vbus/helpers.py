import time
import string
import socket
import logging
from typing import cast
from random import choice
from zeroconf import ServiceBrowser, Zeroconf, ServiceStateChange

LOGGER = logging.getLogger(__name__)


def generate_password(length=22, chars=string.ascii_letters+string.digits):
    new_pass = []
    for i in range(length):
        new_pass.append(choice(chars))
    return ''.join(new_pass)


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
            if "vbus" == name.split(".")[0]:
                # next step compare host_name to choose the same one than the service if available
                LOGGER.debug("vbus found !!")
                if z_vbus_url == "":
                    z_vbus_url = "nats://" + socket.inet_ntoa(cast(bytes, info.address)) + ":" + str(info.port)
                    LOGGER.debug("zeroconf reconstruct: " + z_vbus_url)

    zeroconf = Zeroconf()
    # listener = MyListener()
    browser = ServiceBrowser(zeroconf, "_nats._tcp.local.", handlers=[on_service_state_change])

    time.sleep(5)
    zeroconf.close()
    return z_vbus_url
