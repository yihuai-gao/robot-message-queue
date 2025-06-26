import numpy as np
import numpy.typing as npt
import pickle
from typing import Any, Dict, List, Tuple, Union


def _serialize(data: Any):
    if isinstance(data, dict):
        return {key: _serialize(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [_serialize(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(_serialize(item) for item in data)
    elif isinstance(data, np.ndarray):
        return (data.data.tobytes(), data.dtype.str, data.shape)
    # elif (
    #     isinstance(data, bytes)
    #     or isinstance(data, str)
    #     or isinstance(data, int)
    #     or isinstance(data, float)
    #     or data is None
    # ):
    else:
        return data


def serialize(data: Any) -> bytes:
    return pickle.dumps(_serialize(data))


def _deserialize(data: Any):
    if isinstance(data, dict):
        return {key: _deserialize(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [_deserialize(item) for item in data]
    elif isinstance(data, tuple):
        if (
            len(data) == 3
            and isinstance(data[0], bytes)
            and isinstance(data[1], str)
            and isinstance(data[2], tuple)
        ):
            try:
                return np.frombuffer(data[0], dtype=data[1]).reshape(data[2]).copy()
            except Exception as e:
                pass
        return tuple(_deserialize(item) for item in data)
    # elif (
    #     isinstance(data, bytes)
    #     or isinstance(data, str)
    #     or isinstance(data, int)
    #     or isinstance(data, float)
    #     or data is None
    # ):
    #     return data
    # else:
    #     raise ValueError(f"Unsupported type: {type(data)}")
    else:
        return data


def deserialize(data: bytes) -> Any:
    return _deserialize(pickle.loads(data))
