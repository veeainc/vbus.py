from typing import Dict, Callable
from .client import ExtendedNatsClient


OnGetNodeCallback = Callable[[str or None], any]


class VBusNodes:
    def __init__(self, client: ExtendedNatsClient):
        self._client = client
        self._initialized = False
        self._on_get_nodes: OnGetNodeCallback = lambda uuid: {}  # by default empty response

    async def async_initialize(self):
        if self._initialized:
            return
        await self._client.async_subscribe("nodes", cb=self._async_get_nodes)
        await self._client.async_subscribe("nodes", "*", cb=self._async_get_node)
        self._initialized = True

    async def _async_get_nodes(self, data, reply: str):
        """ Get all nodes. """
        return self._on_get_nodes(None)

    async def _async_get_node(self, data, reply: str, node_uuid: str):
        """ Get one node. """
        return self._on_get_nodes(node_uuid)

    async def async_on_get_nodes(self, callback: OnGetNodeCallback):
        await self.async_initialize()
        self._on_get_nodes = callback

    def get_nodes(self):
        return self._on_get_nodes(None)  # get all

