import json
import collections
from typing import Dict


def from_vbus(data: bytes) -> Dict:
    return json.loads(data.decode('utf-8'))


def to_vbus(dict: any) -> bytes:
    return json.dumps(dict).encode('utf-8')


def is_sequence(obj):
    if isinstance(obj, str):
        return False
    return isinstance(obj, collections.Sequence)
