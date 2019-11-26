from typing import Dict

from .client import ExtendedNatsClient
from .methods import VBusMethodsClient


class VBusBridge:
    def __init__(self, client: ExtendedNatsClient, bridge_def: Dict):
        self._client = client
        self._methods = VBusMethodsClient(client, bridge_def["methods"])

    @property
    def methods(self):
        return self._methods
