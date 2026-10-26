"""Regression tests for the shared-memory failure paths of RMQServer / RMQClient.

Behaviour covered (on a shared-memory topic unless stated otherwise):

* A REQUEST_WITH_DATA whose block is a descriptor the server cannot read (missing,
  unreadable or out-of-bounds segment) is answered by the server's own background thread
  with an ERROR reply naming the segment; wait_for_request never sees it and the server
  keeps serving.
* A raw (non-descriptor) REQUEST_WITH_DATA no longer wedges the server: Python receives the
  bytes, replies, the raw client gets a REQUEST_WITH_DATA reply, and the next request works.
* A payload larger than the topic's segment is refused: put_data and reply_request raise
  ValueError and store nothing, a client waiting for that reply gets an error reply at once,
  and the topic keeps working afterwards.
* A failed shared-memory request leaves no ``*_request`` segment behind in /dev/shm.
* RMQClient.check_shared_memory(topic, timeout_s) diagnoses the shared-memory path end to
  end and always removes its ``*_probe`` segment.

Servers that must REPLY from Python run in a separate process (wait_for_request holds the
GIL); servers whose background thread answers on its own stay in-process. Raw frames are
sent with a pyzmq REQ socket (tests/_rmq_wire.py) as in test_malformed_frames.py. Every
client call carries a timeout so a regression fails instead of hanging.
"""

from __future__ import annotations

import contextlib
import glob
import os
import random
import stat
import struct
import threading
import time
import types
import uuid
from multiprocessing import shared_memory

import pytest

import robotmq
from tests._rmq_wire import (
    CHECK_SHARED_MEMORY,
    ERROR,
    REQUEST_WITH_DATA,
    SHM_MAGIC,
    check_shared_memory_request,
    frame,
    parse_frame,
    send_raw_frame,
    topic_status,
)
from tests._shm_server_processes import SMALL_SEGMENT_GB, SPAWN, random_bytes, running_echo_server

SMALL_SEGMENT_BYTES = int(SMALL_SEGMENT_GB * 1024**3)

requires_non_root = pytest.mark.skipif(os.geteuid() == 0, reason="chmod 0 does not deny root")


# --------------------------------------------------------------------------------------
# Payload helpers (frame-level helpers live in tests/_rmq_wire.py)
# --------------------------------------------------------------------------------------


def _unique(prefix: str) -> str:
    """A name unique per test, so /dev/shm globs on this pid never match a previous test's
    server (a failed test's traceback can keep its server, and thus its segment, alive)."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _data_blocks(blocks: list[bytes], timestamp: float = 0.0) -> bytes:
    """Data-block payload: [u32 block_num] then per block [u32 len][f64 ts], then the bytes."""
    out = struct.pack("<I", len(blocks))
    for block in blocks:
        out += struct.pack("<Id", len(block), timestamp)
    return out + b"".join(blocks)


def _parse_data_blocks(payload: bytes) -> list[bytes]:
    (block_num,) = struct.unpack_from("<I", payload, 0)
    offset = 4
    lengths = []
    for _ in range(block_num):
        length, _ts = struct.unpack_from("<Id", payload, offset)
        offset += struct.calcsize("<Id")
        lengths.append(length)
    blocks = []
    for length in lengths:
        blocks.append(payload[offset : offset + length])
        offset += length
    assert offset == len(payload), "data-block payload has trailing bytes"
    return blocks


def _descriptor(name: str, segment_size: int, start: int, data_size: int) -> bytes:
    """Shared-memory descriptor block (SharedMemoryDataInfo::serialize); `name` is bare."""
    name_bytes = name.encode()
    geometry = struct.pack("<QQQ", segment_size, start, data_size)
    return SHM_MAGIC + struct.pack("<Q", len(name_bytes)) + name_bytes + geometry


def _resolve_block(block: bytes) -> bytes:
    """The bytes a reply block stands for: inline bytes, or the segment slice a descriptor names."""
    if not block.startswith(SHM_MAGIC):
        return block
    offset = len(SHM_MAGIC)
    (name_len,) = struct.unpack_from("<Q", block, offset)
    offset += 8
    name = block[offset : offset + name_len].decode()
    offset += name_len
    segment_size, start, data_size = struct.unpack_from("<QQQ", block, offset)
    assert offset + 24 == len(block), "descriptor has trailing bytes"
    with open(f"/dev/shm/{name}", "rb") as fh:
        segment = fh.read()
    assert len(segment) == segment_size
    if start + data_size <= segment_size:
        return segment[start : start + data_size]
    head = segment[start:]
    return head + segment[: data_size - len(head)]


def _parse_check_reply(payload: bytes) -> tuple[int, int, int, int, bytes, bytes, bytes]:
    """CHECK_SHARED_MEMORY reply: i32 status, u64 st_dev, u64 st_ino, u64 segment_size, then
    three u32-length-prefixed byte strings (probe echo, server segment name, error text)."""
    status, st_dev, st_ino, segment_size = struct.unpack_from("<iQQQ", payload, 0)
    offset = struct.calcsize("<iQQQ")
    strings = []
    for _ in range(3):
        (length,) = struct.unpack_from("<I", payload, offset)
        offset += 4
        strings.append(payload[offset : offset + length])
        offset += length
    assert offset == len(payload), "CHECK_SHARED_MEMORY reply has trailing bytes"
    return status, st_dev, st_ino, segment_size, strings[0], strings[1], strings[2]


def _send_check_request(endpoint: str, payload: bytes):
    raw = send_raw_frame(endpoint, frame("shm", CHECK_SHARED_MEMORY, payload), timeout_ms=3000)
    assert raw is not None, "no reply to a raw CHECK_SHARED_MEMORY frame"
    _topic, cmd, _ts, reply_payload = parse_frame(raw)
    assert cmd == CHECK_SHARED_MEMORY, f"expected a CHECK_SHARED_MEMORY reply, got cmd {cmd}: {reply_payload[:80]!r}"
    return _parse_check_reply(reply_payload)


# --------------------------------------------------------------------------------------
# /dev/shm helpers
# --------------------------------------------------------------------------------------


@contextlib.contextmanager
def _mode_zero(path: str):
    """chmod 0 on a /dev/shm file this user owns, restoring the original mode afterwards."""
    original = stat.S_IMODE(os.stat(path).st_mode)
    os.chmod(path, 0)
    try:
        yield
    finally:
        os.chmod(path, original)


def _server_segments(server_name: str, topic: str) -> tuple[str, str]:
    """(data segment, mutex segment) of an in-process server's shared-memory topic."""
    pid = os.getpid()
    data = glob.glob(f"/dev/shm/rmq_*_{pid}_{server_name}_{topic}")
    mutex = glob.glob(f"/dev/shm/rmq_*_{pid}_{server_name}_{topic}_mutex")
    assert len(data) == 1, f"expected one data segment, found {data}"
    assert len(mutex) == 1, f"expected one mutex segment, found {mutex}"
    return data[0], mutex[0]


def _request_segments(client_name: str, topic: str) -> list[str]:
    return glob.glob(f"/dev/shm/rmq_*_{os.getpid()}_{client_name}_{topic}_*_request")


def _assert_no_probe_segment(client_name: str, topic: str) -> None:
    leftover = glob.glob(f"/dev/shm/rmq_*_{os.getpid()}_{client_name}_{topic}_*_probe")
    assert leftover == [], f"check_shared_memory left its probe segment behind: {leftover}"


def _check_invalid_timeouts(endpoint, client_name, timeouts, result_sender):
    """Run potentially unbounded native polls in a child that the test can terminate."""
    client = robotmq.RMQClient(client_name, endpoint, robotmq.RMQLogLevel.ERROR)
    results = [client.check_shared_memory("shm", timeout_s=value) for value in timeouts]
    result_sender.send(results)
    result_sender.close()


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


@pytest.fixture
def shm_server(endpoint):
    """In-process server with one small shared-memory topic; nobody calls wait_for_request."""
    server_name = _unique("shmfail_srv")
    server = robotmq.RMQServer(server_name, endpoint, robotmq.RMQLogLevel.ERROR)
    server.add_shared_memory_topic("shm", 10.0, SMALL_SEGMENT_GB)
    yield types.SimpleNamespace(server=server, endpoint=endpoint, server_name=server_name)


@pytest.fixture
def check_setup(endpoint):
    """In-process server with a shared-memory topic `shm` and a plain topic `plain`, plus a client."""
    server_name = _unique("shmcheck_srv")
    client_name = _unique("shmcheck_cli")
    server = robotmq.RMQServer(server_name, endpoint, robotmq.RMQLogLevel.ERROR)
    server.add_shared_memory_topic("shm", 10.0, 0.001)
    server.add_topic("plain", 10.0)
    client = robotmq.RMQClient(client_name, endpoint, robotmq.RMQLogLevel.ERROR)
    yield types.SimpleNamespace(
        server=server, client=client, endpoint=endpoint, server_name=server_name, client_name=client_name
    )


# --------------------------------------------------------------------------------------
# 1. The server answers an unreadable request segment itself
# --------------------------------------------------------------------------------------


class TestUnreadableRequestSegment:
    def test_missing_segment_gets_error_reply_and_server_keeps_serving(self, endpoint):
        topic = "shm"
        seen = SPAWN.Value("i", 0)
        with running_echo_server(endpoint, _unique("shmfail_srv"), topic, seen_count=seen):
            missing = _unique("rmq_test_missing")
            assert not os.path.exists(f"/dev/shm/{missing}")
            descriptor = _descriptor(missing, 64, 0, 64)
            raw = send_raw_frame(
                endpoint, frame(topic, REQUEST_WITH_DATA, _data_blocks([descriptor])), timeout_ms=2000
            )
            assert raw is not None, "no reply within 2 s to a request naming a missing segment"
            _topic, cmd, _ts, payload = parse_frame(raw)
            assert cmd == ERROR, f"expected an ERROR reply, got cmd {cmd}"
            text = payload.decode("utf-8", errors="replace")
            assert "cannot read the request's shared memory segment" in text
            assert missing in text

            # The background thread answered alone: the Python loop never saw the request.
            assert seen.value == 0

            # The same server still serves a normal request afterwards.
            client = robotmq.RMQClient(_unique("shmfail_cli"), endpoint, robotmq.RMQLogLevel.ERROR)
            reply = client.request_with_data(topic, b"after the bad request", timeout_s=5.0, automatic_resend=False)
            assert reply == b"after the bad request"
            assert seen.value == 1

    @requires_non_root
    def test_unreadable_segment_gets_error_reply(self, shm_server):
        segment = shared_memory.SharedMemory(create=True, size=64)
        try:
            with _mode_zero(f"/dev/shm/{segment.name}"):
                descriptor = _descriptor(segment.name, 64, 0, 64)
                raw = send_raw_frame(
                    shm_server.endpoint,
                    frame("shm", REQUEST_WITH_DATA, _data_blocks([descriptor])),
                    timeout_ms=2000,
                )
                assert raw is not None, "no reply within 2 s to a request naming an unreadable segment"
                _topic, cmd, _ts, payload = parse_frame(raw)
                assert cmd == ERROR, f"expected an ERROR reply, got cmd {cmd}"
                text = payload.decode("utf-8", errors="replace")
                assert "cannot read the request's shared memory segment" in text
                assert segment.name in text
                assert "Permission denied" in text
        finally:
            segment.close()
            segment.unlink()

        # Handled without Python: the server is alive and the bad request was not queued.
        client = robotmq.RMQClient(_unique("shmfail_cli"), shm_server.endpoint, robotmq.RMQLogLevel.ERROR)
        assert client.get_topic_status("shm", 3.0) == 0

    def test_out_of_bounds_descriptor_gets_error_reply(self, shm_server):
        segment = shared_memory.SharedMemory(create=True, size=64)
        try:
            # data_size larger than the segment itself.
            descriptor = _descriptor(segment.name, 64, 0, 4096)
            raw = send_raw_frame(
                shm_server.endpoint,
                frame("shm", REQUEST_WITH_DATA, _data_blocks([descriptor])),
                timeout_ms=2000,
            )
            assert raw is not None, "no reply within 2 s to an out-of-bounds descriptor"
            _topic, cmd, _ts, payload = parse_frame(raw)
            assert cmd == ERROR, f"expected an ERROR reply, got cmd {cmd}"
            text = payload.decode("utf-8", errors="replace")
            assert "cannot read the request's shared memory segment" in text
            assert "out of bounds" in text
        finally:
            segment.close()
            segment.unlink()

        client = robotmq.RMQClient(_unique("shmfail_cli"), shm_server.endpoint, robotmq.RMQLogLevel.ERROR)
        assert client.get_topic_status("shm", 3.0) == 0

    def test_undersized_segment_gets_error_reply(self, shm_server):
        segment = shared_memory.SharedMemory(create=True, size=64)
        try:
            # The descriptor is self-consistent (1 MB segment, 1 MB of data), but the segment on disk
            # holds 64 bytes: the fstat size check refuses it before any byte is read.
            descriptor = _descriptor(segment.name, 1 << 20, 0, 1 << 20)
            raw = send_raw_frame(
                shm_server.endpoint,
                frame("shm", REQUEST_WITH_DATA, _data_blocks([descriptor])),
                timeout_ms=2000,
            )
            assert raw is not None, "no reply within 2 s to a descriptor larger than its segment"
            _topic, cmd, _ts, payload = parse_frame(raw)
            assert cmd == ERROR, f"expected an ERROR reply, got cmd {cmd}"
            text = payload.decode("utf-8", errors="replace")
            assert "cannot read the request's shared memory segment" in text
            assert segment.name in text
            assert "fewer than" in text
        finally:
            segment.close()
            segment.unlink()

        client = robotmq.RMQClient(_unique("shmfail_cli"), shm_server.endpoint, robotmq.RMQLogLevel.ERROR)
        assert client.get_topic_status("shm", 3.0) == 0

    def test_segment_shrunk_during_read_gets_error_reply_not_sigbus(self, endpoint):
        """A request segment that shrinks while the server reads it yields an ERROR reply, not a
        SIGBUS in the server.

        The size checks (the background thread's before parking the request, wait_for_request's on
        opening the segment) pass only while the segment is full, so the fault needs a shrink that
        lands between the last check and the end of the read: a race. A thread flaps the segment
        between 64 MiB and 0, holding each state for a random 0.1-0.5 ms: longer than the 100 us
        poll of wait_for_request, so a request can pass both checks, and far shorter than the few
        ms a 64 MiB read takes, so the shrink lands inside the read. Measured on the pread binary,
        that puts about a third to a half of the 40 requests into the read window (a tight loop
        without a pause manages 3 %), so the pre-fix SIGBUS (server exitcode -7, replies stop
        arriving) shows up reliably. After the fix every interleaving is acceptable: a normal reply
        when the read won, an ERROR naming the segment when a size check or the read lost. The
        context manager then asserts the server exited cleanly and unlinked its segments.
        """
        topic = "shm"
        size = 64 << 20
        with running_echo_server(endpoint, _unique("shmtrunc_srv"), topic, fixed_reply=b"ok") as process:
            name = _unique("rmq_test_trunc")
            segment = shared_memory.SharedMemory(name=name, create=True, size=size)
            try:
                fd = os.open(f"/dev/shm/{name}", os.O_RDWR)
                stop = threading.Event()
                dwell = random.Random(20261026)

                def flap_size():
                    while not stop.is_set():
                        os.ftruncate(fd, 0)
                        time.sleep(dwell.uniform(1e-4, 5e-4))
                        os.ftruncate(fd, size)
                        time.sleep(dwell.uniform(1e-4, 5e-4))

                flapper = threading.Thread(target=flap_size, daemon=True)
                flapper.start()
                try:
                    for i in range(40):
                        raw = send_raw_frame(
                            endpoint,
                            frame(topic, REQUEST_WITH_DATA, _data_blocks([_descriptor(name, size, 0, size)])),
                            timeout_ms=5000,
                        )
                        assert raw is not None, (
                            f"no reply within 5 s to request {i} naming the flapping segment: the server stopped "
                            f"answering (alive={process.is_alive()}, exitcode={process.exitcode})"
                        )
                        _topic, cmd, _ts, payload = parse_frame(raw)
                        if cmd == REQUEST_WITH_DATA:
                            assert [_resolve_block(block) for block in _parse_data_blocks(payload)] == [b"ok"]
                        else:
                            assert cmd == ERROR, f"request {i}: expected REQUEST_WITH_DATA or ERROR, got cmd {cmd}"
                            assert name.encode() in payload, (
                                f"request {i}: ERROR reply does not name the segment: {payload!r}"
                            )
                finally:
                    stop.set()
                    flapper.join(timeout=5.0)
                    os.close(fd)
            finally:
                segment.close()
                segment.unlink()
            assert process.is_alive(), (
                f"the server process died (exitcode {process.exitcode}) while reading a shrinking segment"
            )


# --------------------------------------------------------------------------------------
# 2. A raw (non-descriptor) REQUEST_WITH_DATA no longer wedges the server
# --------------------------------------------------------------------------------------


class TestRawRequestOnSharedMemoryTopic:
    def test_raw_inline_request_is_served_and_server_keeps_working(self, endpoint):
        topic = "shm"
        received = SPAWN.Queue()
        with running_echo_server(endpoint, _unique("shmraw_srv"), topic, received_queue=received):
            raw_request = b"raw inline request bytes"
            raw = send_raw_frame(
                endpoint, frame(topic, REQUEST_WITH_DATA, _data_blocks([raw_request])), timeout_ms=5000
            )
            assert raw is not None, "server did not answer a raw REQUEST_WITH_DATA (wedged)"
            reply_topic, cmd, _ts, payload = parse_frame(raw)
            assert cmd == REQUEST_WITH_DATA, f"expected a REQUEST_WITH_DATA reply, got cmd {cmd}: {payload[:80]!r}"
            assert reply_topic == topic
            blocks = _parse_data_blocks(payload)
            assert len(blocks) == 1
            assert _resolve_block(blocks[0]) == raw_request

            # The server's Python side got the raw bytes from wait_for_request.
            assert received.get(timeout=5.0) == raw_request

            # A later normal request still works.
            client = robotmq.RMQClient(_unique("shmraw_cli"), endpoint, robotmq.RMQLogLevel.ERROR)
            assert (
                client.request_with_data(topic, b"normal request", timeout_s=5.0, automatic_resend=False)
                == b"normal request"
            )


# --------------------------------------------------------------------------------------
# 3. Oversized data on a shared-memory topic is refused, not sent another way
# --------------------------------------------------------------------------------------


class TestOversizedPayloadRefused:
    def test_put_data_raises_and_stores_nothing(self, shm_server):
        server = shm_server.server
        client = robotmq.RMQClient(_unique("shmbig_cli"), shm_server.endpoint, robotmq.RMQLogLevel.ERROR)

        exact_fit = random_bytes(random.Random(1), SMALL_SEGMENT_BYTES)
        server.put_data("shm", exact_fit)  # the whole segment is usable
        assert server.pop_data("shm", 0)[0] == [exact_fit]

        one_over = f"{SMALL_SEGMENT_BYTES + 1} bytes does not fit the {SMALL_SEGMENT_BYTES}-byte shared memory"
        with pytest.raises(ValueError, match=one_over):
            server.put_data("shm", random_bytes(random.Random(2), SMALL_SEGMENT_BYTES + 1))
        with pytest.raises(ValueError, match="does not fit"):
            server.put_data("shm", random_bytes(random.Random(3), 3 * SMALL_SEGMENT_BYTES))
        assert server.peek_data("shm", 0)[0] == []
        assert client.get_topic_status("shm", 3.0) == 0

        # The topic keeps working afterwards.
        small = b"after the refusal" * 10
        server.put_data("shm", small)
        assert client.pop_data("shm", 0, timeout_s=5.0, automatic_resend=False)[0] == [small]

    def test_oversized_reply_raises_on_server_and_errors_the_client(self, endpoint):
        topic = "shm"
        reply_errors = SPAWN.Queue()
        with running_echo_server(endpoint, _unique("shmbig_srv"), topic, reply_errors=reply_errors):
            client = robotmq.RMQClient(_unique("shmbig_cli"), endpoint, robotmq.RMQLogLevel.ERROR)
            big = random_bytes(random.Random(20261025), 1 << 20)
            assert len(big) > SMALL_SEGMENT_BYTES
            # The echo of a 1 MB request does not fit the topic's segment: reply_request raises in the server
            # process, and the client is told at once instead of running into its timeout.
            with pytest.raises(RuntimeError, match="could not store its reply on topic `shm`.*does not fit"):
                client.request_with_data(topic, big, timeout_s=5.0, automatic_resend=False)
            server_error = reply_errors.get(timeout=5.0)
            assert "does not fit" in server_error and str(len(big)) in server_error, server_error
            # The server keeps serving.
            assert client.request_with_data(topic, b"fits", timeout_s=5.0, automatic_resend=False) == b"fits"

    def test_ring_keeps_exactly_the_entries_that_fit(self, shm_server):
        server = shm_server.server
        client = robotmq.RMQClient(_unique("shmbig_cli"), shm_server.endpoint, robotmq.RMQLogLevel.ERROR)

        # Fill the ring well past its capacity.
        small_size = 2000
        pushed = []
        for i in range(120):
            payload = struct.pack("<I", i) * (small_size // 4)
            server.put_data("shm", payload)
            pushed.append(payload)
        assert len(pushed) * small_size > SMALL_SEGMENT_BYTES

        assert client.peek_data("shm", -1, timeout_s=5.0, automatic_resend=False)[0] == [pushed[-1]]
        assert server.peek_data("shm", -1)[0] == [pushed[-1]]
        retained = client.peek_data("shm", 0, timeout_s=5.0, automatic_resend=False)[0]
        # Deterministic: the ring keeps exactly as many 2000-byte entries as fit, the newest ones, in order.
        assert len(retained) == SMALL_SEGMENT_BYTES // small_size, (
            f"expected {SMALL_SEGMENT_BYTES // small_size} retained entries, got {len(retained)}"
        )
        assert retained == pushed[-len(retained) :], "retained entries are not the newest ones, in order"


# --------------------------------------------------------------------------------------
# 4. A failed shared-memory request leaves no request segment behind
# --------------------------------------------------------------------------------------


class TestFailedRequestLeavesNoSegment:
    def test_timed_out_request_unlinks_request_segment(self, shm_server):
        client_name = _unique("shmleak_cli")
        client = robotmq.RMQClient(client_name, shm_server.endpoint, robotmq.RMQLogLevel.ERROR)
        assert _request_segments(client_name, "shm") == []

        # Nobody calls wait_for_request on this server, so the request can only time out.
        with pytest.raises(RuntimeError, match="No reply from server"):
            client.request_with_data("shm", b"x" * 1000, timeout_s=0.5, automatic_resend=False)

        assert _request_segments(client_name, "shm") == [], "request segment leaked after a failed request"

        # The descriptor is still parked in the topic (nobody pops it), so the server's own peek fails on
        # the client's `_request` segment: proof that a descriptor was sent and its segment is gone.
        with pytest.raises(RuntimeError, match=r"_request"):
            shm_server.server.peek_data("shm", 0)


# --------------------------------------------------------------------------------------
# 5. RMQClient.check_shared_memory
# --------------------------------------------------------------------------------------


class TestCheckSharedMemory:
    def test_shared_memory_topic_is_ok(self, check_setup):
        result = check_setup.client.check_shared_memory("shm", timeout_s=1.0)
        assert result == (True, "")
        _assert_no_probe_segment(check_setup.client_name, "shm")

    def test_plain_topic_is_refused(self, check_setup):
        ok, reason = check_setup.client.check_shared_memory("plain", timeout_s=1.0)
        assert ok is False
        assert "is not a shared memory topic" in reason
        _assert_no_probe_segment(check_setup.client_name, "plain")

    def test_unknown_topic_is_refused(self, check_setup):
        ok, reason = check_setup.client.check_shared_memory("no_such_topic", timeout_s=1.0)
        assert ok is False
        assert "is not a topic of the server" in reason
        _assert_no_probe_segment(check_setup.client_name, "no_such_topic")

    def test_topic_status_reply_pins_the_shared_memory_flag(self, check_setup):
        # This is the contract old clients decide the transport on: the 0.1.16 release takes the
        # shared-memory path only on an exactly 8-byte `<i size><i is_shm>` reply with the flag set.
        # Pinned here because the cross-version module is skipped where no old install exists.
        shm_status = topic_status(check_setup.endpoint, "shm")
        assert len(shm_status) == 8, f"shm status payload: {shm_status!r}"
        assert struct.unpack("<ii", shm_status)[1] == 1
        plain_status = topic_status(check_setup.endpoint, "plain")
        assert len(plain_status) == 8, f"plain status payload: {plain_status!r}"
        assert struct.unpack("<ii", plain_status)[1] == 0
        assert topic_status(check_setup.endpoint, "no_such_topic") == struct.pack("<i", -1)

    @requires_non_root
    def test_unopenable_server_segment_is_reported(self, check_setup):
        data_segment, _mutex_segment = _server_segments(check_setup.server_name, "shm")
        with _mode_zero(data_segment):
            ok, reason = check_setup.client.check_shared_memory("shm", timeout_s=1.0)
        assert ok is False
        assert "cannot open the server's shared memory segment" in reason
        _assert_no_probe_segment(check_setup.client_name, "shm")
        assert check_setup.client.get_topic_status("shm", 3.0) == 0

    @requires_non_root
    def test_unopenable_server_mutex_is_reported(self, check_setup):
        _data_segment, mutex_segment = _server_segments(check_setup.server_name, "shm")
        with _mode_zero(mutex_segment):
            ok, reason = check_setup.client.check_shared_memory("shm", timeout_s=1.0)
        assert ok is False
        assert "cannot open the server's shared memory mutex" in reason
        _assert_no_probe_segment(check_setup.client_name, "shm")
        assert check_setup.client.get_topic_status("shm", 3.0) == 0

    @pytest.mark.parametrize("truncated_size", [0, 1])
    def test_truncated_server_mutex_is_reported(self, check_setup, truncated_size):
        _data_segment, mutex_segment = _server_segments(check_setup.server_name, "shm")
        # CHECK_SHARED_MEMORY only reads the server's metadata, without locking this mutex. Restore its exact
        # initialized contents before any data operation or fixture teardown can touch the existing mapping.
        with open(mutex_segment, "r+b", buffering=0) as mutex_file:
            original = mutex_file.read()
            assert truncated_size < len(original)
            try:
                mutex_file.truncate(truncated_size)
                ok, reason = check_setup.client.check_shared_memory("shm", timeout_s=1.0)
            finally:
                mutex_file.truncate(len(original))
                mutex_file.seek(0)
                assert mutex_file.write(original) == len(original)

        assert ok is False
        assert "shared memory mutex" in reason
        assert f"holds {truncated_size} bytes, fewer than the required" in reason
        _assert_no_probe_segment(check_setup.client_name, "shm")
        assert check_setup.client.check_shared_memory("shm", timeout_s=1.0) == (True, "")

    def test_raw_probe_naming_missing_segment_reports_status_2(self, check_setup):
        # A probe segment is named `<...>_probe` and holds a few bytes; this one does not exist.
        missing = f"{_unique('rmq_test_missing')}_probe"
        assert not os.path.exists(f"/dev/shm/{missing}")
        raw = send_raw_frame(
            check_setup.endpoint,
            frame("shm", CHECK_SHARED_MEMORY, check_shared_memory_request(_descriptor(missing, 32, 0, 32), b"x" * 32)),
            timeout_ms=3000,
        )
        assert raw is not None, "no reply to a raw CHECK_SHARED_MEMORY frame"
        _topic, cmd, _ts, payload = parse_frame(raw)
        assert cmd == CHECK_SHARED_MEMORY, f"expected a CHECK_SHARED_MEMORY reply, got cmd {cmd}: {payload[:80]!r}"
        status, _st_dev, _st_ino, _segment_size, probe_echo, _server_segment, error_text = _parse_check_reply(payload)
        assert status == 2, f"expected status 2 (server could not read the probe), got {status}"
        assert missing.encode() in error_text
        assert b"No such file" in error_text
        assert probe_echo == b""

        # The probe did not disturb the server.
        assert check_setup.client.get_topic_status("shm", 3.0) == 0

    def test_raw_probe_naming_server_segment_is_refused(self, check_setup):
        # The reply must never echo another segment's contents: a descriptor for the server's own data
        # segment (not a `_probe` name, far larger than a probe) is refused with status 2 and no bytes.
        data_segment, _mutex_segment = _server_segments(check_setup.server_name, "shm")
        descriptor = _descriptor(os.path.basename(data_segment), int(0.001 * 1024**3), 0, 64)
        raw = send_raw_frame(
            check_setup.endpoint,
            frame("shm", CHECK_SHARED_MEMORY, check_shared_memory_request(descriptor, b"x" * 64)),
            timeout_ms=3000,
        )
        assert raw is not None, "no reply to a raw CHECK_SHARED_MEMORY frame"
        _topic, cmd, _ts, payload = parse_frame(raw)
        assert cmd == CHECK_SHARED_MEMORY, f"expected a CHECK_SHARED_MEMORY reply, got cmd {cmd}: {payload[:80]!r}"
        status, _st_dev, _st_ino, _segment_size, probe_echo, _server_segment, error_text = _parse_check_reply(payload)
        assert status == 2, f"expected status 2 (not a probe segment), got {status}"
        assert b"is not a probe segment" in error_text
        assert probe_echo == b"", f"the reply echoed the server's segment: {probe_echo[:80]!r}"
        assert check_setup.client.get_topic_status("shm", 3.0) == 0

    def test_raw_probe_larger_than_probe_limit_is_refused(self, check_setup):
        # A `_probe` name alone is not enough: a 65-byte segment exceeds the 64-byte probe limit.
        name = f"{_unique('rmq_test_big')}_probe"
        segment = shared_memory.SharedMemory(create=True, size=65, name=name)
        try:
            raw = send_raw_frame(
                check_setup.endpoint,
                frame("shm", CHECK_SHARED_MEMORY, check_shared_memory_request(_descriptor(name, 65, 0, 65), b"x" * 64)),
                timeout_ms=3000,
            )
            assert raw is not None, "no reply to a raw CHECK_SHARED_MEMORY frame"
            _topic, cmd, _ts, payload = parse_frame(raw)
            assert cmd == CHECK_SHARED_MEMORY, f"expected a CHECK_SHARED_MEMORY reply, got cmd {cmd}: {payload[:80]!r}"
            status, _st_dev, _st_ino, _segment_size, probe_echo, _server_segment, error_text = _parse_check_reply(payload)
            assert status == 2, f"expected status 2 (not a probe segment), got {status}"
            assert b"is not a probe segment" in error_text
            assert probe_echo == b"", f"the reply echoed an oversized probe: {probe_echo[:80]!r}"
        finally:
            segment.close()
            segment.unlink()
        assert check_setup.client.get_topic_status("shm", 3.0) == 0

    def test_raw_probe_actual_size_cannot_exceed_advertised_limit(self, check_setup):
        name = f"{_unique('rmq_test_hidden_size')}_probe"
        segment = shared_memory.SharedMemory(create=True, size=65, name=name)
        nonce = b"x" * 64
        try:
            segment.buf[:64] = nonce
            request = check_shared_memory_request(_descriptor(name, 64, 0, 64), nonce)
            status, _dev, _ino, _size, echo, _name, error = _send_check_request(check_setup.endpoint, request)
            assert status == 2
            assert b"holds 65 bytes, more than the allowed 64" in error
            assert echo == b""
        finally:
            segment.close()
            segment.unlink()

    def test_raw_probe_cannot_read_a_topic_named_probe(self, check_setup):
        # The protected segment belongs to a different topic than the CHECK_SHARED_MEMORY request. Even a small
        # topic whose name has the probe suffix must not be treated as a client's diagnostic probe.
        check_setup.server.add_shared_memory_topic("probe", 10.0, 64 / 1024**3)
        nonce = b"private topic payload".ljust(64, b"!")
        check_setup.server.put_data("probe", nonce)
        data_segment, mutex_segment = _server_segments(check_setup.server_name, "probe")
        request = check_shared_memory_request(_descriptor(os.path.basename(data_segment), 64, 0, 64), nonce)
        status, _dev, _ino, _size, echo, _name, error = _send_check_request(check_setup.endpoint, request)
        assert status == 2
        assert b"belongs to a server topic" in error
        assert echo == b""

        # Mutex names are also refused, before mapping or reading their contents.
        request = check_shared_memory_request(_descriptor(os.path.basename(mutex_segment), 1, 0, 1), b"x")
        status, _dev, _ino, _size, echo, _name, _error = _send_check_request(check_setup.endpoint, request)
        assert status == 2 and echo == b""
        assert check_setup.server.peek_data("probe", 0)[0] == [nonce]

    @pytest.mark.parametrize("matches", [True, False])
    def test_raw_probe_echo_requires_a_matching_nonce(self, check_setup, matches):
        name = f"{_unique('rmq_test_nonce')}_probe"
        segment = shared_memory.SharedMemory(create=True, size=64, name=name)
        contents = bytes(range(64))
        try:
            segment.buf[:] = contents
            # This descriptor wraps around the ring, exercising both reads before the comparison.
            nonce = contents[48:] + contents[:16] if matches else b"x" * 32
            request = check_shared_memory_request(_descriptor(name, 64, 48, 32), nonce)
            status, _dev, _ino, _size, echo, _name, error = _send_check_request(check_setup.endpoint, request)
            if matches:
                assert status == 0 and echo == nonce and error == b""
            else:
                assert status == 2 and echo == b""
                assert b"do not match the supplied nonce" in error
        finally:
            segment.close()
            segment.unlink()

    @pytest.mark.parametrize(
        "malformation",
        ["empty_nonce", "long_nonce", "wrong_length", "truncated", "trailing", "bare_descriptor", "out_of_bounds"],
    )
    def test_raw_probe_invalid_request_returns_no_echo(self, check_setup, malformation):
        name = f"{_unique('rmq_test_bad_probe')}_probe"
        segment = shared_memory.SharedMemory(create=True, size=16, name=name)
        try:
            nonce = b"x" * 16
            segment.buf[:] = nonce
            descriptor = _descriptor(name, 16, 0, 16)
            if malformation == "out_of_bounds":
                descriptor = _descriptor(name, 16, 17, 16)
            if malformation == "empty_nonce":
                nonce = b""
            elif malformation == "long_nonce":
                nonce = b"x" * 65
            elif malformation == "wrong_length":
                nonce = b"x" * 15
            request = check_shared_memory_request(descriptor, nonce)
            if malformation == "truncated":
                request = request[:-1]
            elif malformation == "trailing":
                request += b"extra"
            elif malformation == "bare_descriptor":
                request = descriptor
            status, _dev, _ino, _size, echo, _name, error = _send_check_request(check_setup.endpoint, request)
            assert status == 2 and echo == b"" and error
        finally:
            segment.close()
            segment.unlink()
        assert check_setup.client.check_shared_memory("shm", timeout_s=1.0) == (True, "")

    def test_raw_probe_partial_failed_read_returns_no_echo(self, check_setup):
        name = f"{_unique('rmq_test_partial_probe')}_probe"
        segment = shared_memory.SharedMemory(create=True, size=64, name=name)
        nonce = b"private-prefix!!" + b"\0" * 48
        stop = threading.Event()
        fd = os.open(f"/dev/shm/{name}", os.O_RDWR)

        def flap_size():
            while not stop.is_set():
                os.ftruncate(fd, 16)
                os.ftruncate(fd, 64)

        flapper = threading.Thread(target=flap_size, daemon=True)
        try:
            segment.buf[:] = nonce
            request = check_shared_memory_request(_descriptor(name, 64, 0, 64), nonce)
            flapper.start()
            partial_failure_seen = False
            # A reported read failure (rather than fstat rejection) necessarily follows a partial read: the file
            # never shrinks below 16 bytes, so the first pread at offset zero cannot return EOF. The bounded race
            # exercises the same failure path as a client shrinking its probe between fstat and pread.
            for _ in range(2000):
                status, _dev, _ino, _size, echo, _name, error = _send_check_request(check_setup.endpoint, request)
                if status == 0:
                    assert echo == nonce
                else:
                    assert status == 2 and echo == b""
                    if b"segment shrank while it was read" in error:
                        partial_failure_seen = True
                        break
            assert partial_failure_seen, "did not exercise a partial probe read before the bounded race ended"
        finally:
            stop.set()
            if flapper.ident is not None:
                flapper.join(timeout=5.0)
            os.close(fd)
            segment.close()
            segment.unlink()

    def test_invalid_timeouts_are_refused_without_waiting(self):
        endpoint = f"ipc:///tmp/rmq_test_bad_timeout_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        client_name = _unique("shmcheck_bad_timeout")
        cases = [
            (-1.0, "timeout_s must be non-negative"),
            (float("-inf"), "timeout_s must be non-negative"),
            (float("nan"), "timeout_s must be finite"),
            (float("inf"), "timeout_s must be finite"),
            ((2**31) / 1000.0, "timeout_s must be finite"),
            (1e30, "timeout_s must be finite"),
        ]
        receiver, sender = SPAWN.Pipe(duplex=False)
        process = SPAWN.Process(
            target=_check_invalid_timeouts,
            args=(endpoint, client_name, [value for value, _reason in cases], sender),
        )
        process.start()
        sender.close()
        probe_pattern = f"/dev/shm/rmq_*_{process.pid}_{client_name}_shm_*_probe"
        try:
            process.join(timeout=15.0)
            assert not process.is_alive(), "invalid timeout waited indefinitely for an absent server"
            assert process.exitcode == 0, f"timeout-check subprocess exited with {process.exitcode}"
            assert receiver.poll(1.0), "timeout-check subprocess returned no results"
            results = receiver.recv()
            assert len(results) == len(cases)
            for (value, prefix), (ok, reason) in zip(cases, results):
                assert ok is False and reason.startswith(prefix), (value, ok, reason)
            assert glob.glob(probe_pattern) == [], "invalid timeout left a probe segment behind"
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5.0)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5.0)
            receiver.close()
            # A regressed child can be killed while holding a probe; remove only this test child's objects.
            for path in glob.glob(probe_pattern):
                os.unlink(path)

    def test_no_server_returns_false_within_timeout(self):
        endpoint = f"ipc:///tmp/rmq_test_no_server_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        client_name = _unique("shmcheck_cli")
        client = robotmq.RMQClient(client_name, endpoint, robotmq.RMQLogLevel.ERROR)

        started = time.monotonic()
        ok, reason = client.check_shared_memory("shm", timeout_s=1.0)
        elapsed = time.monotonic() - started

        assert ok is False
        assert "no reply from the server" in reason
        assert elapsed < 3.0, f"check_shared_memory took {elapsed:.1f} s for timeout_s=1.0"
        _assert_no_probe_segment(client_name, "shm")

    def test_check_does_not_disturb_request_reply(self, endpoint):
        topic = "shm"
        with running_echo_server(endpoint, _unique("shmcheck_srv"), topic):
            client_name = _unique("shmcheck_cli")
            client = robotmq.RMQClient(client_name, endpoint, robotmq.RMQLogLevel.ERROR)
            assert client.check_shared_memory(topic, timeout_s=1.0) == (True, "")
            _assert_no_probe_segment(client_name, topic)
            assert (
                client.request_with_data(topic, b"hello after check", timeout_s=5.0, automatic_resend=False)
                == b"hello after check"
            )
