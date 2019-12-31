"""
    Builder elements are used to build a node definition.
"""
import json
import inspect
from abc import ABC, abstractmethod
from typing import Callable, Dict, List


class NodeBuilder(ABC):
    """ A Json serializable class. """
    def __init__(self):
        self._definition = {}

    @property
    def definition(self) -> Dict:
        return self._definition

    def search(self, parts: List[str]) -> 'NodeBuilder' or None or any:
        root = self.definition
        for i, part in enumerate(parts):
            if part in root:
                root = root[part]
                if i < len(parts) - 1 and isinstance(root, NodeBuilder):
                    root = root.definition
            else:
                return None  # not found
        return root

    def add_node(self, uuid: str, node: 'NodeBuilder'):
        self._definition[uuid] = node

    def remove_node(self, uuid: str) -> 'NodeBuilder' | None:
        if not uuid in self._definition:
            return None

        builder = self._definition[uuid]
        del self._definition[uuid]
        return builder

    @abstractmethod
    async def handle_set(self, data: any, parts: List[str]):
        pass

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

    async def handle_set(self, data: any, parts: List[str]):
        return await self._method(data)


class Node(NodeBuilder):
    """ A standard node element on which we can listen for incoming VBus events. """
    def __init__(self, node_def: Dict, on_write: Callable = lambda: None):
        super().__init__()
        self._definition = node_def
        self._on_write = on_write

    @property
    def on_write(self):
        return self._on_write

    def to_json(self) -> any:
        return self._definition

    async def handle_set(self, data: any, parts: List[str]):
        return await self._on_write(data, parts)


class VBusBuilderEncoder(json.JSONEncoder):
    """ Vbus json encoder used to transform a node definition into Json. """
    def default(self, o):
        if isinstance(o, NodeBuilder):
            return o.to_json()
        else:
            raise ValueError("unknown type: " + type(o))

