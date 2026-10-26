"""Raw wire-protocol helpers shared by the shared-memory test modules."""

from __future__ import annotations

import struct
import time

import zmq

# Wire protocol (native little-endian), see robotmq/core/src/rmq_message.cpp:
# frame = [u8 topic_len][topic][i8 cmd][f64 timestamp][payload]
REQUEST_WITH_DATA = 3
GET_TOPIC_STATUS = 6
CHECK_SHARED_MEMORY = 7
ERROR = -1

SHM_MAGIC = b"\x0d\x0a\x0d\x0b"  # SharedMemoryDataInfo::HEADER


def frame(topic: str, cmd: int, payload: bytes, timestamp: float | None = None) -> bytes:
    """Serialize one RMQ frame. Timestamps must differ between REQUEST_WITH_DATA frames on the
    same topic, or the server answers the second from its deduplication cache."""
    topic_bytes = topic.encode()
    if timestamp is None:
        timestamp = time.monotonic()
    return struct.pack("<B", len(topic_bytes)) + topic_bytes + struct.pack("<bd", cmd, timestamp) + payload


def parse_frame(raw: bytes) -> tuple[str, int, float, bytes]:
    topic_len = raw[0]
    topic = raw[1 : 1 + topic_len].decode(errors="replace")
    cmd, timestamp = struct.unpack_from("<bd", raw, 1 + topic_len)
    payload = raw[1 + topic_len + struct.calcsize("<bd") :]
    return topic, cmd, timestamp, payload


def send_raw_frame(endpoint: str, payload: bytes, timeout_ms: int = 3000) -> bytes | None:
    """Send a raw frame on a REQ socket and return the reply (None on timeout)."""
    with zmq.Context() as ctx:
        with ctx.socket(zmq.REQ) as sock:
            sock.setsockopt(zmq.LINGER, 100)
            sock.connect(endpoint)
            sock.send(payload)
            reply = None
            if sock.poll(timeout_ms):
                reply = sock.recv()
            return reply


def topic_status(endpoint: str, topic: str, timeout_ms: int = 3000) -> bytes:
    """Payload of the server's GET_TOPIC_STATUS reply for `topic` (the request payload is ignored
    by the server; RMQClient sends the text "Get topic status")."""
    raw = send_raw_frame(endpoint, frame(topic, GET_TOPIC_STATUS, b""), timeout_ms=timeout_ms)
    assert raw is not None, f"no GET_TOPIC_STATUS reply for topic {topic!r} within {timeout_ms} ms"
    _topic, cmd, _ts, payload = parse_frame(raw)
    assert cmd == GET_TOPIC_STATUS, f"expected a GET_TOPIC_STATUS reply, got cmd {cmd}: {payload[:80]!r}"
    return payload


def assert_shared_memory_topic(endpoint: str, topic: str) -> None:
    """Assert that the server advertises `topic` as a shared-memory topic on the wire.

    Clients (including the 0.1.16 release) take the shared-memory path only on an exactly 8-byte
    `<i size><i is_shm>` status reply with the flag set; anything else means inline transport.
    """
    payload = topic_status(endpoint, topic)
    assert len(payload) == 8, (
        f"GET_TOPIC_STATUS reply for {topic!r} is {len(payload)} bytes, not the 8-byte <i size><i is_shm> form "
        f"clients (including the 0.1.16 release) require for the shared-memory path: {payload!r}"
    )
    _size, is_shm = struct.unpack("<ii", payload)
    assert is_shm == 1, (
        f"GET_TOPIC_STATUS reply for {topic!r} has is_shm={is_shm}; clients (including the 0.1.16 release) take "
        f"the shared-memory path only when the flag is set"
    )
