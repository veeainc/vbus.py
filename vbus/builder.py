"""
    Builder elements are used to build a node definition.
"""
import json
import inspect
from abc import ABC, abstractmethod
from typing import Callable, Dict


class NodeBuilder(ABC):
    """ A Json serializable class. """
    def __init__(self):
        pass

    @property
    def definition(self) -> Dict:
        return {}

    @abstractmethod
    def to_json(self) -> any:
        pass


class Method(NodeBuilder):
    """ A Method node. """
    def __init__(self, method):
        super().__init__()
        self._method = method

    @property
    def method(self):
        return self._method

    def to_json(self) -> any:
        inspection = inspect.getfullargspec(self.method)
        ann = inspection.annotations

        params_schema = {"type": "array", "items": []}
        for arg in inspection.args:
            params_schema["items"].append({
                "type": Method.py_types_to_json_schema[ann[arg]],
                "description": arg
            })
        return_schema = {"type": Method.py_types_to_json_schema[ann['return']]}

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
        inspection = inspect.getfullargspec(self.method)
        for arg in inspection.args:
            if arg == 'self':
                continue
            if arg not in inspection.annotations:
                raise ValueError("you must annotate your callback with type annotation (see "
                                 "https://docs.python.org/3/library/typing.html).")
            if inspection.annotations[arg] not in Method.py_types_to_json_schema:
                raise ValueError(str(inspection.annotations[arg]) + " is not a supported python type.")

        if 'return' not in inspection.annotations:
            raise ValueError("you must annotate return value, even if its None.")


class Node(NodeBuilder):
    """ A standard node element on which we can listen for incoming VBus events. """
    def __init__(self, node_def: Dict, on_write: Callable = lambda: None):
        super().__init__()
        self._node_def = node_def
        self._on_write = on_write

    @property
    def definition(self) -> Dict:
        return self._node_def

    @property
    def on_write(self):
        return self._on_write

    def to_json(self) -> any:
        return self._node_def


class VBusBuilderEncoder(json.JSONEncoder):
    """ Vbus json encoder used to transform a node definition into Json. """
    def default(self, o):
        if isinstance(o, NodeBuilder):
            return o.to_json()
        else:
            raise ValueError("unknown type: " + type(o))

