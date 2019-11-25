from typing import Dict, Callable

from vbus.utils import to_vbus
from .client import ExtendedClient


class VBusNodes:
    def __init__(self, client: ExtendedClient):
        self._client = client
        self._initialized = False
        self._registry: Dict[str, Callable] = {}

    async def async_initialize(self):
        if self._initialized:
            return
        await self._client.async_subscribe("nodes", "*", cb=self._async_get_nodes)
        await self._client.async_subscribe("nodes", "*", "*", cb=self._async_get_node)
        self._initialized = True

    async def _async_get_nodes(self, data, reply: str, node_type: str):
        """ Get all nodes. """
        if node_type in self._registry:
            await self._client.nats.publish(reply, to_vbus(self._registry[node_type]()))

    async def _async_get_node(self, data, reply: str, node_type: str, node_uuid: str):
        """ Get one node. """
        if node_type in self._registry:
            await self._client.nats.publish(reply, to_vbus(self._registry[node_type](node_uuid)))

    async def async_on_get_nodes(self, nodes: str, callback: Callable):
        await self.async_initialize()
        self._registry[nodes] = callback


