"""Tests for the request-reply (synchronous) communication pattern.

Note: wait_for_request holds the GIL during its busy loop, so the server
and client must run in separate processes (not threads).
"""

import multiprocessing
import time
import numpy as np
import pytest
import robotmq
from robotmq import serialize, deserialize


ENDPOINT = "ipc:///tmp/rmq_test_rpc"


def _echo_server_process(endpoint, topic, ready_event, duration_s=10.0):
    """Server process that echoes request data back with +1 for numpy arrays."""
    server = robotmq.RMQServer("rpc_server", endpoint, robotmq.RMQLogLevel.WARNING)
    server.add_topic(topic, 10.0)
    ready_event.set()

    deadline = time.time() + duration_s
    while time.time() < deadline:
        req_data, req_topic = server.wait_for_request(0.5)
        if not req_topic:
            continue
        data = deserialize(req_data)
        if isinstance(data, np.ndarray):
            reply = serialize(data + 1)
        else:
            reply = req_data
        server.reply_request(req_topic, reply)


def _echo_server_shm_process(endpoint, topic, ready_event, duration_s=10.0):
    """Server process with shared memory topic."""
    server = robotmq.RMQServer("rpc_shm_server", endpoint, robotmq.RMQLogLevel.WARNING)
    server.add_shared_memory_topic(topic, 10.0, 0.1)
    ready_event.set()

    deadline = time.time() + duration_s
    while time.time() < deadline:
        req_data, req_topic = server.wait_for_request(0.5)
        if not req_topic:
            continue
        data = deserialize(req_data)
        if isinstance(data, np.ndarray):
            reply = serialize(data + 1)
        else:
            reply = req_data
        server.reply_request(req_topic, reply)


def _counting_server_process(endpoint, topic, ready_event, count_value, duration_s=10.0):
    """Server process that counts how many requests it processes."""
    server = robotmq.RMQServer("count_server", endpoint, robotmq.RMQLogLevel.WARNING)
    server.add_topic(topic, 10.0)
    ready_event.set()

    deadline = time.time() + duration_s
    while time.time() < deadline:
        req_data, req_topic = server.wait_for_request(0.5)
        if not req_topic:
            continue
        count_value.value += 1
        server.reply_request(req_topic, req_data)


class TestRequestReply:
    def test_basic_request_reply(self):
        endpoint = "ipc:///tmp/rmq_rpc_basic"
        ready = multiprocessing.Event()
        p = multiprocessing.Process(target=_echo_server_process, args=(endpoint, "rpc", ready, 10.0))
        p.start()
        try:
            ready.wait(timeout=5.0)
            client = robotmq.RMQClient("rpc_client", endpoint, robotmq.RMQLogLevel.WARNING)

            arr = np.array([1.0, 2.0, 3.0])
            reply = client.request_with_data("rpc", serialize(arr), timeout_s=5.0)
            result = deserialize(reply)
            np.testing.assert_array_equal(result, arr + 1)
        finally:
            p.terminate()
            p.join(timeout=3.0)

    def test_request_reply_shm(self):
        endpoint = "ipc:///tmp/rmq_rpc_shm"
        ready = multiprocessing.Event()
        p = multiprocessing.Process(target=_echo_server_shm_process, args=(endpoint, "rpc_shm", ready, 10.0))
        p.start()
        try:
            ready.wait(timeout=5.0)
            client = robotmq.RMQClient("rpc_shm_client", endpoint, robotmq.RMQLogLevel.WARNING)

            arr = np.random.rand(1000).astype(np.float64)
            reply = client.request_with_data("rpc_shm", serialize(arr), timeout_s=5.0)
            result = deserialize(reply)
            np.testing.assert_array_equal(result, arr + 1)
        finally:
            p.terminate()
            p.join(timeout=3.0)

    def test_multiple_requests(self):
        endpoint = "ipc:///tmp/rmq_rpc_multi"
        ready = multiprocessing.Event()
        p = multiprocessing.Process(target=_echo_server_process, args=(endpoint, "rpc", ready, 15.0))
        p.start()
        try:
            ready.wait(timeout=5.0)
            client = robotmq.RMQClient("rpc_multi_client", endpoint, robotmq.RMQLogLevel.WARNING)

            for i in range(5):
                arr = np.array([float(i)])
                reply = client.request_with_data("rpc", serialize(arr), timeout_s=5.0)
                result = deserialize(reply)
                np.testing.assert_array_equal(result, arr + 1)
        finally:
            p.terminate()
            p.join(timeout=3.0)

    def test_wait_for_request_timeout(self, server_client):
        server, _ = server_client
        server.add_topic("rpc", 10.0)

        req_data, req_topic = server.wait_for_request(0.1)
        assert req_data == b""
        assert req_topic == ""


class TestRequestReplyDeduplication:
    def test_deduplication_does_not_reprocess(self):
        endpoint = "ipc:///tmp/rmq_rpc_dedup"
        ready = multiprocessing.Event()
        call_count = multiprocessing.Value("i", 0)
        p = multiprocessing.Process(
            target=_counting_server_process,
            args=(endpoint, "dedup", ready, call_count, 10.0),
        )
        p.start()
        try:
            ready.wait(timeout=5.0)
            client = robotmq.RMQClient("dedup_client", endpoint, robotmq.RMQLogLevel.WARNING)

            arr = np.array([1.0, 2.0])
            reply = client.request_with_data("dedup", serialize(arr), timeout_s=5.0)
            result = deserialize(reply)
            np.testing.assert_array_equal(result, arr)
            assert call_count.value == 1
        finally:
            p.terminate()
            p.join(timeout=3.0)
