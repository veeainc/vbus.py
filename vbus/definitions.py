"""
    This module contains node definition classes.
    Theses classes are used to hold user data like the json structure, callbacks, etc...
    They are not connected to Vbus. They just act as a data holder.
    Each of theses classes can be serialized to Json to be sent on Vbus.
"""
import inspect
import genson
from abc import ABC, abstractmethod
from typing import Callable, Dict, List


class Definition(ABC):
    """ Base class for creating an element definition. """
    def __init__(self):
        pass

    def search_path(self, parts: List[str]) -> 'Definition' or None:
        """ Search for a path in this definition.
            It can returns a Definition class or a dictionary or none if not found.
        """
        if not parts:
            return self
        return None

    @abstractmethod
    async def handle_set(self, data: any, parts: List[str]):
        """ Tells how to handle a set request from Vbus. """
        pass

    @abstractmethod
    def to_json(self) -> any:
        """ Get the Json representation (as a Python Object)."""
        pass

    @abstractmethod
    def to_schema(self) -> any:
        """ Get the Json Schema representation (as a Python Object)."""
        pass


class MethodDef(Definition):
    """ A Method definition.
        It holds a user callback.
    """
    def __init__(self, method: Callable):
        super().__init__()
        self._method = method
        self._name = method.__name__

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
            "params": {
                "schema": params_schema
            },
            "returns": {
                "schema": return_schema
            },
        }

    def to_schema(self) -> any:
        return None


class AttributeDef(Definition):
    def __init__(self, uuid: str, value: any):
        super().__init__()
        assert value is not None, f"attribute {uuid} must not be null, use instead an EmptyAttrDef"
        self._key = uuid
        self._value = value

    async def handle_set(self, data: any, parts: List[str]):
        pass

    def to_json(self) -> any:
        return {
            'schema': self.to_schema(),
            'value': self._value,
        }

    def to_schema(self) -> any:
        # we use genson library to determine schema type:
        try:
            builder = genson.SchemaBuilder()
            builder.add_object(self._value)
            schema = builder.to_schema()
            schema.pop("$schema", None)
            return schema
        except genson.schema.node.SchemaGenerationError as e:
            raise TypeError(f"Invalid attribute type for {self._key}, type is {type(self._value)} ({str(e)})")


class EmptyAttrDef(Definition):
    """ Used to declare an attribute without value at the declaration moment. """
    def __init__(self, uuid: str, type_json_schema: dict):
        super().__init__()
        self._key = uuid
        self._type = type_json_schema

    async def handle_set(self, data: any, parts: List[str]):
        pass

    def to_json(self) -> any:
        return {
            'schema': self._type,
        }

    def to_schema(self) -> any:
        pass


class NodeDef(Definition):
    """ A node definition.
        It holds a user structure (Python object) and optional callbacks.
    """
    def __init__(self, node_def: Dict, on_write: Callable = lambda: None):
        super().__init__()
        self._initialize_structure(node_def)
        self._structure = node_def
        self._on_write = on_write

    def _initialize_structure(self, node_def: Dict):
        """ Take a node definition (raw dict) and replace them with attributes and nodes. """
        for k, v in node_def.items():
            if isinstance(v, dict):
                node_def[k] = NodeDef(v)
            elif not isinstance(v, Definition):
                node_def[k] = AttributeDef(k, v)

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

    async def handle_set(self, data: any, parts: List[str]):
        return await self._on_write(data, parts)

    def search_path(self, parts: List[str]) -> Definition or None:
        if not parts:
            return self
        elif parts[0] in self._structure:
            return self._structure[parts[0]].search_path(parts[1:])
        return None

    def to_json(self) -> any:
        return {k: v.to_json() for k, v in self._structure.items()}

    def to_schema(self) -> any:
        # we use genson library to determine schema type:
        builder = genson.SchemaBuilder()

        for k, v in self._structure.items():
            if isinstance(v, AttributeDef):
                builder.add_object({k: v.to_schema()})
            elif isinstance(v, NodeDef):
                builder.add_object({k: {}})

        # clean unused properties
        schema = builder.to_schema()
        schema.pop("$schema", None)
        schema.pop("required", None)
        return schema


# some aliases
N = NodeDef
A = AttributeDef
EA = EmptyAttrDef
M = MethodDef
