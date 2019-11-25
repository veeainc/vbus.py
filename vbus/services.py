import inspect
from typing import Callable, Dict
from nats.aio.client import Client
from .utils import from_vbus, to_vbus, is_sequence


class VBusServices:
    # Convert a Python type to a Json Schema one.
    py_types_to_json_schema = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        None: "null",
    }

    def __init__(self, nats: Client, app_id: str, hostname: str):
        self._nats = nats
        self._app_id = app_id
        self._hostname = hostname
        self._registry = {}
        self._initialized = False

    async def async_initialize(self):
        if self._initialized:
            return
        await self._nats.subscribe("services", cb=self._async_handle_get_services)
        self._initialized = True

    async def async_register(self, callback: Callable):
        """ Register a new callback as a service.
            The callback must be annotated with Python type.
            See: https://docs.python.org/3/library/typing.html

            :example:
            def scan(self, time: int) -> None:
                pass
        """
        self._validate_callback(callback)
        self._registry[callback.__name__] = callback
        await self.async_initialize()
        await self._nats.subscribe(
            f"{self._app_id}.{self._hostname}.services.{callback.__name__}",
            cb=self._async_handle_service_publish)

    @staticmethod
    def _validate_callback(callback: Callable):
        inspection = inspect.getfullargspec(callback)
        for arg in inspection.args:
            if arg == 'self':
                continue
            if arg not in inspection.annotations:
                raise ValueError("you must annotate your callback with type annotation (see "
                                 "https://docs.python.org/3/library/typing.html).")
            if inspection.annotations[arg] not in VBusServices.py_types_to_json_schema:
                raise ValueError(str(inspection.annotations[arg]) + " is not a supported python type.")

        if 'return' not in inspection.annotations:
            raise ValueError("you must annotate return value, even if its None.")

    async def _async_handle_service_publish(self, msg):
        callback_name = msg.subject.split(".")[-1]

        if callback_name in self._registry:
            args = from_vbus(msg.data)

            if is_sequence(args):
                ret = self._registry[callback_name](*args)
            else:
                ret = self._registry[callback_name](args)
            await self._nats.publish(msg.reply, to_vbus(ret))

    async def _async_handle_get_services(self, msg):
        await self._nats.publish(msg.reply, to_vbus(self.to_services()))

    def to_service(self, name: str) -> Dict:
        inspection = inspect.getfullargspec(self._registry[name])
        ann = inspection.annotations

        params_schema = {"type": "array", "items": []}
        for arg in inspection.args:
            params_schema["items"].append({
                "type": self.py_types_to_json_schema[ann[arg]],
                "description": arg
            })
        return_schema = {"type": self.py_types_to_json_schema[ann['return']]}

        return {
            "name": name,
            "host": self._hostname,
            "bridge": self._app_id,
            "version": "0.1.0",
            "params": params_schema,
            "returns": return_schema,
        }

    def to_services(self):
        return [self.to_service(n) for n in self._registry.keys()]
