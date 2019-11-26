import socket
import pydbus


def get_hostname() -> str:
    hostname = socket.gethostname()

    # try to get hostname if we are on a hub
    try:
        bus = pydbus.SystemBus()
        hostname = bus.get('io.veea.VeeaHub.Info').Hostname()
    except Exception:
        pass

    return hostname
