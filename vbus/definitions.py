"""
    This module contains node definition classes.
    Theses classes are used to hold user data like the json structure, callbacks, etc...
    They are not connected to the bus. They just act as a data holder.
    Each of theses classes can be serialized to Json to be sent on Vbus.
"""
import json
import inspect
from abc import ABC, abstractmethod
from typing import Callable, Dict, List


class Definition(ABC):
    """ Base class for creating an element definition.
    """
    def __init__(self):
        self._structure = {}

    @property
    def definition(self) -> Dict:
        return self._structure

    def search_path(self, parts: List[str]) -> 'Definition' or None or any:
        """ Search for a path in this definition.
            It can returns a Definition class or a dictionary or none if not found.
        """
        if not parts:
            return self

        root = self.definition
        for i, part in enumerate(parts):
            if part in root:
                root = root[part]
                if isinstance(root, Definition):
                    return root.search_path(parts[i + 1:])
            else:
                return None  # not found
        return root

    def add_child(self, uuid: str, node: 'Definition'):
        """ Add a child element to this definition. """
        self._structure[uuid] = node

    def remove_child(self, uuid: str) -> 'Definition' or None:
        """ Remove a child element from this definition. """
        if uuid not in self._structure:
            return None

        builder = self._structure[uuid]
        del self._structure[uuid]
        return builder

    @abstractmethod
    async def handle_set(self, data: any, parts: List[str]):
        """ Tells how to handle a set request from Vbus. """
        pass

    @abstractmethod
    def to_json(self) -> any:
        """ Convert this definition to a Json Python Object."""
        pass


class MethodDef(Definition):
    """ A Method definition.
        It holds a user callback.
    """
    def __init__(self, method: Callable):
        super().__init__()
        self._method = method

    def to_json(self) -> any:
        inspection = inspect.getfullargspec(self._method)
        ann = inspection.annotations

        params_schema = {"type": "array", "items": []}
        for arg in inspection.args:
            params_schema["items"].append({
                "type": MethodDef.py_types_to_json_schema[ann[arg]],
                "description": arg
            })
        return_schema = {"type": MethodDef.py_types_to_json_schema[ann['return']]}

        return {
            "params": params_schema,
            "returns": return_schema,
        }

    # Convert a Python type to a Json Schema one.
    py_types_to_json_schema = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        None: "null",
    }

    def validate_callback(self):
        inspection = inspect.getfullargspec(self._method)
        for arg in inspection.args:
            if arg == 'self':
                continue
            if arg not in inspection.annotations:
                raise ValueError("you must annotate your callback with type annotation (see "
                                 "https://docs.python.org/3/library/typing.html).")
            if inspection.annotations[arg] not in MethodDef.py_types_to_json_schema:
                raise ValueError(str(inspection.annotations[arg]) + " is not a supported python type.")

        if 'return' not in inspection.annotations:
            raise ValueError("you must annotate return value, even if its None.")

    async def handle_set(self, data: any, parts: List[str]):
        return await self._method(data)


class NodeDef(Definition):
    """ A node definition.
        It holds a user structure (Python object) and optional callbacks.
    """
    def __init__(self, node_raw_def: Dict, on_write: Callable = lambda: None):
        super().__init__()
        self._structure = node_raw_def
        self._on_write = on_write

    def to_json(self) -> any:
        return self._structure

    async def handle_set(self, data: any, parts: List[str]):
        return await self._on_write(data, parts)


class VBusBuilderEncoder(json.JSONEncoder):
    """ A custom Python Json encoder to tell how to convect Definition classes to json. """
    def default(self, o):
        if isinstance(o, Definition):
            return o.to_json()
        else:
            raise ValueError("unknown type: " + type(o))

