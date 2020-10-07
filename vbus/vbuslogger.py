"""
    vBus remote logger.
"""
from vbus import ExtendedNatsClient
import logging
import asyncio


SYSTEM_SEGMENT = "__system__"
TRACE_LEVEL_SEGMENT = "trace"
DEBUG_LEVEL_SEGMENT = "debug"
INFO_LEVEL_SEGMENT = "info"
WARNING_LEVEL_SEGMENT = "warning"
ERROR_LEVEL_SEGMENT = "error"


LOGGER = logging.getLogger(__name__)


class RemoteLogger:
    def __init__(self, nats: ExtendedNatsClient, namespace: str):
        if namespace != "":
            namespace = namespace + ": "

        self._nats = nats
        self._namespace = namespace
        self._path_mask = SYSTEM_SEGMENT + ".log.{}"

    async def _async_send(self, msg: str, level_segment: str):
        try:
            await self._nats.async_publish(self._path_mask.format(level_segment), self._namespace + msg)
        except Exception as e:
            LOGGER.exception(e)

    def _send(self, msg: str, level_segment: str):
        asyncio.get_event_loop(). create_task(self._async_send(msg, level_segment))