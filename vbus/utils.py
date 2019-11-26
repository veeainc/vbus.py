import json
import collections
from typing import Dict


def from_vbus(data: bytes) -> Dict:
    if data:
        return json.loads(data.decode('utf-8'))
    else:
        return None


def to_vbus(data: any) -> bytes:
    if data is None:
        return b''
    else:
        return json.dumps(data).encode('utf-8')


def is_sequence(obj):
    if isinstance(obj, str):
        return False
    return isinstance(obj, collections.Sequence)
