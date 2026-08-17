"""Regression tests: malformed raw ZMQ frames must never crash the server.

Before the 0.1.15 fix, sending a raw garbage frame to an RMQServer aborted the
whole process: parsing threw std::invalid_argument on the native background
thread (uncaught -> std::terminate -> SIGABRT), and a truncated header (valid
topic length + topic, but missing cmd/timestamp) additionally read out of
bounds. These tests send raw garbage frames with pyzmq (REQ, matching the
server's REP socket) and then verify the server still serves a normal
RMQClient request.
"""

import zmq
import pytest
import robotmq


@pytest.fixture
def malformed_server(endpoint):
    server = robotmq.RMQServer("malformed_test_server", endpoint, robotmq.RMQLogLevel.ERROR)
    server.add_topic("test_topic", 10.0)
    yield server, endpoint


def _send_raw_frame(endpoint: str, payload: bytes, timeout_ms: int = 3000) -> bytes | None:
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


def test_malformed_frames_do_not_kill_server(malformed_server):
    server, endpoint = malformed_server

    # Empty frame: previously the parser's std::invalid_argument went uncaught
    # on the background thread and aborted the process.
    reply = _send_raw_frame(endpoint, b"")
    # The server should answer with a best-effort ERROR reply (also keeps the
    # REP state machine from wedging).
    assert reply is not None and len(reply) > 0

    # 1-byte garbage frame: claims a 7-byte topic that is not there.
    reply = _send_raw_frame(endpoint, b"\x07")
    assert reply is not None and len(reply) > 0

    # Truncated header: valid topic length + topic, but missing cmd/timestamp.
    # Previously this passed the length check and read past the end of the
    # buffer.
    reply = _send_raw_frame(endpoint, b"\x03abc")
    assert reply is not None and len(reply) > 0

    # The server must still be alive and answer a normal client call.
    client = robotmq.RMQClient("malformed_test_client", endpoint, robotmq.RMQLogLevel.ERROR)
    status = client.get_topic_status("test_topic", 3.0)
    assert status == 0

    # And normal data flow still works end to end.
    server.put_data("test_topic", b"still alive")
    data, _timestamps = client.pop_data("test_topic", 1, 3.0)
    assert data == [b"still alive"]
