"""Tests for the request-reply (synchronous) communication pattern."""

import threading
import time
import numpy as np
import robotmq
from robotmq import serialize, deserialize


def _run_echo_server(server, topic, duration_s=5.0):
    """Server loop that echoes request data back with +1 added (for numpy arrays)."""
    deadline = time.time() + duration_s
    while time.time() < deadline:
        req_data, req_topic = server.wait_for_request(0.5)
        if not req_topic:
            continue
        data = deserialize(req_data)
        if isinstance(data, np.ndarray):
            reply = serialize(data + 1)
        else:
            reply = req_data  # echo back raw
        server.reply_request(req_topic, reply)


class TestRequestReply:
    def test_basic_request_reply(self, server_client):
        server, client = server_client
        server.add_topic("rpc", 10.0)

        t = threading.Thread(target=_run_echo_server, args=(server, "rpc", 5.0))
        t.start()

        arr = np.array([1.0, 2.0, 3.0])
        reply = client.request_with_data("rpc", serialize(arr), timeout_s=3.0)
        result = deserialize(reply)
        np.testing.assert_array_equal(result, arr + 1)
        t.join(timeout=6.0)

    def test_request_reply_shm(self, server_client):
        server, client = server_client
        server.add_shared_memory_topic("rpc_shm", 10.0, 0.1)

        t = threading.Thread(target=_run_echo_server, args=(server, "rpc_shm", 5.0))
        t.start()

        arr = np.random.rand(1000).astype(np.float64)
        reply = client.request_with_data("rpc_shm", serialize(arr), timeout_s=3.0)
        result = deserialize(reply)
        np.testing.assert_array_equal(result, arr + 1)
        t.join(timeout=6.0)

    def test_multiple_requests(self, server_client):
        server, client = server_client
        server.add_topic("rpc", 10.0)

        t = threading.Thread(target=_run_echo_server, args=(server, "rpc", 10.0))
        t.start()

        for i in range(5):
            arr = np.array([float(i)])
            reply = client.request_with_data("rpc", serialize(arr), timeout_s=3.0)
            result = deserialize(reply)
            np.testing.assert_array_equal(result, arr + 1)
        t.join(timeout=11.0)

    def test_wait_for_request_timeout(self, server_client):
        server, _ = server_client
        server.add_topic("rpc", 10.0)

        req_data, req_topic = server.wait_for_request(0.1)
        assert req_data == b""
        assert req_topic == ""


class TestRequestReplyDeduplication:
    def test_deduplication_does_not_reprocess(self, server_client):
        """Verify that server-side deduplication caches replies for retried requests."""
        server, client = server_client
        server.add_topic("dedup", 10.0)

        call_count = 0

        def counting_server(server, duration_s=5.0):
            nonlocal call_count
            deadline = time.time() + duration_s
            while time.time() < deadline:
                req_data, req_topic = server.wait_for_request(0.5)
                if not req_topic:
                    continue
                call_count += 1
                server.reply_request(req_topic, req_data)

        t = threading.Thread(target=counting_server, args=(server, 5.0))
        t.start()

        arr = np.array([1.0, 2.0])
        reply = client.request_with_data("dedup", serialize(arr), timeout_s=3.0)
        result = deserialize(reply)
        np.testing.assert_array_equal(result, arr)

        # The server should have processed exactly one request
        t.join(timeout=6.0)
        assert call_count == 1
