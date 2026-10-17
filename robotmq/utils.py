import io
import math
import numpy as np
import pickle
import struct
import sys
from typing import Any
import os
import pwd
import warnings

from ._pickle_validation import validate_pickle as _validate_pickle

_SERIALIZE_DEPRECATION_MSG = (
    "robotmq.serialize is deprecated and will be removed in a future release: its "
    "output may require `deserialize`, which runs pickle.loads on untrusted bytes. "
    "Use robotmq.safe_serialize to restrict payloads to supported types instead."
)
_DESERIALIZE_DEPRECATION_MSG = (
    "robotmq.deserialize is deprecated and will be removed in a future release: it "
    "runs pickle.loads on untrusted bytes, which can execute arbitrary code. Use "
    "robotmq.safe_deserialize instead."
)


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
    """Deprecated: use `safe_serialize`, which `safe_deserialize` can read safely."""
    warnings.warn(_SERIALIZE_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
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
    """Deprecated: runs `pickle.loads` on untrusted bytes; use `safe_deserialize`."""
    warnings.warn(_DESERIALIZE_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    if len(data) == 0:
        warnings.warn(
            "robotmq.utils.deserialize: Received empty data. Will return None"
        )
        return None
    return _deserialize(pickle.loads(data))


# ---------------------------------------------------------------------------
# Safe serialization
#
# The legacy `deserialize` above runs `pickle.loads` on whatever arrives from
# the network, and a pickle can import any module and call any callable while
# loading, so a single malicious payload executes arbitrary code in the
# receiving process. `safe_serialize` / `safe_deserialize` keep the exact wire
# format of the legacy pair (a plain payload pickles to byte-identical bytes),
# but:
#
# * the writer walks the payload once, accepting leaves by exact type (str,
#   bytes, int, float, bool, None), dict / list / tuple (subclasses are
#   flattened to the plain container), numpy arrays of kind bool / int / uint /
#   float with at most 8-byte items, numpy scalars that convert to one of the
#   leaf types, and torch tensors (tagged dict, see `_tensor_to_wire`).
#   Everything else raises TypeError naming the path of the offending element;
# * before unpickling, the reader validates primitive opcodes, memo indices,
#   frame boundaries, the exact final STOP, and tuple/key complexity. It then
#   rebuilds containers, arrays and tensors under entry, key-work and byte
#   budgets. Normal decoding refusals are reported as `UnsafePayloadError`.
#   These checks bound specific amplification paths, not total process resources.
#
# The hot paths build no strings and raise a private `_Reject`; only the error
# path re-walks the payload to produce a message. Both walkers share the
# `_array_ok` / `_scalar_leaf` / `_tensor_ok` predicates so they cannot
# disagree. Array bytes retain their dtype's byte order, recorded in `dtype.str`.
# Torch tensors use native byte order without a marker, so tensor senders and
# receivers must share endianness.
# The legacy pair is deprecated (DeprecationWarning on every call) and kept
# only for backward compatibility.
# ---------------------------------------------------------------------------

_LEAF = frozenset((str, bytes, int, float, bool, type(None)))
_ARRAY_KINDS = frozenset("biuf")  # bool, signed int, unsigned int, float
_SCALAR_KINDS = frozenset("biufSU")  # numpy scalars allowed to convert via .item()
_MAX_ARRAY_ITEMSIZE = 8  # refuses longdouble / float128 (platform dependent)
_MAX_DTYPE_STR = 16  # a real `dtype.str` is at most ~8 characters
_MAX_TENSOR_DIMS = 64
_TENSOR_TAG = "__robotmq_torch_tensor__"
_TENSOR_KEYS = frozenset((_TENSOR_TAG, "dtype", "shape", "data"))
_ndarray, _generic = np.ndarray, np.generic


class UnsafePayloadError(pickle.UnpicklingError, ValueError):
    """Raised by `safe_deserialize` for normal decoding refusals.

    Covers a pickle that references a global / persistent id / copyreg
    extension, a malformed or truncated stream, trailing bytes, a forged torch
    tensor tag, and a payload that exceeds validation or reconstruction limits.
    Process-wide resource exhaustion can still raise MemoryError. Subclasses
    both `pickle.UnpicklingError` and `ValueError`,
    so code that caught either of those keeps working.
    """


class _Reject(Exception):
    """Internal: the fast writer refused `obj`; the slow walker names its path."""

    def __init__(self, obj: Any):
        super().__init__()
        self.obj = obj


# -- predicates shared by the fast writer and the error-path walker ----------


def _array_ok(arr: np.ndarray) -> bool:
    dt = arr.dtype
    return dt.kind in _ARRAY_KINDS and dt.itemsize <= _MAX_ARRAY_ITEMSIZE


def _scalar_leaf(scalar: np.generic) -> Any:
    """Convert a numpy scalar to a Python leaf, or raise `_Reject`.

    np.float32 / np.int64 / np.bool_ / np.str_ / np.bytes_ become float / int /
    bool / str / bytes. np.longdouble (`.item()` returns itself), complex,
    datetime64 / timedelta64 (`.item()` may return an int for ns precision) and
    void are refused.
    """
    if scalar.dtype.kind in _SCALAR_KINDS:
        v = scalar.item()
        if type(v) in _LEAF:
            return v
    raise _Reject(scalar)


def _tensor_ok(tensor, torch) -> bool:
    return (
        tensor.layout is torch.strided
        and not tensor.is_quantized
        and not tensor.is_nested
        and tensor.device.type != "meta"
    )


# -- writer -------------------------------------------------------------------


def _tensor_to_wire(tensor, torch) -> dict:
    """Encode a torch tensor as the tagged dict that travels on the wire.

    The tensor is detached, conj / neg bits are materialised, it is moved to
    the CPU and made contiguous; the payload is its raw bytes, so every dtype
    torch defines (bfloat16 included) survives without a numpy equivalent.
    """
    tensor = tensor.detach().resolve_conj().resolve_neg().cpu().contiguous()
    dtype_name = str(tensor.dtype)
    if dtype_name.startswith("torch."):
        dtype_name = dtype_name[len("torch.") :]
    if tensor.numel():
        data = tensor.view(-1).view(torch.uint8).numpy().tobytes()
    else:
        data = b""
    return {
        _TENSOR_TAG: 1,
        "dtype": dtype_name,
        "shape": tuple(tensor.shape),
        "data": data,
    }


def _plain_key(key: Any) -> bool:
    """True when a dict key needs no conversion: a leaf, or a tuple of plain keys.

    Such a key is passed through as the same object, as the legacy writer does,
    so a tuple key shared between dicts hits the pickle memo and the output
    stays byte-identical to `serialize`.
    """
    t = type(key)
    return t in _LEAF or (t is tuple and all(_plain_key(item) for item in key))


def _to_wire(obj: Any) -> Any:
    """Single-pass validate-and-convert for `safe_serialize` (hot path)."""
    t = type(obj)
    if t in _LEAF:
        return obj
    if t is dict:
        if _TENSOR_TAG in obj:
            raise _Reject(obj)
        return {
            (k if type(k) in _LEAF or _plain_key(k) else _to_wire(k)): (v if type(v) in _LEAF else _to_wire(v))
            for k, v in obj.items()
        }
    if t is list:
        return [v if type(v) in _LEAF else _to_wire(v) for v in obj]
    if t is tuple:
        return tuple([v if type(v) in _LEAF else _to_wire(v) for v in obj])
    if t is _ndarray:
        if not _array_ok(obj):
            raise _Reject(obj)
        return (obj.tobytes(), obj.dtype.str, obj.shape)
    return _to_wire_slow(obj)


def _to_wire_slow(obj: Any) -> Any:
    """Subclasses and rare types; everything not handled raises `_Reject`."""
    if isinstance(obj, dict):  # OrderedDict, defaultdict, ... -> plain dict
        return _to_wire(dict(obj))
    if isinstance(obj, list):
        return _to_wire(list(obj))
    if isinstance(obj, tuple):  # namedtuple -> plain tuple
        return _to_wire(tuple(obj))
    if isinstance(obj, _ndarray):  # np.matrix, MaskedArray -> base ndarray
        return _to_wire(np.asarray(obj))
    if isinstance(obj, _generic):
        return _scalar_leaf(obj)
    # A tensor can only exist if torch is already imported; never import it here.
    torch = sys.modules.get("torch")
    if torch is not None and isinstance(obj, torch.Tensor):
        if not _tensor_ok(obj, torch):
            raise _Reject(obj)
        return _tensor_to_wire(obj, torch)
    # bytearray, IntEnum, str / int subclasses, set, frozenset, dataclasses, ...
    raise _Reject(obj)


def _explain_reject(obj: Any, path: str = "payload") -> None:
    """Error path only: re-walk a refused payload and raise TypeError with the path.

    Uses the same predicates as `_to_wire` / `_to_wire_slow`, so it reaches the
    same verdict; the message names the element like `payload['a'][1]`.
    """
    if type(obj) in _LEAF:
        return
    if isinstance(obj, dict):
        if _TENSOR_TAG in obj:
            raise TypeError(f"{path}: reserved key {_TENSOR_TAG!r} is not allowed in a payload")
        for key, value in obj.items():
            _explain_reject(key, f"{path} key {key!r}")
            _explain_reject(value, f"{path}[{key!r}]")
        return
    if isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            _explain_reject(value, f"{path}[{i}]")
        return
    if isinstance(obj, _ndarray):
        if not _array_ok(np.asarray(obj)):
            raise TypeError(
                f"{path}: array dtype {obj.dtype} is not a plain numeric dtype (bool / int / "
                "uint / float with at most 8-byte items)"
            )
        return
    if isinstance(obj, _generic):
        try:
            _scalar_leaf(obj)
        except _Reject:
            raise TypeError(
                f"{path}: numpy scalar {type(obj).__name__} does not convert to str, bytes, "
                "int, float or bool"
            ) from None
        return
    torch = sys.modules.get("torch")
    if torch is not None and isinstance(obj, torch.Tensor):
        if not _tensor_ok(obj, torch):
            raise TypeError(
                f"{path}: only strided, non-quantized, non-nested, non-meta torch tensors can travel on a "
                f"safe robotmq payload (got layout={obj.layout}, device={obj.device})"
            )
        return
    raise TypeError(
        f"{path}: {type(obj).__module__}.{type(obj).__qualname__} cannot travel on a safe "
        "robotmq payload (allowed: dict, list, tuple, str, bytes, int, float, bool, None, "
        "numeric numpy arrays and scalars, torch tensors)"
    )


def safe_serialize(data: Any) -> bytes:
    """Serialize `data` so that `safe_deserialize` can read it.

    Same pickle wire format as `serialize`: a payload of builtins and numpy
    arrays produces byte-identical output, so a `safe_deserialize` server
    accepts legacy `serialize` clients and a legacy `deserialize` client reads
    `safe_serialize` replies.

    What travels: str, bytes, int, float, bool, None (exact types only; a
    `bytearray`, an `IntEnum` or a str / int subclass raises TypeError), dict /
    list / tuple (subclasses such as OrderedDict, defaultdict and namedtuple
    are flattened to the plain container, as the legacy writer did), numpy
    arrays of kind bool / int / uint / float with items of at most 8 bytes
    (object, str, void, complex, datetime and longdouble arrays are refused;
    subclasses go through `np.asarray`), numpy scalars that convert to a leaf
    (np.float32 -> float, np.int64 -> int, np.bool_ -> bool; longdouble,
    complex, datetime64 and timedelta64 are refused), and torch tensors, which
    travel as a tagged dict (`{"__robotmq_torch_tensor__": 1, "dtype",
    "shape", "data"}`) after detach / resolve_conj / resolve_neg / cpu /
    contiguous (sparse, quantized, nested and meta tensors are refused). The tagged
    form is safe <-> safe only: legacy `deserialize` returns the dict, and
    `safe_deserialize` refuses a pickled tensor sent by `serialize`. A dict
    that already contains the reserved tag key anywhere, and every other type
    (`set`, `frozenset`, dataclasses, pathlib paths, ...), raise TypeError
    naming the path of the offending element, e.g. `payload['a'][1]`.

    Array bytes retain their dtype's byte order, recorded in `dtype.str`.
    Torch tensors use native byte order without a marker, so both ends must
    share endianness when exchanging tensors.
    """
    try:
        wire = _to_wire(data)
    except _Reject as exc:
        _explain_reject(data)  # raises TypeError with the path; must agree with _to_wire
        bad = type(exc.obj)
        raise TypeError(
            f"payload: {bad.__module__}.{bad.__qualname__} cannot travel on a safe robotmq payload"
        ) from None
    return pickle.dumps(wire)


# -- reader -------------------------------------------------------------------


class _NoGlobals(pickle.Unpickler):
    """Unpickler that refuses every global lookup and every persistent id.

    Without a global the stream cannot name a class or a function, so none of
    REDUCE / BUILD / NEWOBJ / INST / OBJ can call anything: only the literal
    containers and scalars that `safe_serialize` emits can be rebuilt.
    """

    def find_class(self, module, name):
        raise UnsafePayloadError(
            f"safe_deserialize: payload references {module}.{name}; only builtins, numpy "
            "arrays and tagged torch tensors travel on a safe robotmq payload"
        )

    def persistent_load(self, pid):
        raise UnsafePayloadError("safe_deserialize: persistent ids are not allowed")


_TORCH_DTYPES: "dict[str, Any] | None" = None


def _torch_dtypes() -> dict:
    """`{"float32": torch.float32, ...}`, built once from `vars(torch)`.

    This is the only place the reader imports torch, and a dtype name is
    looked up in this static table, never with `getattr(torch, name)`, which
    would trigger torch's lazy submodule imports on an attacker-chosen name.
    """
    global _TORCH_DTYPES
    if _TORCH_DTYPES is None:
        try:
            import torch
        except ImportError as exc:
            raise UnsafePayloadError(
                "safe_deserialize: payload carries a torch tensor but torch is not installed"
            ) from exc
        _TORCH_DTYPES = {k: v for k, v in vars(torch).items() if isinstance(v, torch.dtype)}
    return _TORCH_DTYPES


def _tensor_from_wire(wire: dict, budget: list) -> Any:
    """Rebuild a CPU tensor from a tagged dict, validating every field first.

    Raises UnsafePayloadError when the dtype name is not a torch dtype, the
    shape is not a tuple / list of at most 64 non-negative ints below 2**63,
    the data is not bytes, or the byte count does not match shape x dtype.
    """
    dtypes = _torch_dtypes()
    name = wire["dtype"]
    if type(name) is not str or name not in dtypes:
        # Rendering untrusted containers can expand shared graphs exponentially.
        raise UnsafePayloadError("safe_deserialize: unknown torch dtype")
    dtype = dtypes[name]
    raw_shape = wire["shape"]
    if type(raw_shape) not in (tuple, list) or len(raw_shape) > _MAX_TENSOR_DIMS or not all(
        type(d) is int and 0 <= d < (1 << 63) for d in raw_shape
    ):
        raise UnsafePayloadError("safe_deserialize: invalid tensor shape")
    shape = tuple(raw_shape)
    data = wire["data"]
    if type(data) not in (bytes, bytearray):
        raise UnsafePayloadError("safe_deserialize: tensor payload is not bytes")
    budget[1] -= len(data)
    if budget[1] < 0:
        raise UnsafePayloadError(
            "safe_deserialize: tensor bytes exceed the payload size (shared references)"
        )
    if math.prod(shape) * dtype.itemsize != len(data):  # Python ints: no overflow
        raise UnsafePayloadError(
            f"safe_deserialize: tensor payload of {len(data)} bytes does not match "
            f"shape {shape} x {dtype}"
        )
    import torch  # already imported by _torch_dtypes()

    if not data:
        return torch.empty(shape, dtype=dtype, device="cpu")
    # bytes -> writable uint8 tensor (one copy) -> reinterpret -> reshape
    return torch.frombuffer(bytearray(data), dtype=torch.uint8).view(dtype).reshape(shape)


def _charge_key(key: Any, budget: list) -> None:
    """Charge repeated tuple/int hashing when rebuilding memo-shared dicts."""
    if type(key) is int:
        bits = sys.int_info.bits_per_digit
        budget[0] -= max(1, (key.bit_length() + bits - 1) // bits)
    else:
        budget[0] -= 1
    if budget[0] < 0:
        raise UnsafePayloadError("safe_deserialize: dictionary key hashing exceeds the payload size")
    if type(key) is tuple:
        for item in key:
            _charge_key(item, budget)


def _from_wire(obj: Any, budget: list) -> Any:
    """Single pass over the unpickled graph: rebuild arrays and tensors under a budget.

    `budget` is `[entries_left, array_bytes_left]`, both starting at the wire
    size. Charge each dict entry, key's hashing work, and list / tuple slot
    before rebuilding its container, including slots holding leaves; arrays /
    tensors also cost their byte length. Preflight separately bounds unpickling.
    """
    t = type(obj)
    if t in _LEAF:
        return obj
    budget[0] -= len(obj) if t in (dict, list, tuple) else 1
    if budget[0] < 0:
        raise UnsafePayloadError(
            "safe_deserialize: payload expands beyond its wire size (shared or cyclic references)"
        )
    if t is dict:
        if _TENSOR_TAG in obj:
            tag = obj[_TENSOR_TAG]
            if type(tag) is int and tag == 1 and len(obj) == 4 and obj.keys() == _TENSOR_KEYS:
                return _tensor_from_wire(obj, budget)
        result = {}
        for key, value in obj.items():
            _charge_key(key, budget)
            result[key] = value if type(value) in _LEAF else _from_wire(value, budget)
        return result
    if t is list:
        return [v if type(v) in _LEAF else _from_wire(v, budget) for v in obj]
    if t is tuple:
        if (
            len(obj) == 3
            and type(obj[0]) is bytes
            and type(obj[1]) is str
            and type(obj[2]) is tuple
            and len(obj[1]) <= _MAX_DTYPE_STR
        ):
            try:
                array = np.frombuffer(obj[0], dtype=obj[1]).reshape(obj[2])
            except Exception:
                pass  # not an array triple after all: legacy behavior keeps the tuple
            else:
                budget[1] -= array.nbytes
                if budget[1] < 0:
                    raise UnsafePayloadError(
                        "safe_deserialize: array bytes exceed the payload size (shared references)"
                    )
                return array.copy()
        return tuple([v if type(v) in _LEAF else _from_wire(v, budget) for v in obj])
    return obj  # set / frozenset / bytearray from a legacy client: returned as-is


_WRAPPED_ERRORS = (
    pickle.UnpicklingError,
    ValueError,
    TypeError,
    AttributeError,
    KeyError,
    IndexError,
    RecursionError,
    RuntimeError,
    OverflowError,
    EOFError,
    struct.error,
    ImportError,
)


def safe_deserialize(data: bytes) -> Any:
    """Deserialize bytes from `safe_serialize` (or a plain `serialize` payload).

    Before unpickling, a stdlib opcode pass checks primitive types, stack and
    memo operations, frame boundaries and the exact final STOP. Globals,
    reducers, persistent ids, extensions and external buffers are refused;
    the restricted unpickler also refuses globals and persistent ids. A
    `set` / `frozenset` from a legacy client is still read, because
    its pickle needs no global, and arrays are accepted with any dtype numpy
    can read from a buffer (complex, datetime, structured ...), not just the
    kinds the writer emits, so legacy clients keep working; an object-dtype
    triple cannot be rebuilt and arrives as the `(bytes, "|O", shape)` tuple,
    exactly as with `deserialize`. The `(bytes, str, tuple)` triple is
    inherently ambiguous with a user tuple of that shape; this is inherited
    from the legacy wire format. Arrays come back writable (one copy).

    Normal decoding refusals raise `UnsafePayloadError` (a
    `pickle.UnpicklingError` and a `ValueError`). Memo indices must be below
    `len(data)`, tuple and MARK nesting are limited to 128, and estimated key
    hashing work is bounded by the wire size. Reconstruction has separate
    wire-size budgets for container entries plus key work, and array / tensor
    bytes. Excessively shared or deep graphs may be refused even if generated
    by a legitimate writer. These limits are not a CPU or memory sandbox:
    large inputs or pathological hash collisions still require application
    limits; process-wide resource exhaustion may raise MemoryError.
    Torch is imported when the tag marker and keys match, before validating
    its fields. The dtype name is checked against a static table (never
    `getattr(torch, name)`); if torch is not installed such a payload raises
    `UnsafePayloadError`.
    Empty bytes return None with a warning, matching `deserialize`.
    """
    if len(data) == 0:
        warnings.warn(
            "robotmq.utils.safe_deserialize: Received empty data. Will return None"
        )
        return None
    try:
        # Freeze bytes-like callers once so validation and loading cannot see
        # different content if another thread mutates the input buffer.
        if type(data) is not bytes:
            data = memoryview(data).tobytes()
        _validate_pickle(data)
        stream = io.BytesIO(data)
        obj = _NoGlobals(stream).load()
        if stream.tell() != len(data):
            raise UnsafePayloadError(
                f"safe_deserialize: {len(data) - stream.tell()} trailing bytes after STOP"
            )
        return _from_wire(obj, [len(data), len(data)])
    except UnsafePayloadError:
        raise
    except _WRAPPED_ERRORS as exc:
        raise UnsafePayloadError(f"safe_deserialize: {exc}") from exc


def clear_shared_memory():
    try:
        user_name = os.getlogin()
    except OSError:
        # Match the native transport's get_user_name() in headless sessions.
        try:
            user_name = pwd.getpwuid(os.getuid()).pw_name
        except KeyError:
            user_name = str(os.getuid())

    for file in os.listdir("/dev/shm"):
        if file.startswith(f"rmq_{user_name}_"):
            os.remove(f"/dev/shm/{file}")
