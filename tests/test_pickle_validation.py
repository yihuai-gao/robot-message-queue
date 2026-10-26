"""Pre-unpickle safety and compatibility regressions.

Hostile allocation and hash payloads are tested with the native loader disabled:
even a regression in the validator must not allocate gigabytes or hang pytest.
"""

import copyreg
import pickle
import struct

import numpy as np
import pytest

import robotmq.utils as utils
from robotmq import UnsafePayloadError, safe_deserialize, safe_serialize


def _p4(body):
    return pickle.PROTO + b"\x04" + body + pickle.STOP


def _frame(body):
    return pickle.FRAME + struct.pack("<Q", len(body)) + body


@pytest.fixture
def forbid_native_loader(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("malformed or excessive payload reached the native unpickler")
    monkeypatch.setattr(utils, "_NoGlobals", forbidden)


@pytest.mark.parametrize("index", [1 << 20, 1 << 28, (1 << 32) - 1])
@pytest.mark.parametrize("opcode", [pickle.PUT, pickle.LONG_BINPUT])
def test_sparse_memo_is_rejected_before_allocation(index, opcode, forbid_native_loader):
    encoded = str(index).encode() + b"\n" if opcode == pickle.PUT else struct.pack("<I", index)
    with pytest.raises(UnsafePayloadError, match="memo index"):
        safe_deserialize(_p4(pickle.NONE + opcode + encoded))


@pytest.mark.parametrize("opcode", [pickle.BINBYTES8, pickle.BINUNICODE8, pickle.BYTEARRAY8, pickle.FRAME])
def test_forged_length_is_rejected_before_allocation(opcode, forbid_native_loader):
    with pytest.raises(UnsafePayloadError):
        safe_deserialize(_p4(opcode + struct.pack("<Q", 1 << 40)))


@pytest.mark.parametrize("suffix", [b"junk", pickle.NONE + pickle.STOP, b"."])
def test_trailing_bytes_inside_frame_are_rejected(suffix, forbid_native_loader):
    wire = pickle.PROTO + b"\x04" + _frame(pickle.NONE + pickle.STOP + suffix)
    with pytest.raises(UnsafePayloadError, match="trailing bytes"):
        safe_deserialize(wire)


@pytest.mark.parametrize("body", [
    _frame(pickle.BININT1) + b"\x01",  # argument crosses the frame boundary
    _frame(_frame(pickle.NONE)),  # nested frame
    pickle.FRAME + struct.pack("<Q", 100) + pickle.NONE,
])
def test_invalid_frames_are_rejected(body, forbid_native_loader):
    with pytest.raises(UnsafePayloadError, match="frame"):
        safe_deserialize(_p4(body))


@pytest.mark.parametrize("body, expected", [
    (_frame(b"") + pickle.NONE, None),
    (_frame(pickle.EMPTY_LIST) + _frame(pickle.MARK + pickle.NONE + pickle.APPENDS), [None]),
    (_frame(pickle.EMPTY_LIST) + pickle.BINBYTES + struct.pack("<I", 100000) + b"x" * 100000
     + _frame(pickle.APPEND), [b"x" * 100000]),
])
def test_valid_mixed_frames_are_accepted(body, expected):
    assert safe_deserialize(_p4(body)) == expected


@pytest.mark.parametrize("stream, expected", [
    (b"(I1\nI2\n0l.", [1]),
    (b"I1\n(0.", 1),
    (b"I1\n(I2\n1.", 1),
    (b"I7\n2\x86.", (7, 7)),
    (b"I1\np0\n0I2\np0\n0g0\n.", 2),
    (b"I1\np2\n0g2\n.", 1),
    (b"I1\np00\n0g00\n.", 1),
    (_p4(b"K\x01q\x050K\x02\x940h\x01"), 2),
])
def test_legacy_stack_and_memo_semantics(stream, expected):
    assert pickle.loads(stream) == expected
    assert safe_deserialize(stream) == expected


def test_deep_tuple_key_is_rejected_before_hashing(forbid_native_loader):
    key = pickle.NONE + pickle.TUPLE1 * 10000
    with pytest.raises(UnsafePayloadError, match="nesting"):
        safe_deserialize(_p4(pickle.EMPTY_DICT + key + pickle.NONE + pickle.SETITEM))


@pytest.mark.parametrize("prefix, suffix", [
    (pickle.EMPTY_DICT, pickle.NONE + pickle.SETITEM),
    (pickle.MARK, pickle.NONE + pickle.DICT),
    (pickle.EMPTY_DICT + pickle.MARK, pickle.NONE + pickle.SETITEMS),
    (pickle.EMPTY_SET + pickle.MARK, pickle.ADDITEMS),
    (pickle.MARK, pickle.FROZENSET),
])
def test_tuple_hash_amplification_is_rejected(prefix, suffix, forbid_native_loader):
    key = pickle.NONE + pickle.TUPLE1 + (pickle.DUP + pickle.TUPLE2) * 40
    with pytest.raises(UnsafePayloadError, match="tuple hashing"):
        safe_deserialize(_p4(prefix + key + suffix))


def test_repeated_big_integer_hashing_is_bounded(forbid_native_loader):
    # A 64 KiB integer (~17.5 K digits) is re-hashed by each of 2048 dicts. The
    # hashing credit is one unit per wire byte (~78 K) plus 256 per opcode plus
    # the integer's own digits, so the integer and a handful of dicts are paid
    # for, and the 2048 re-hashes (~36 M units against ~3.3 M credit) exceed it.
    integer = pickle.LONG4 + struct.pack("<I", 65536) + b"\x01" * 65536
    # Keep the integer in the memo; each new dict forces another hash.
    body = integer + pickle.BINPUT + b"\x00" + pickle.POP + pickle.EMPTY_LIST
    body += (pickle.EMPTY_DICT + pickle.BINGET + b"\x00" + pickle.NONE + pickle.SETITEM + pickle.APPEND) * 2048
    with pytest.raises(UnsafePayloadError, match="key hashing"):
        safe_deserialize(_p4(body))


def test_reconstruction_of_shared_dicts_budgets_key_hashing():
    # One memoized dict with 64 tuple keys of 1024 ints each, referenced 4096 times:
    # ~270 M hash units on reconstruction against a credit of one unit per byte
    # (~200 KB) plus 256 per opcode (~70 K opcodes): ~18 M units.
    keys = [tuple(range(i, i + 1024)) for i in range(64)]
    shared = dict.fromkeys(keys)
    wire = pickle.dumps([shared] * 4096)
    with pytest.raises(UnsafePayloadError, match="key hashing"):
        safe_deserialize(wire)


def test_bulk_padding_credits_only_its_own_bytes(forbid_native_loader):
    # A bulk leaf credits one hash unit per byte, not 256: a 64 KiB bytes leaf
    # (one opcode, ~66 K units) does not pay for a DAG tuple key of ~12.6 M units.
    pad = pickle.BINBYTES8 + struct.pack("<Q", 65536) + b"\x00" * 65536 + pickle.POP
    key = pickle.NONE + pickle.TUPLE1 + (pickle.DUP + pickle.TUPLE2) * 22
    with pytest.raises(UnsafePayloadError, match="hashing budget"):
        safe_deserialize(_p4(pad + pickle.EMPTY_DICT + key + pickle.NONE + pickle.SETITEM))


def test_big_integer_key_is_accepted():
    # A dict keyed by one 64 KiB integer: the integer leaf credits its own digits,
    # so the single hash its insertion needs fits the budget.
    payload = {1 << 524287: 1}
    assert safe_deserialize(safe_serialize(payload)) == payload
    assert safe_deserialize(pickle.dumps(payload)) == payload


@pytest.mark.parametrize("payload", [
    # Two dicts sharing a memoized tuple key around a 64 KiB integer (~35 K units of
    # hashing on 65 KB of wire): accepted by release 0.1.16, whose budget was the
    # wire size, so it must stay accepted.
    [{(1 << 524287,): 0}, {(1 << 524287,): 1}],
    # 1000 dicts sharing a 5000-element tuple key (~5 M units) next to a 10 MB array:
    # the array's bytes pay for the hashing, exactly as they did in 0.1.16.
    {"image": np.zeros(10_000_000, dtype=np.uint8), "meta": [{tuple(range(5000)): i} for i in range(1000)]},
])
def test_payloads_accepted_by_release_0_1_16_stay_accepted(payload):
    rebuilt = safe_deserialize(safe_serialize(payload))
    if isinstance(payload, dict):
        assert np.array_equal(rebuilt["image"], payload["image"]) and rebuilt["meta"] == payload["meta"]
    else:
        assert rebuilt == payload


@pytest.mark.parametrize("key_len", [8, 20, 64, 256])
def test_many_dicts_sharing_a_long_tuple_key_are_accepted(key_len):
    # The hash budget must not reject this legitimate shape: pickle memoizes the
    # tuple key once, and every one of the 1000 dicts re-hashes it on insertion.
    key = tuple(range(key_len))
    payload = [{key: i} for i in range(1000)]
    for wire in (safe_serialize(payload), pickle.dumps(payload)):
        assert safe_deserialize(wire) == payload


def test_shared_tuple_keys_remain_compatible():
    key = ("camera", (1, 2, 3))
    payload = [{key: 1}, {key: 2}]
    assert safe_deserialize(safe_serialize(payload)) == payload


@pytest.mark.parametrize("opcode, arg", [
    (pickle.EXT1, b"\xf0"), (pickle.EXT2, b"\xf0\x00"), (pickle.EXT4, b"\xf0\x00\x00\x00"),
])
def test_cached_extensions_are_always_refused(opcode, arg, monkeypatch, forbid_native_loader):
    # Exercise an empty registry with an independently warm cache as well.
    for key in list(copyreg._extension_registry):
        monkeypatch.delitem(copyreg._extension_registry, key)
    monkeypatch.setitem(copyreg._extension_cache, 240, print)
    with pytest.raises(UnsafePayloadError, match="opcode EXT"):
        safe_deserialize(_p4(opcode + arg))


@pytest.mark.parametrize("make", [bytearray, memoryview])
def test_mutable_input_is_frozen_before_validation(make, monkeypatch):
    original = pickle.dumps({"v": 1})
    source = bytearray(original)
    validate = utils._validate_pickle

    def mutate_after_validation(data):
        assert type(data) is bytes
        credit = validate(data)
        source[:] = b"x" * len(source)
        return credit

    monkeypatch.setattr(utils, "_validate_pickle", mutate_after_validation)
    assert safe_deserialize(make(source)) == {"v": 1}
