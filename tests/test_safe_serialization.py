"""Tests for robotmq.safe_serialize / safe_deserialize.

The safe pair shares the pickle wire format of the legacy serialize /
deserialize pair but refuses every global on read (no code execution) and
every non-plain type on write. Torch tests are skipped when torch is missing.

The legacy pair is deprecated and warns on every call. The cross-compatibility
tests below call it on purpose (that is what they check), so they go through
``_legacy_serialize`` / ``_legacy_deserialize``, which silence the deprecation
warning; ``pytestmark`` turns any unwrapped legacy call in this file into an
error. ``TestLegacyDeprecation`` checks the warning itself.
"""

import collections
import copyreg
import enum
import pathlib
import pickle
import pickletools
import subprocess
import sys
import time
import warnings

import numpy as np
import pytest

from robotmq import deserialize, safe_deserialize, safe_serialize, serialize
from robotmq import UnsafePayloadError
from robotmq._pickle_validation import validate_pickle

pytestmark = pytest.mark.filterwarnings("error:robotmq\\.(de)?serialize is deprecated:DeprecationWarning")


def _legacy_serialize(obj):
    """Call the deprecated legacy writer without its DeprecationWarning."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return serialize(obj)


def _legacy_deserialize(buf):
    """Call the deprecated legacy reader without its DeprecationWarning."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return deserialize(buf)


try:
    import torch
except ImportError:  # the safe pair must work without torch; only the tensor tests need it
    torch = None
needs_torch = pytest.mark.skipif(torch is None, reason="torch is not installed")

TENSOR_TAG = "__robotmq_torch_tensor__"

# Opcodes that resolve a global, call something or load a persistent id.
FORBIDDEN_OPCODES = {
    "GLOBAL", "STACK_GLOBAL", "REDUCE", "BUILD", "INST", "OBJ", "NEWOBJ", "NEWOBJ_EX",
    "EXT1", "EXT2", "EXT4", "BINPERSID", "PERSID",
}


def _equal(x, y):
    """Structural equality that handles arrays, nested containers and nan."""
    if isinstance(x, np.ndarray):
        return isinstance(y, np.ndarray) and x.dtype == y.dtype and np.array_equal(x, y, equal_nan=x.dtype.kind == "f")
    if isinstance(x, dict):
        return isinstance(y, dict) and x.keys() == y.keys() and all(_equal(x[k], y[k]) for k in x)
    if isinstance(x, (list, tuple)):
        return type(x) is type(y) and len(x) == len(y) and all(_equal(p, q) for p, q in zip(x, y))
    if isinstance(x, float) and x != x:
        return isinstance(y, float) and y != y
    return type(x) is type(y) and x == y


def _observation():
    rng = np.random.default_rng(0)
    return {
        "instruction": "put the marker in the cup",
        "exterior1_rgb": rng.integers(0, 255, (2, 256, 448, 3), dtype=np.uint8),
        "wrist_rgb": rng.integers(0, 255, (2, 256, 448, 3), dtype=np.uint8),
        "right_main_camera_trajectory_xyz_wxyz": rng.standard_normal((2, 7)).astype(np.float32),
        "right_gripper_width_m": rng.standard_normal((2, 1)).astype(np.float32),
        "_sent_wall": 1760000000.123,
    }


_OBS = _observation()
PAYLOADS = {
    "observation": _OBS,
    "warm_up": {
        "uva_mode": "policy", "ar_chunk_num": 1, "batch_size": 2, "observation": _OBS,
        "all_instructions": ["a", "b"], "num_passes": 1, "offload_gen": True, "nominal_gap_steps": None,
    },
    "batch": [_OBS, _OBS],
    "reply": {
        "right_main_camera_trajectory_xyz_wxyz": np.zeros((32, 7), np.float32),
        "wrist_pred_rgb": np.zeros((8, 256, 448, 3), np.uint8),
    },
    "batch_reply": {
        "results": [{"a": np.ones(3, np.float32)}],
        "timing": {"queue_wait_ms": 0.1, "n": 2, "x": None, "nan": float("nan"), "inf": float("inf")},
    },
    "summary": {
        "observation_signature": [("exterior1_rgb", (256, 448)), ("n", 2)], "gpu_memory_gib": 11.5,
        "ok": True, "big": 2**70, "neg": -5, "bytes": b"\x00\x01", "empty": {}, "emptyl": [], "u": "héllo 🤖",
    },
    "config": {"model": {"lr": 1e-4, "path": "s3://x/y", "list": [1, 2.0, "3", None, False]}},
    "bare_true": True,
    "bare_none": None,
    "jpeg_bytes": {"cameras/wrist": b"\xff\xd8\xff" + bytes(100)},
    "mixed_dtypes": {k: np.zeros(3, k) for k in ["u1", "i1", "u2", "i2", "i4", "u4", "i8", "u8", "f2", "f4", "f8", "?"]},
    "zero_d": {"v": np.array(3.0)},
    "shape0": {"v": np.zeros((0, 7), np.float32)},
    # Bare (top-level) values, as a plain `put_data(topic, serialize(arr))` sends them.
    "bare_array": np.random.default_rng(1).standard_normal((4, 5, 3)),
    "bare_list_of_arrays": [np.array([1, 2]), np.array([3, 4, 5])],
    "bare_tuple_of_arrays": (np.array([1, 2]), np.array([3, 4])),
    "bare_int": 42,
    "bare_float": 3.14,
    "bare_str": "hello",
    "bare_bytes": b"raw bytes",
    "bare_empty_list": [],
    "bare_empty_dict": {},
}


class TestWireCompatibility:
    @pytest.mark.parametrize("name", list(PAYLOADS))
    def test_same_bytes_as_legacy(self, name):
        payload = PAYLOADS[name]
        assert safe_serialize(payload) == _legacy_serialize(payload)

    @pytest.mark.parametrize("name", list(PAYLOADS))
    def test_all_four_pairings_decode_equal(self, name):
        payload = PAYLOADS[name]
        legacy, safe = _legacy_serialize(payload), safe_serialize(payload)
        assert _equal(payload, safe_deserialize(safe))  # safe -> safe
        assert _equal(payload, safe_deserialize(legacy))  # legacy client -> safe server
        assert _equal(payload, _legacy_deserialize(safe))  # safe server -> legacy client
        assert _equal(_legacy_deserialize(legacy), safe_deserialize(legacy))

    @pytest.mark.parametrize("name", list(PAYLOADS))
    def test_opcode_audit_finds_no_globals_or_calls(self, name):
        found = {op.name for op, _, _ in pickletools.genops(safe_serialize(PAYLOADS[name]))}
        assert not (found & FORBIDDEN_OPCODES)

    def test_deserialized_array_is_writable(self):
        out = safe_deserialize(safe_serialize(np.arange(3.0)))
        out[0] = 99.0
        assert out[0] == 99.0

    def test_empty_bytes_returns_none_with_warning(self):
        with pytest.warns(UserWarning, match="empty data"):
            assert safe_deserialize(b"") is None


class _Attack:
    """A pickle of this object calls builtins.print when loaded."""

    def __reduce__(self):
        return (print, ("PWNED by pickle",))


class TestRefusals:
    def test_attack_payload_runs_in_legacy_and_is_refused_by_safe(self, capsys):
        attack = pickle.dumps({"obs": _Attack()})
        _legacy_deserialize(attack)  # legacy pair: the payload's code runs
        assert "PWNED by pickle" in capsys.readouterr().out
        with pytest.raises(pickle.UnpicklingError, match="builtins.print"):
            safe_deserialize(attack)
        assert capsys.readouterr().out == ""

    def test_persistent_id_is_refused(self):
        class _PersistentPickler(pickle.Pickler):
            def persistent_id(self, obj):
                return "pid" if isinstance(obj, str) else None

        import io

        buffer = io.BytesIO()
        _PersistentPickler(buffer).dump({"k": "v"})
        with pytest.raises(pickle.UnpicklingError, match="persistent"):
            safe_deserialize(buffer.getvalue())

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param({"v": np.float32(1.5)}, id="np.float32 scalar"),
            pytest.param({"seed": np.int64(3)}, id="np.int64 scalar"),
            pytest.param({"v": pathlib.Path("/x")}, id="Path"),
            pytest.param({"v": _Attack()}, id="custom object"),
        ],
    )
    def test_legacy_pickled_global_is_refused_on_receive(self, value):
        legacy = _legacy_serialize(value)
        with pytest.raises(pickle.UnpicklingError):
            safe_deserialize(legacy)

    @pytest.mark.parametrize("value", [pytest.param({1, 2}, id="set"), pytest.param(frozenset({1}), id="frozenset")])
    def test_legacy_pickled_set_is_read_on_receive(self, value):
        # A set pickles with EMPTY_SET / FROZENSET opcodes and no global, so the
        # restricted reader accepts one from a legacy client; the safe writer
        # still refuses it (explicit allow-list).
        assert safe_deserialize(_legacy_serialize({"v": value})) == {"v": value}

    def test_legacy_object_array_arrives_as_the_same_garbage_tuple(self):
        # The legacy writer sends an object array as its pointer bytes; neither
        # reader can rebuild it and both return the (bytes, "|O", shape) tuple.
        legacy = _legacy_serialize({"v": np.array([1, "a"], dtype=object)})
        out = safe_deserialize(legacy)
        assert out == _legacy_deserialize(legacy)
        assert isinstance(out["v"], tuple) and out["v"][1] == "|O"

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param({"v": {1, 2}}, id="set"),
            pytest.param({"v": frozenset({1})}, id="frozenset"),
            pytest.param({"v": pathlib.Path("/x")}, id="Path"),
            pytest.param({"v": np.array([1, "a"], dtype=object)}, id="object array"),
            pytest.param({"v": np.array(["a"])}, id="str array"),
            pytest.param({"v": np.zeros(2, np.complex64)}, id="complex array"),
            pytest.param({"v": np.array(["2020-01-01"], dtype="datetime64[D]")}, id="datetime array"),
            pytest.param({TENSOR_TAG: 1}, id="reserved tensor key"),
            pytest.param({"v": _Attack()}, id="custom object"),
            pytest.param({_Attack(): 1}, id="custom object as dict key"),
        ],
    )
    def test_non_plain_value_is_refused_on_send(self, value):
        with pytest.raises(TypeError):
            safe_serialize(value)

    def test_send_error_names_the_path(self):
        with pytest.raises(TypeError, match=r"payload\['a'\]\[1\]"):
            safe_serialize({"a": [1, {2}]})

    def test_numpy_scalars_are_converted_on_send(self):
        out = safe_deserialize(safe_serialize({"v": np.float32(1.5), "n": np.int64(3), "b": np.bool_(True)}))
        assert out == {"v": 1.5, "n": 3, "b": True}
        assert type(out["v"]) is float and type(out["n"]) is int and type(out["b"]) is bool

    def test_numpy_scalar_dict_key_is_converted_on_send(self):
        assert safe_deserialize(safe_serialize({np.int64(3): "x"})) == {3: "x"}


class TestLegacyDeprecation:
    def test_serialize_warns(self):
        with pytest.deprecated_call(match="robotmq.serialize is deprecated"):
            serialize(1)

    def test_deserialize_warns(self):
        buf = _legacy_serialize({"a": 1})
        with pytest.deprecated_call(match="robotmq.deserialize is deprecated"):
            deserialize(buf)

    def test_legacy_round_trip_still_works(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            assert deserialize(serialize({"a": [1, 2.5, "x"]})) == {"a": [1, 2.5, "x"]}

    def test_safe_pair_emits_no_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = safe_deserialize(safe_serialize({"a": np.arange(3), "b": "x"}))
        assert caught == []
        assert _equal(out, {"a": np.arange(3), "b": "x"})


@needs_torch
class TestTorchTensors:
    @staticmethod
    def _cases():
        g = torch.Generator().manual_seed(0)
        cases = {
            "bf16_kv": torch.randn(4, 2, 7, 8, 16, generator=g).to(torch.bfloat16),
            "f16": torch.randn(3, 4, generator=g).to(torch.float16),
            "f32": torch.randn(5, generator=g),
            "f64": torch.randn(2, 2, generator=g).to(torch.float64),
            "i64": torch.arange(10),
            "i32": torch.arange(4, dtype=torch.int32),
            "i16": torch.tensor([-3, 7], dtype=torch.int16),
            "i8": torch.tensor([-1, 2], dtype=torch.int8),
            "u8": torch.tensor([255], dtype=torch.uint8),
            "bool": torch.tensor([True, False]),
            "zero_d": torch.tensor(2.5),
            "empty": torch.empty(0, 7),
            "non_contiguous": torch.randn(4, 6, generator=g).t(),
            "requires_grad": torch.randn(3, generator=g).requires_grad_(True),
            "nan_inf": torch.tensor([float("nan"), float("inf"), -float("inf"), -0.0]),
            "parameter": torch.nn.Parameter(torch.randn(2, generator=g)),
        }
        if torch.cuda.is_available():
            cases["cuda_bf16"] = torch.randn(3, 3, generator=g).to(torch.bfloat16).cuda()
        return cases

    @pytest.mark.parametrize("name", [
        "bf16_kv", "f16", "f32", "f64", "i64", "i32", "i16", "i8", "u8", "bool", "zero_d", "empty",
        "non_contiguous", "requires_grad", "nan_inf", "parameter", "cuda_bf16",
    ])
    def test_round_trip_is_bit_exact(self, name):
        cases = self._cases()
        if name not in cases:
            pytest.skip("CUDA not available")
        t = cases[name]
        out = safe_deserialize(safe_serialize({"kv": {"c": t}, "n": 3}))["kv"]["c"]
        expected = t.detach().cpu()
        assert type(out) is torch.Tensor
        assert out.dtype == t.dtype and out.shape == t.shape and out.device.type == "cpu"
        assert not out.requires_grad
        # Compare the raw bytes so nan payloads and -0.0 are checked bit-exactly.
        assert torch.equal(out.reshape(-1).view(torch.uint8), expected.contiguous().reshape(-1).view(torch.uint8))

    def test_tensor_is_safe_to_safe_only(self):
        t = torch.zeros(2, dtype=torch.bfloat16)
        safe = safe_serialize({"kv": {"c": t}})
        legacy_view = _legacy_deserialize(safe)["kv"]["c"]  # legacy reader gets the tagged dict
        assert isinstance(legacy_view, dict) and legacy_view[TENSOR_TAG] == 1
        with pytest.raises(pickle.UnpicklingError):  # legacy writer's pickled tensor is refused
            safe_deserialize(_legacy_serialize({"kv": {"c": t}}))

    def test_tensor_wire_has_no_globals(self):
        found = {op.name for op, _, _ in pickletools.genops(safe_serialize(torch.randn(3)))}
        assert not (found & FORBIDDEN_OPCODES)

    @pytest.mark.parametrize(
        "forged",
        [
            pytest.param({TENSOR_TAG: 1, "dtype": "bfloat16", "shape": (2, 2), "data": b"\x00" * 7}, id="byte count"),
            pytest.param({TENSOR_TAG: 1, "dtype": "cuda", "shape": (1,), "data": b"\x00"}, id="dtype is a module"),
            pytest.param({TENSOR_TAG: 1, "dtype": "float32", "shape": (-1,), "data": b"\x00" * 4}, id="negative dim"),
            pytest.param({TENSOR_TAG: 1, "dtype": "float32", "shape": ("1",), "data": b"\x00" * 4}, id="str dim"),
            pytest.param({TENSOR_TAG: 1, "dtype": "float32", "shape": (1,), "data": "abcd"}, id="str data"),
            pytest.param({TENSOR_TAG: 1, "dtype": 7, "shape": (1,), "data": b"\x00" * 4}, id="int dtype"),
        ],
    )
    def test_forged_tag_is_refused(self, forged):
        with pytest.raises(ValueError):
            safe_deserialize(pickle.dumps(forged))

    def test_tag_with_extra_keys_stays_a_dict(self):
        payload = {TENSOR_TAG: 1, "dtype": "float32", "shape": (1,), "data": b"\x00" * 4, "extra": 0}
        assert safe_deserialize(pickle.dumps(payload)) == payload

    def test_reserved_key_is_refused_on_send(self):
        with pytest.raises(TypeError, match="reserved key"):
            safe_serialize({TENSOR_TAG: 1, "dtype": "float32", "shape": (1,), "data": b"\x00" * 4})


# ---------------------------------------------------------------------------
# Contract tests for the hardened safe pair
# ---------------------------------------------------------------------------

_PYTHON = sys.executable
_REPO_ROOT = str(pathlib.Path(__file__).resolve().parents[1])


def _matrix(rows):
    """np.matrix without numpy's PendingDeprecationWarning at collection time."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PendingDeprecationWarning)
        return np.matrix(rows)


class _Color(enum.IntEnum):
    RED = 1


class _Str(str):
    pass


class _Int(int):
    pass


class _Float(float):
    pass


class _Bytes(bytes):
    pass


_Point = collections.namedtuple("_Point", "x y")


def _c_order():
    return np.arange(12.0).reshape(3, 4)


def _accepted_cases():
    """Every value category the safe writer accepts, with the value the reader must return."""
    a = _c_order()
    return [
        pytest.param("s", "s", id="str"),
        pytest.param(b"b", b"b", id="bytes"),
        pytest.param(7, 7, id="int"),
        pytest.param(2**70, 2**70, id="big int"),
        pytest.param(0.5, 0.5, id="float"),
        pytest.param(float("nan"), float("nan"), id="nan"),
        pytest.param(True, True, id="bool"),
        pytest.param(None, None, id="None"),
        pytest.param({"a": [1, (2, "x")], 3: None}, {"a": [1, (2, "x")], 3: None}, id="nested containers"),
        pytest.param(collections.OrderedDict([("b", 1), ("a", 2)]), {"b": 1, "a": 2}, id="OrderedDict"),
        pytest.param(collections.defaultdict(list, {"a": [1]}), {"a": [1]}, id="defaultdict"),
        pytest.param(_Point(1, 2), (1, 2), id="namedtuple"),
        pytest.param(np.float32(0.5), 0.5, id="np.float32"),
        pytest.param(np.int64(7), 7, id="np.int64"),
        pytest.param(np.bool_(True), True, id="np.bool_"),
        pytest.param(np.uint8(3), 3, id="np.uint8"),
        pytest.param(a, a, id="C-order"),
        pytest.param(np.asfortranarray(a), a, id="F-order"),
        pytest.param(a[::-1], a[::-1].copy(), id="reversed"),
        pytest.param(a[:, ::2], a[:, ::2].copy(), id="strided"),
        pytest.param(a.T, a.T.copy(), id="transposed"),
        pytest.param(np.broadcast_to(np.arange(3.0), (4, 3)), np.tile(np.arange(3.0), (4, 1)), id="stride-0"),
        pytest.param(a.astype(">f8"), a.astype(">f8"), id="big-endian f8"),
        pytest.param(np.arange(4, dtype=">i2"), np.arange(4, dtype=">i2"), id="big-endian i2"),
        pytest.param(np.zeros(3, np.uint64), np.zeros(3, np.uint64), id="uint64"),
        pytest.param(np.zeros(3, np.float16), np.zeros(3, np.float16), id="float16"),
        pytest.param(np.zeros(3, bool), np.zeros(3, bool), id="bool array"),
        pytest.param(_matrix([[1, 2], [3, 4]]), np.array([[1, 2], [3, 4]]), id="np.matrix"),
    ]


def _refused_cases():
    """Values the safe writer must refuse with TypeError."""
    return [
        pytest.param(bytearray(b"x"), id="bytearray"),
        pytest.param(_Color.RED, id="IntEnum"),
        pytest.param(_Str("x"), id="str subclass"),
        pytest.param(_Int(1), id="int subclass"),
        pytest.param(_Float(1.0), id="float subclass"),
        pytest.param(_Bytes(b"x"), id="bytes subclass"),
        pytest.param({1}, id="set"),
        pytest.param(frozenset({1}), id="frozenset"),
        pytest.param(pathlib.Path("/x"), id="Path"),
        pytest.param(_Attack(), id="custom object"),
        pytest.param(np.longdouble(1.0), id="np.longdouble scalar"),
        pytest.param(np.complex64(1.0), id="np.complex64 scalar"),
        pytest.param(np.datetime64("2020-01-01"), id="np.datetime64 scalar"),
        pytest.param(np.timedelta64(1, "D"), id="np.timedelta64 scalar"),
        pytest.param(np.array([1, "a"], dtype=object), id="object array"),
        pytest.param(np.array(["a"]), id="str array"),
        pytest.param(np.zeros(2, "|V4"), id="void array"),
        pytest.param(np.zeros(2, dtype="f8,f8"), id="structured array"),
        pytest.param(np.zeros(2, np.complex64), id="complex array"),
        pytest.param(np.array(["2020-01-01"], dtype="datetime64[D]"), id="datetime array"),
        pytest.param(np.zeros(2, "m8[s]"), id="timedelta array"),
        pytest.param(np.zeros(2, np.longdouble), id="longdouble array"),
        pytest.param({TENSOR_TAG: 1}, id="reserved tensor key"),
    ]


class TestWriterContract:
    @pytest.mark.parametrize("value, expected", _accepted_cases())
    def test_accepted_value_round_trips(self, value, expected):
        out = safe_deserialize(safe_serialize(value))
        assert _equal(expected, out)
        if isinstance(expected, np.ndarray):
            assert type(out) is np.ndarray and out.dtype.str == expected.dtype.str

    @pytest.mark.parametrize("value, expected", _accepted_cases())
    def test_accepted_value_round_trips_nested(self, value, expected):
        out = safe_deserialize(safe_serialize({"v": [value], ("k",): (value,)}))
        assert _equal({"v": [expected], ("k",): (expected,)}, out)

    def test_masked_array_is_flattened_to_ndarray(self):
        m = np.ma.masked_array([1.0, 2.0, 3.0], mask=[0, 1, 0])
        out = safe_deserialize(safe_serialize(m))
        assert type(out) is np.ndarray and out.dtype == m.dtype and out.shape == (3,)
        assert out[0] == 1.0 and out[2] == 3.0

    @pytest.mark.parametrize("value", _refused_cases())
    def test_refused_value_raises_type_error_bare(self, value):
        with pytest.raises(TypeError):
            safe_serialize(value)

    @pytest.mark.parametrize("value", _refused_cases())
    def test_refused_value_raises_type_error_nested(self, value):
        with pytest.raises(TypeError):
            safe_serialize({"a": [1, value]})

    @pytest.mark.parametrize(
        "key",
        [pytest.param(_Color.RED, id="IntEnum key"), pytest.param(_Str("k"), id="str subclass key"),
         pytest.param(frozenset({1}), id="frozenset key")],
    )
    def test_refused_dict_key_raises_type_error(self, key):
        with pytest.raises(TypeError):
            safe_serialize({key: 1})

    @pytest.mark.parametrize(
        "value, pattern",
        [
            pytest.param({"a": [1, bytearray(b"x")]}, r"payload\['a'\]\[1\]", id="bytearray in list"),
            pytest.param({"a": (0, {"b": _Color.RED})}, r"payload\['a'\]\[1\]\['b'\]", id="IntEnum in tuple"),
            pytest.param([np.zeros(2, np.complex64)], r"payload\[0\]", id="complex array in list"),
        ],
    )
    def test_send_error_names_the_full_path(self, value, pattern):
        with pytest.raises(TypeError, match=pattern):
            safe_serialize(value)

    def test_shared_tuple_key_matches_legacy_bytes(self):
        k = ("a", 1)
        payload = [{k: 1}, {k: 2}]
        assert safe_serialize(payload) == _legacy_serialize(payload)
        assert safe_deserialize(safe_serialize(payload)) == payload

    def test_shared_array_object_round_trips(self):
        arr = np.arange(3.0)
        out = safe_deserialize(safe_serialize([arr, arr, {"a": arr}]))
        assert _equal([arr, arr, {"a": arr}], out)

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(collections.OrderedDict([("a", 1)]), id="OrderedDict"),
            pytest.param(_Point(1, 2), id="namedtuple"),
            pytest.param(np.float32(0.5), id="np.float32"),
            pytest.param(np.asfortranarray(_c_order()), id="F-order array"),
            pytest.param(np.arange(4, dtype=">i2"), id="big-endian array"),
        ],
    )
    def test_accepted_wire_has_no_globals(self, value):
        found = {op.name for op, _, _ in pickletools.genops(safe_serialize({"v": value}))}
        assert not (found & FORBIDDEN_OPCODES)


def _p4(*ops):
    return pickle.PROTO + b"\x04" + b"".join(ops) + pickle.STOP


def _hostile_array_triple(buf, original):
    """A hostile array triple either raises UnsafePayloadError or comes back as the tuple."""
    try:
        out = safe_deserialize(buf)
    except UnsafePayloadError:
        return
    assert isinstance(out, tuple) and out == original


class TestReaderHostileInput:
    def test_error_class_is_unpickling_error_and_value_error(self):
        assert issubclass(UnsafePayloadError, pickle.UnpicklingError)
        assert issubclass(UnsafePayloadError, ValueError)
        with pytest.raises(UnsafePayloadError) as excinfo:
            safe_deserialize(pickle.dumps(_Attack()))
        exc = excinfo.value
        assert isinstance(exc, pickle.UnpicklingError) and isinstance(exc, ValueError)

    @pytest.mark.parametrize("protocol", [pytest.param(2, id="GLOBAL"), pytest.param(4, id="STACK_GLOBAL")])
    def test_global_is_refused_and_named(self, protocol, capsys):
        attack = pickle.dumps({"obs": _Attack()}, protocol=protocol)
        # Protocols < 3 spell the module `__builtin__`.
        with pytest.raises(UnsafePayloadError, match=r"(__builtin__|builtins)\.print"):
            safe_deserialize(attack)
        assert capsys.readouterr().out == ""

    @pytest.mark.parametrize("protocol", [pytest.param(0, id="PERSID"), pytest.param(4, id="BINPERSID")])
    def test_persistent_id_is_refused(self, protocol):
        import io

        class _PersistentPickler(pickle.Pickler):
            def persistent_id(self, obj):
                return "pid" if isinstance(obj, str) else None

        buffer = io.BytesIO()
        _PersistentPickler(buffer, protocol=protocol).dump({"k": "v"})
        with pytest.raises(UnsafePayloadError):
            safe_deserialize(buffer.getvalue())

    @pytest.mark.parametrize(
        "stream",
        [
            pytest.param(_p4(pickle.EMPTY_LIST, pickle.EMPTY_TUPLE, pickle.REDUCE), id="REDUCE"),
            pytest.param(_p4(pickle.EMPTY_DICT, pickle.EMPTY_DICT, pickle.BUILD), id="BUILD"),
            pytest.param(_p4(pickle.EMPTY_LIST, pickle.EMPTY_TUPLE, pickle.NEWOBJ), id="NEWOBJ"),
            pytest.param(_p4(pickle.EMPTY_LIST, pickle.EMPTY_TUPLE, pickle.EMPTY_DICT, pickle.NEWOBJ_EX), id="NEWOBJ_EX"),
            pytest.param(_p4(pickle.MARK, pickle.EMPTY_LIST, pickle.OBJ), id="OBJ"),
            pytest.param(_p4(pickle.MARK, pickle.INST + b"builtins\nlist\n"), id="INST"),
            pytest.param(_p4(pickle.GLOBAL + b"builtins\nprint\n"), id="GLOBAL bare"),
            pytest.param(_p4(pickle.SHORT_BINUNICODE + b"\x08builtins", pickle.SHORT_BINUNICODE + b"\x05print",
                             pickle.STACK_GLOBAL), id="STACK_GLOBAL bare"),
            pytest.param(pickle.PROTO + b"\x05" + pickle.NEXT_BUFFER + pickle.READONLY_BUFFER + pickle.STOP,
                         id="NEXT_BUFFER"),
            pytest.param(_p4(pickle.SHORT_BINUNICODE + b"\x03pid", pickle.BINPERSID), id="BINPERSID bare"),
        ],
    )
    def test_handcrafted_opcode_is_refused(self, stream, capsys):
        with pytest.raises(UnsafePayloadError):
            safe_deserialize(stream)
        assert capsys.readouterr().out == ""

    def test_trailing_bytes_are_refused(self):
        with pytest.raises(UnsafePayloadError):
            safe_deserialize(pickle.dumps(1) + b"junk")

    def test_truncated_stream_is_refused(self):
        with pytest.raises(UnsafePayloadError):
            safe_deserialize(pickle.dumps({"a": [1, 2, 3]})[:-3])

    @pytest.mark.parametrize("stream", [pytest.param(b"\x00", id="bad opcode"), pytest.param(b"junk", id="garbage")])
    def test_garbage_is_refused(self, stream):
        with pytest.raises(UnsafePayloadError):
            safe_deserialize(stream)

    def test_ext1_with_registered_and_warm_extension_is_refused(self, capsys):
        stream = _p4(pickle.EXT1 + bytes([240]))
        copyreg.add_extension("builtins", "print", 240)
        try:
            pickle.loads(pickle.dumps(print))  # warms copyreg._extension_cache[240]
            assert 240 in copyreg._extension_cache
            with pytest.raises(UnsafePayloadError):
                safe_deserialize(stream)
        finally:
            copyreg.remove_extension("builtins", "print", 240)
        assert capsys.readouterr().out == ""

    @pytest.mark.parametrize(
        "stream",
        [
            pytest.param(_p4(pickle.EXT1 + bytes([240])), id="EXT1"),
            pytest.param(_p4(pickle.EXT2 + (240).to_bytes(2, "little")), id="EXT2"),
            pytest.param(_p4(pickle.EXT4 + (240).to_bytes(4, "little")), id="EXT4"),
        ],
    )
    def test_ext_with_empty_registry_is_refused(self, stream):
        assert 240 not in copyreg._inverted_registry
        with pytest.raises(UnsafePayloadError):
            safe_deserialize(stream)

    def test_shared_reference_bomb_is_refused_quickly(self):
        bomb = [1]
        for _ in range(40):
            bomb = [bomb, bomb]
        stream = pickle.dumps(bomb)
        start = time.perf_counter()
        with pytest.raises(UnsafePayloadError):
            safe_deserialize(stream)
        assert time.perf_counter() - start < 0.1

    @pytest.mark.parametrize("container", [list, tuple, dict])
    def test_shared_leaf_container_exceeds_entry_budget(self, container):
        shared = dict.fromkeys(range(256)) if container is dict else container([None] * 256)
        stream = pickle.dumps([shared] * 256)
        with pytest.raises(UnsafePayloadError, match="expands beyond"):
            safe_deserialize(stream)

    def test_empty_containers_fit_entry_budget(self):
        payload = [[], {}, ()] * 256
        assert safe_deserialize(safe_serialize(payload)) == payload

    @pytest.mark.parametrize("dtype, shape", [("not a dtype", (4096,)), ("|u1", (4097,))])
    def test_shared_bytes_in_non_array_triples_round_trip(self, dtype, shape):
        triple = (bytes(4096), dtype, shape)
        payload = [triple] * 4
        assert safe_deserialize(safe_serialize(payload)) == payload

    def test_memo_shared_array_bomb_is_refused_quickly(self):
        triple = (bytes(1 << 20), "|u1", (1 << 20,))
        stream = pickle.dumps([triple] * 1000)  # the tuple is memoized: ~1 MB on the wire, 1 GB if rebuilt
        assert len(stream) < 2 << 20
        start = time.perf_counter()
        with pytest.raises(UnsafePayloadError):
            safe_deserialize(stream)
        assert time.perf_counter() - start < 0.2

    def test_self_referential_list_is_refused(self):
        loop = []
        loop.append(loop)
        with pytest.raises(UnsafePayloadError):
            safe_deserialize(pickle.dumps(loop))

    def test_self_referential_dict_is_refused(self):
        loop = {}
        loop["self"] = loop
        with pytest.raises(UnsafePayloadError):
            safe_deserialize(pickle.dumps({"a": [loop]}))

    def test_deep_nesting_is_refused_not_recursion_error(self):
        depth = 200_000  # [[[...1...]]] built from raw opcodes; pickle.dumps itself cannot nest this deep
        stream = _p4(pickle.EMPTY_LIST * depth, pickle.BININT1 + b"\x01", pickle.APPEND * depth)
        with pytest.raises(UnsafePayloadError):
            safe_deserialize(stream)

    @pytest.mark.parametrize(
        "dtype",
        [pytest.param("O", id="O"), pytest.param("|O", id="|O"), pytest.param("O,i4", id="O,i4"),
         pytest.param("(2,)O", id="(2,)O"), pytest.param("T", id="T (StringDType)"),
         pytest.param("not a dtype", id="garbage dtype"), pytest.param("", id="empty dtype")],
    )
    def test_hostile_dtype_triple_does_not_crash(self, dtype):
        triple = (b"\x00" * 16, dtype, (2,))
        _hostile_array_triple(pickle.dumps(triple), triple)

    def test_huge_dtype_string_is_handled_quickly(self):
        triple = (b"\x00" * 8, "x" * (10 << 20), (1,))
        stream = pickle.dumps(triple)
        start = time.perf_counter()
        _hostile_array_triple(stream, triple)
        assert time.perf_counter() - start < 0.1

    @pytest.mark.parametrize(
        "shape",
        [pytest.param((1 << 40, 1 << 40), id="1<<40 square"), pytest.param((1 << 63,), id="1<<63"),
         pytest.param((2, 3), id="byte count mismatch"),
         pytest.param(("1",), id="str dim"), pytest.param((1.0,), id="float dim")],
    )
    def test_hostile_shape_triple_does_not_crash(self, shape):
        triple = (b"\x00" * 8, "<f8", shape)
        _hostile_array_triple(pickle.dumps(triple), triple)

    @pytest.mark.parametrize("dim", [-1, -2])
    def test_negative_dim_reshapes_like_legacy(self, dim):
        # numpy treats a negative dim as "infer"; the legacy reader does the same,
        # so this is parity, not a hazard: the byte count still bounds the array.
        buf = pickle.dumps((b"\x00" * 8, "<f8", (dim,)))
        out = safe_deserialize(buf)
        assert _equal(_legacy_deserialize(buf), out)
        assert isinstance(out, np.ndarray) and out.shape == (1,) and out.dtype == np.float64


class TestReaderLegacyLeniency:
    @pytest.mark.parametrize(
        "arr",
        [
            pytest.param(np.array([1 + 2j, 3 - 1j], dtype="<c16"), id="<c16"),
            pytest.param(np.array(["2020-01-01", "2021-06-30"], dtype="<M8[D]"), id="<M8[D]"),
            pytest.param(np.array(["abc", "de"], dtype="<U3"), id="<U3"),
            pytest.param(np.frombuffer(bytes(range(12)), dtype="|V4"), id="|V4"),
        ],
    )
    def test_legacy_wide_dtype_triple_is_returned_as_array(self, arr):
        triple = (arr.tobytes(), arr.dtype.str, arr.shape)
        out = safe_deserialize(pickle.dumps({"v": triple}))["v"]
        assert isinstance(out, np.ndarray) and out.dtype == arr.dtype and out.shape == arr.shape
        assert np.array_equal(out, arr)

    def test_legacy_structured_triple_does_not_raise(self):
        arr = np.zeros(2, dtype="f8,f8")
        triple = (arr.tobytes(), arr.dtype.str, arr.shape)  # dtype.str is "|V16": the field names are lost
        assert triple[1] == "|V16"
        out = safe_deserialize(pickle.dumps(triple))
        assert isinstance(out, (np.ndarray, tuple))

    @pytest.mark.parametrize("value", [pytest.param({1, 2}, id="set"), pytest.param(frozenset({1}), id="frozenset")])
    def test_legacy_set_is_read(self, value):
        assert safe_deserialize(pickle.dumps({"v": value})) == {"v": value}

    def test_legacy_bytearray_is_read(self):
        out = safe_deserialize(pickle.dumps({"v": bytearray(b"x")}, protocol=5))["v"]
        assert type(out) is bytearray and out == bytearray(b"x")

    def test_legacy_picklebuffer_is_read_as_bytes(self):
        out = safe_deserialize(pickle.dumps(pickle.PickleBuffer(b"abc"), protocol=5))
        assert bytes(out) == b"abc"

    @pytest.mark.parametrize("protocol", [3, 4, 5])
    def test_every_bytes_capable_protocol_is_read(self, protocol):
        payload = {"a": [1, 2.5, "x", b"y", None, True], "t": (1, 2), "arr": (np.arange(3.0).tobytes(), "<f8", (3,))}
        out = safe_deserialize(pickle.dumps(payload, protocol=protocol))
        assert _equal({**payload, "arr": np.arange(3.0)}, out)

    @pytest.mark.parametrize("protocol", [0, 1, 2])
    def test_old_protocols_read_without_bytes(self, protocol):
        payload = {"a": [1, 2.5, "x", None, True], "t": (1, 2)}
        assert safe_deserialize(pickle.dumps(payload, protocol=protocol)) == payload

    @pytest.mark.parametrize("protocol", [0, 1, 2])
    def test_old_protocols_refuse_bytes(self, protocol):
        # Protocols < 3 encode bytes through the `_codecs.encode` global, which the
        # reader refuses. robotmq always pickles with the default protocol (>= 4).
        with pytest.raises(UnsafePayloadError, match="_codecs.encode"):
            safe_deserialize(pickle.dumps({"b": b"y"}, protocol=protocol))

    def test_legacy_plain_payload_decodes_equal(self):
        payload = {"obs": PAYLOADS["observation"], "cfg": PAYLOADS["config"]}
        assert _equal(payload, safe_deserialize(_legacy_serialize(payload)))


class TestPerformanceGuard:
    @staticmethod
    def _best_of(fn, arg, runs=5):
        return min(_timed(fn, arg) for _ in range(runs))

    def test_serialize_is_not_much_slower_than_legacy(self):
        d = {f"k{i}": (i * 0.5 if i % 2 else i) for i in range(10000)}
        safe_t = self._best_of(safe_serialize, d)
        legacy_t = self._best_of(_legacy_serialize, d)
        assert safe_t <= 1.5 * legacy_t + 1e-3, (safe_t, legacy_t)

    def test_deserialize_overhead_beyond_validation_is_bounded(self):
        d = {f"k{i}": (i * 0.5 if i % 2 else i) for i in range(10000)}
        buf = safe_serialize(d)
        safe_t = self._best_of(safe_deserialize, buf)
        legacy_t = self._best_of(_legacy_deserialize, buf)
        validation_t = self._best_of(validate_pickle, buf)
        # Full validation is intentional; guard against accidental extra passes
        # while retaining the original allowance for rebuilding plain payloads.
        assert safe_t <= 1.5 * validation_t + 2.0 * legacy_t + 1e-3, (safe_t, validation_t, legacy_t)

    def test_array_payload_serialize_is_not_much_slower_than_legacy(self):
        payload = PAYLOADS["observation"]
        safe_t = self._best_of(safe_serialize, payload)
        legacy_t = self._best_of(_legacy_serialize, payload)
        assert safe_t <= 1.5 * legacy_t + 1e-3, (safe_t, legacy_t)


def _timed(fn, arg):
    start = time.perf_counter()
    fn(arg)
    return time.perf_counter() - start


_DYNAMO_PROBE = """
import pickle, sys
from robotmq import safe_deserialize, UnsafePayloadError
forged = pickle.dumps({%r: 1, "dtype": "_dynamo", "shape": (1,), "data": b"\\x00" * 4})
try:
    safe_deserialize(forged)
    print("NO_ERROR", "torch._dynamo" in sys.modules)
except UnsafePayloadError:
    print("UnsafePayloadError", "torch._dynamo" in sys.modules)
""" % TENSOR_TAG


@needs_torch
class TestTorchTensorViews:
    @staticmethod
    def _view_cases():
        g = torch.Generator().manual_seed(1)
        cases = {
            "real_conj_noop": torch.tensor([1.0, 2.0]).conj(),
            "complex64_conj_view": torch.randn(3, dtype=torch.complex64, generator=g).conj(),
            "complex128_conj_view": torch.randn(2, 2, dtype=torch.complex128, generator=g).conj(),
            "complex64_plain": torch.randn(4, dtype=torch.complex64, generator=g),
        }
        if hasattr(torch, "_neg_view"):
            cases["neg_view"] = torch._neg_view(torch.randn(3, generator=g))
            cases["conj_neg_view"] = torch._neg_view(torch.randn(3, dtype=torch.complex64, generator=g).conj())
        return cases

    @pytest.mark.parametrize("name", [
        "real_conj_noop", "complex64_conj_view", "complex128_conj_view", "complex64_plain", "neg_view", "conj_neg_view",
    ])
    def test_view_round_trip_is_bit_exact(self, name):
        cases = self._view_cases()
        if name not in cases:
            pytest.skip("torch._neg_view is not available")
        t = cases[name]
        out = safe_deserialize(safe_serialize({"t": t}))["t"]
        expected = t.resolve_conj().resolve_neg().detach().cpu().contiguous()
        assert type(out) is torch.Tensor and out.dtype == t.dtype and out.shape == t.shape
        assert not out.is_conj() and not out.is_neg()
        assert torch.equal(out.reshape(-1).view(torch.uint8), expected.reshape(-1).view(torch.uint8))

    @pytest.mark.parametrize(
        "make",
        [
            pytest.param(lambda: torch.sparse_coo_tensor(torch.tensor([[0, 1]]), torch.tensor([1.0, 2.0]), (3,)),
                         id="sparse"),
            pytest.param(lambda: torch.quantize_per_tensor(torch.randn(3), 0.1, 0, torch.qint8), id="quantized"),
            pytest.param(
                lambda: torch.nested.nested_tensor([torch.ones(2), torch.ones(3)]),
                id="nested",
                marks=pytest.mark.filterwarnings("ignore:The PyTorch API of nested tensors:UserWarning"),
            ),
            pytest.param(lambda: torch.empty(3, device="meta"), id="meta"),
        ],
    )
    def test_unsupported_tensor_is_refused_on_send(self, make):
        with pytest.raises(TypeError, match=r"payload\['t'\]"):
            safe_serialize({"t": make()})

    def test_unsupported_tensor_error_names_the_path(self):
        with pytest.raises(TypeError, match=r"payload\['t'\]\[0\]"):
            safe_serialize({"t": [torch.empty(3, device="meta")]})


@needs_torch
class TestTorchForgedTags:
    @pytest.mark.parametrize(
        "forged",
        [
            pytest.param({TENSOR_TAG: 1, "dtype": "_dynamo", "shape": (1,), "data": b"\x00" * 4}, id="dtype _dynamo"),
            pytest.param({TENSOR_TAG: 1, "dtype": "cuda", "shape": (1,), "data": b"\x00"}, id="dtype cuda"),
            pytest.param({TENSOR_TAG: 1, "dtype": "Tensor", "shape": (1,), "data": b"\x00"}, id="dtype Tensor"),
            pytest.param({TENSOR_TAG: 1, "dtype": 7, "shape": (1,), "data": b"\x00" * 4}, id="int dtype"),
            pytest.param({TENSOR_TAG: 1, "dtype": "float32", "shape": (1,) * 65, "data": b"\x00" * 4}, id="65 dims"),
            pytest.param({TENSOR_TAG: 1, "dtype": "float32", "shape": (0, 1 << 62, 1 << 62), "data": b""},
                         id="zero numel with huge dims"),
            pytest.param({TENSOR_TAG: 1, "dtype": "uint8", "shape": (1 << 63,), "data": b"\x00"}, id="dim 1<<63"),
            pytest.param({TENSOR_TAG: 1, "dtype": "float32", "shape": (-1,), "data": b"\x00" * 4}, id="negative dim"),
            pytest.param({TENSOR_TAG: 1, "dtype": "float32", "shape": ("1",), "data": b"\x00" * 4}, id="str dim"),
            pytest.param({TENSOR_TAG: 1, "dtype": "float32", "shape": (True,), "data": b"\x00" * 4}, id="bool dim"),
            pytest.param({TENSOR_TAG: 1, "dtype": "float32", "shape": (2,), "data": b"\x00" * 7}, id="byte count"),
            pytest.param({TENSOR_TAG: 1, "dtype": "float32", "shape": (1,), "data": "abcd"}, id="str data"),
            pytest.param({TENSOR_TAG: 1, "dtype": "float32", "shape": 4, "data": b"\x00" * 4}, id="int shape"),
        ],
    )
    def test_forged_tag_raises_unsafe_payload_error(self, forged):
        with pytest.raises(UnsafePayloadError):
            safe_deserialize(pickle.dumps(forged))

    @pytest.mark.parametrize("field", ["dtype", "shape"])
    def test_invalid_field_error_does_not_expand_shared_containers(self, field):
        shared = [0]
        # Keep a regression harmless: the old error renders only tens of KiB here,
        # while increasing this depth would make error formatting exponential.
        for _ in range(12):
            shared = [shared, shared]
        forged = {TENSOR_TAG: 1, "dtype": "float32", "shape": (1,), "data": b"\x00" * 4}
        forged[field] = shared
        with pytest.raises(UnsafePayloadError, match=field) as exc:
            safe_deserialize(pickle.dumps(forged))
        assert len(str(exc.value)) < 256

    def test_empty_tensor_is_rebuilt_on_cpu_under_default_device_context(self):
        payload = safe_serialize(torch.empty(0, 7, dtype=torch.bfloat16, device="cpu"))
        with torch.device("meta"):
            out = safe_deserialize(payload)
        assert out.device.type == "cpu"
        assert out.shape == (0, 7) and out.dtype == torch.bfloat16

    def test_forged_dynamo_dtype_does_not_import_torch_dynamo(self):
        proc = subprocess.run(
            [_PYTHON, "-c", _DYNAMO_PROBE], cwd=_REPO_ROOT, capture_output=True, text=True, timeout=300,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.split() == ["UnsafePayloadError", "False"], proc.stdout + proc.stderr

    def test_tag_true_stays_a_dict(self):
        payload = {TENSOR_TAG: True, "dtype": "float32", "shape": (1,), "data": b"\x00" * 4}
        out = safe_deserialize(pickle.dumps(payload))
        assert isinstance(out, dict) and out[TENSOR_TAG] is True and out == payload

    @pytest.mark.parametrize("tag", [pytest.param(2, id="tag 2"), pytest.param("1", id="tag '1'"),
                                     pytest.param(1.0, id="tag 1.0")])
    def test_other_tag_values_stay_a_dict(self, tag):
        payload = {TENSOR_TAG: tag, "dtype": "float32", "shape": (1,), "data": b"\x00" * 4}
        out = safe_deserialize(pickle.dumps(payload))
        assert isinstance(out, dict) and type(out[TENSOR_TAG]) is type(tag) and out == payload

    def test_shape_as_list_is_rebuilt(self):
        payload = {TENSOR_TAG: 1, "dtype": "float32", "shape": [2, 1], "data": b"\x00" * 8}
        out = safe_deserialize(pickle.dumps(payload))
        assert type(out) is torch.Tensor and out.shape == (2, 1) and out.dtype == torch.float32

    def test_zero_numel_with_sane_shape_is_rebuilt(self):
        payload = {TENSOR_TAG: 1, "dtype": "bfloat16", "shape": (0, 7), "data": b""}
        out = safe_deserialize(pickle.dumps(payload))
        assert type(out) is torch.Tensor and out.shape == (0, 7) and out.dtype == torch.bfloat16
