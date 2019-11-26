import inspect
from typing import Callable, Dict
from jsonschema import validate
from .utils import from_vbus, to_vbus, is_sequence
from .client import ExtendedNatsClient


class VBusMethods:
    # Convert a Python type to a Json Schema one.
    py_types_to_json_schema = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        None: "null",
    }

    def __init__(self, nats: ExtendedNatsClient):
        self._nats = nats
        self._registry = {}
        self._initialized = False

    async def async_initialize(self):
        if self._initialized:
            return
        await self._nats.async_subscribe("methods", cb=self._async_on_get_methods)
        await self._nats.async_subscribe("methods", "*", cb=self._async_on_get_method)
        self._initialized = True

    async def async_register(self, callback: Callable):
        """ Register a new callback as a method.
            The callback must be annotated with Python type.
            See: https://docs.python.org/3/library/typing.html

            :example:
            def scan(self, time: int) -> None:
                pass
        """
        self._validate_callback(callback)
        self._registry[callback.__name__] = callback
        await self.async_initialize()

    @staticmethod
    def _validate_callback(callback: Callable):
        inspection = inspect.getfullargspec(callback)
        for arg in inspection.args:
            if arg == 'self':
                continue
            if arg not in inspection.annotations:
                raise ValueError("you must annotate your callback with type annotation (see "
                                 "https://docs.python.org/3/library/typing.html).")
            if inspection.annotations[arg] not in VBusMethods.py_types_to_json_schema:
                raise ValueError(str(inspection.annotations[arg]) + " is not a supported python type.")

        if 'return' not in inspection.annotations:
            raise ValueError("you must annotate return value, even if its None.")

    async def _async_on_get_method(self, args, method_name: str):
        if method_name in self._registry:
            if is_sequence(args):
                return await self._registry[method_name](*args)
            else:
                return await self._registry[method_name](args)

    async def _async_on_get_methods(self, msg):
        await self._nats.async_publish(msg.reply, self.get_methods())

    def get_method(self, name: str) -> Dict:
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
            "host": self._nats.hostname,
            "bridge": self._nats.id,
            "version": "0.1.0",
            "params": params_schema,
            "returns": return_schema,
        }

    def get_methods(self):
        return {n: self.get_method(n) for n in self._registry.keys()}


class VBusMethodsClient:
    def __init__(self, nats: ExtendedNatsClient, methods_def: Dict):
        self._nats = nats
        self._methods_def = methods_def

    def __getattr__(self, attr: str):
        if attr in self._methods_def:
            method = self._methods_def[attr]
            # return a wrapper to capture args
            params_schema = method["params"]

            async def wrapper(*args, timeout: int = 0.5):
                # validate args against json schema
                validate(list(args), schema=params_schema)
                # make nats request
                return await self._nats.async_request(f"{method['bridge']}.{method['host']}.methods.{attr}", args, timeout=timeout)
            return wrapper
        else:
            raise ValueError("method does not exist on remote bridge. Available methods are: " +
                             ", ".join(self._methods_def.keys()))













