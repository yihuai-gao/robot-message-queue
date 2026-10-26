"""Validate primitive pickle streams before the native unpickler sees them.

The stdlib parses and materializes scalar opcode arguments. This pass tracks
types, memo entries, and tuple hashing costs; it never imports globals or
reconstructs the payload's container graph. Limits scale with wire size or
opcode count, except for fixed bounds on tuple and MARK nesting.

Hash work is counted in units of one tuple element or one big-integer digit
hashed per dictionary insertion. A memoized tuple key is re-hashed by every
dictionary that uses it, so many small dictionaries sharing one long tuple
key legitimately do far more hash work than they have wire bytes. The credit
is one unit per wire byte (the whole budget of release 0.1.16, so everything
it accepted still is), plus `_HASH_WORK_PER_OPCODE` units per opcode parsed
and each integer leaf's own digit count: a bulk bytes / str leaf buys only its
own byte count of hashing, while every reuse of a key costs opcodes. One unit
costs about 1.3-4.4 ns (CPython 3.12, measured; float leaves are the slow
end), so a hostile payload can demand at most about 256 units per opcode plus
one per wire byte in unpickling (what this pass accounts for) and the same
again in `safe_deserialize`'s reconstruction: tens of milliseconds per 10 MiB
of padding, not seconds. This is not a process-level memory or CPU sandbox.
"""

import io
import pickle
import pickletools
import sys


_MAX_TUPLE_DEPTH = 128
_MAX_MARK_DEPTH = 128
_HASH_WORK_PER_OPCODE = 256
_INT_BITS = sys.int_info.bits_per_digit
_LEAF_OPS = frozenset((
    "INT", "BININT", "BININT1", "BININT2", "LONG", "LONG1", "LONG4",
    "FLOAT", "BINFLOAT", "NONE", "NEWTRUE", "NEWFALSE", "STRING", "BINSTRING",
    "SHORT_BINSTRING", "UNICODE", "BINUNICODE", "SHORT_BINUNICODE", "BINUNICODE8",
    "BINBYTES", "SHORT_BINBYTES", "BINBYTES8", "BYTEARRAY8",
))
_PUT_OPS = frozenset(("PUT", "BINPUT", "LONG_BINPUT"))
_GET_OPS = frozenset(("GET", "BINGET", "LONG_BINGET"))
_MARK_OPS = frozenset(("TUPLE", "LIST", "DICT", "APPENDS", "SETITEMS", "ADDITEMS", "FROZENSET"))

# Descriptors: (kind, hash work, tuple depth, short string for error messages).
# Mutable containers are unhashable (work == 0); their contents are not retained.
_SCALAR = ("scalar", 1, 0, None)
_LIST = ("list", 0, 0, None)
_DICT = ("dict", 0, 0, None)
_SET = ("set", 0, 0, None)
_BYTEARRAY = ("bytearray", 0, 0, None)
_TUPLE = ("tuple", 1, 1, None)
_FROZENSET = ("frozenset", 1, 0, None)
_EMPTY_OPS = {
    "EMPTY_LIST": _LIST, "EMPTY_DICT": _DICT,
    "EMPTY_SET": _SET, "EMPTY_TUPLE": _TUPLE,
}


def validate_pickle(data: bytes) -> int:
    """Reject unsafe opcodes, malformed framing, and allocation/hash amplification.

    Returns the hashing credit the stream earned (one unit per wire byte,
    `_HASH_WORK_PER_OPCODE` units per opcode and each integer leaf's digit
    count); the caller hands it to reconstruction as the dict-key hashing budget. Raises ValueError for policy
    failures; stdlib parsing failures propagate to the caller, which wraps them
    in UnsafePayloadError. The caller must pass the same immutable bytes to the
    unpickler after validation.
    """
    size = len(data)
    stream = io.BytesIO(data)
    stack = []
    marks = []
    memo = {}
    frame_end = None
    # Hashing credit starts at one unit per wire byte (release 0.1.16's whole
    # budget) and grows per opcode (and per integer digit) while parsing:
    # `credit` is the running total, `hash_left` the unspent part. A tuple built
    # before its credit is earned is only capped at the most the whole stream
    # can earn (every opcode is at least one byte; an integer's digits never
    # exceed its wire bytes).
    hash_left = size
    credit = size
    tuple_cap = size * (_HASH_WORK_PER_OPCODE + 2)

    def require(count):
        floor = marks[-1] if marks else 0
        if len(stack) - floor < count:
            raise ValueError("invalid pickle stack")

    def charge_hash(values):
        nonlocal hash_left
        for value in values:
            cost = value[1]
            if not cost:
                raise ValueError("unhashable pickle key or set member")
            hash_left -= cost
            if hash_left < 0:
                raise ValueError("pickle key hashing exceeds the hashing budget")

    def tuple_value(values):
        depth = 1
        cost = 1
        hashable = True
        for value in values:
            depth = max(depth, value[2] + 1)
            cost += value[1]
            hashable = hashable and value[1] != 0
        if depth > _MAX_TUPLE_DEPTH:
            raise ValueError("pickle tuple nesting exceeds the depth limit")
        if hashable and cost > tuple_cap:
            raise ValueError("pickle tuple hashing exceeds the hashing budget")
        return ("tuple", cost if hashable else 0, depth, None)

    for opcode, arg, pos in pickletools.genops(stream):
        name = opcode.name
        end = stream.tell()
        hash_left += _HASH_WORK_PER_OPCODE
        credit += _HASH_WORK_PER_OPCODE
        if frame_end is not None:
            if pos == frame_end:
                frame_end = None
            elif end > frame_end or name == "FRAME":
                raise ValueError("pickle opcode crosses a frame boundary")

        if name in _LEAF_OPS:
            if name == "BYTEARRAY8":
                value = _BYTEARRAY
            elif type(arg) is str:
                value = ("str", 1, 0, arg if len(arg) <= 256 else None)
            elif type(arg) is int:
                digits = max(1, (arg.bit_length() + _INT_BITS - 1) // _INT_BITS)
                hash_left += digits
                credit += digits
                value = ("scalar", digits, 0, None)
            else:
                value = _SCALAR
            stack.append(value)
        elif name == "MEMOIZE" or name in _PUT_OPS:
            require(1)
            index = len(memo) if name == "MEMOIZE" else arg
            if not 0 <= index < size:
                raise ValueError("pickle memo index exceeds the payload size")
            memo[index] = stack[-1]
        elif name in _GET_OPS:
            if not 0 <= arg < size or arg not in memo:
                raise ValueError("invalid pickle memo reference")
            stack.append(memo[arg])
        elif name in _EMPTY_OPS:
            stack.append(_EMPTY_OPS[name])
        elif name == "MARK":
            if len(marks) >= _MAX_MARK_DEPTH:
                raise ValueError("pickle mark nesting exceeds the depth limit")
            marks.append(len(stack))
        elif name in _MARK_OPS:
            if not marks:
                raise ValueError("pickle opcode has no matching MARK")
            start = marks.pop()
            values = stack[start:]
            del stack[start:]
            if name == "TUPLE":
                stack.append(tuple_value(values))
            elif name == "LIST":
                stack.append(_LIST)
            elif name == "FROZENSET":
                charge_hash(values)
                stack.append(_FROZENSET)
            elif name == "DICT":
                if len(values) % 2:
                    raise ValueError("pickle dictionary has an unmatched key")
                charge_hash(values[::2])
                stack.append(_DICT)
            else:
                require(1)
                expected = {"APPENDS": _LIST, "SETITEMS": _DICT, "ADDITEMS": _SET}[name]
                if stack[-1] != expected:
                    raise ValueError("pickle container opcode has the wrong target type")
                if name == "SETITEMS":
                    if len(values) % 2:
                        raise ValueError("pickle dictionary has an unmatched key")
                    charge_hash(values[::2])
                elif name == "ADDITEMS":
                    charge_hash(values)
        elif name in ("TUPLE1", "TUPLE2", "TUPLE3"):
            count = int(name[-1])
            require(count)
            value = tuple_value(stack[-count:])
            del stack[-count:]
            stack.append(value)
        elif name == "APPEND":
            require(2)
            if stack[-2] != _LIST:
                raise ValueError("pickle APPEND target is not a list")
            stack.pop()
        elif name == "SETITEM":
            require(3)
            if stack[-3] != _DICT:
                raise ValueError("pickle SETITEM target is not a dictionary")
            charge_hash((stack[-2],))
            del stack[-2:]
        elif name == "POP":
            if marks and len(stack) == marks[-1]:
                marks.pop()
            else:
                require(1)
                stack.pop()
        elif name == "POP_MARK":
            if not marks:
                raise ValueError("pickle POP_MARK has no matching MARK")
            del stack[marks.pop():]
        elif name == "DUP":
            require(1)
            stack.append(stack[-1])
        elif name == "PROTO":
            if pos != 0 or not 0 <= arg <= pickle.HIGHEST_PROTOCOL:
                raise ValueError("invalid pickle protocol header")
        elif name == "FRAME":
            if arg > size - end:
                raise ValueError("pickle frame exceeds the payload size")
            frame_end = end + arg
        elif name == "STOP":
            if end != size:
                raise ValueError("trailing bytes after STOP")
            if marks or len(stack) != 1:
                raise ValueError("pickle STOP requires one complete value")
            return credit
        elif name == "GLOBAL":
            raise ValueError(f"payload references {arg.replace(' ', '.', 1)}; globals are not allowed")
        elif name == "STACK_GLOBAL":
            require(2)
            module, attr = stack[-2][3], stack[-1][3]
            raise ValueError(f"payload references {module}.{attr}; globals are not allowed")
        elif name in ("PERSID", "BINPERSID"):
            raise ValueError("persistent ids are not allowed")
        else:
            # Fail closed for globals, reducers, persistent IDs, extensions,
            # external buffers, and any opcodes added by future Python versions.
            raise ValueError(f"pickle opcode {name} is not allowed")

    raise ValueError("pickle has no STOP opcode")
