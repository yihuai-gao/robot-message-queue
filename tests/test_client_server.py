"""Tests for RMQClient-RMQServer communication over IPC."""

import time
import numpy as np
import pytest
import robotmq
from robotmq import serialize, deserialize


class TestClientPeekPop:
    def test_client_peek(self, server_client):
        server, client = server_client
        server.add_topic("t", 10.0)
        server.put_data("t", b"hello")
        time.sleep(0.05)

        data, ts = client.peek_data("t", 1)
        assert len(data) == 1
        assert data[0] == b"hello"

    def test_client_peek_does_not_remove(self, server_client):
        server, client = server_client
        server.add_topic("t", 10.0)
        server.put_data("t", b"msg")
        time.sleep(0.05)

        client.peek_data("t", 1)
        data, _ = client.peek_data("t", 1)
        assert len(data) == 1

    def test_client_pop_removes(self, server_client):
        server, client = server_client
        server.add_topic("t", 10.0)
        server.put_data("t", b"msg")
        time.sleep(0.05)

        data, _ = client.pop_data("t", 1)
        assert len(data) == 1
        assert data[0] == b"msg"

        data, _ = client.pop_data("t", 0)
        assert len(data) == 0

    def test_client_n_negative(self, server_client):
        server, client = server_client
        server.add_topic("t", 10.0)
        for i in range(5):
            server.put_data("t", str(i).encode())
        time.sleep(0.05)

        data, _ = client.peek_data("t", -2)
        assert len(data) == 2
        assert data[0] == b"3"
        assert data[1] == b"4"

    def test_client_n_zero(self, server_client):
        server, client = server_client
        server.add_topic("t", 10.0)
        for i in range(3):
            server.put_data("t", str(i).encode())
        time.sleep(0.05)

        data, _ = client.peek_data("t", 0)
        assert len(data) == 3

    def test_client_empty_topic(self, server_client):
        server, client = server_client
        server.add_topic("t", 10.0)
        time.sleep(0.05)

        data, ts = client.peek_data("t", 1)
        assert len(data) == 0
        assert len(ts) == 0


class TestClientPutData:
    def test_client_put_data(self, server_client):
        server, client = server_client
        server.add_topic("t", 10.0)
        time.sleep(0.05)

        client.put_data("t", b"from_client")
        time.sleep(0.05)

        data, _ = server.peek_data("t", 1)
        assert len(data) == 1
        assert data[0] == b"from_client"


class TestClientTopicStatus:
    def test_topic_exists(self, server_client):
        server, client = server_client
        server.add_topic("t", 10.0)
        server.put_data("t", b"1")
        server.put_data("t", b"2")

        status = client.get_topic_status("t", 1.0)
        assert status == 2

    def test_topic_empty(self, server_client):
        server, client = server_client
        server.add_topic("t", 10.0)

        status = client.get_topic_status("t", 1.0)
        assert status == 0

    def test_topic_not_exist(self, server_client):
        server, client = server_client

        status = client.get_topic_status("nonexistent", 1.0)
        assert status == -1

    def test_server_unreachable(self):
        # Run in subprocess to avoid ZeroMQ destructor hangs on never-connected sockets
        import subprocess, sys
        code = (
            "import os, sys, robotmq; "
            "c = robotmq.RMQClient('x', 'tcp://127.0.0.1:19876', robotmq.RMQLogLevel.ERROR); "
            "s = c.get_topic_status('t', 0.5); "
            "print(s); sys.stdout.flush(); os._exit(0)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=15
        )
        assert result.returncode == 0
        assert "-2" in result.stdout


class TestClientGetLastRetrievedData:
    def test_after_peek(self, server_client):
        server, client = server_client
        server.add_topic("t", 10.0)
        server.put_data("t", b"data1")
        time.sleep(0.05)

        client.peek_data("t", 1)
        data, ts = client.get_last_retrieved_data()
        assert len(data) == 1
        assert data[0] == b"data1"

    def test_after_pop(self, server_client):
        server, client = server_client
        server.add_topic("t", 10.0)
        server.put_data("t", b"data2")
        time.sleep(0.05)

        client.pop_data("t", 1)
        data, ts = client.get_last_retrieved_data()
        assert len(data) == 1
        assert data[0] == b"data2"


class TestClientTimestamp:
    def test_get_timestamp(self, server_client):
        _, client = server_client
        ts = client.get_timestamp()
        assert isinstance(ts, float)

    def test_reset_start_time(self, server_client):
        _, client = server_client
        sys_time = robotmq.system_clock_us()
        client.reset_start_time(sys_time)
        ts = client.get_timestamp()
        assert ts >= 0.0
        assert ts < 1.0


class TestAutomaticResend:
    def _run_no_server_test(self, code):
        """Run test in subprocess to avoid ZeroMQ destructor hangs on disconnected sockets."""
        import subprocess, sys
        # Use os._exit(0) for success and os._exit(1) for unexpected errors, to avoid
        # ZeroMQ socket destructor hangs when client never connected to a server.
        wrapped = (
            "import os, sys, robotmq\n"
            "try:\n"
            f"    {code}\n"
            "    print('ERROR: no exception raised'); sys.stdout.flush(); os._exit(1)\n"
            "except RuntimeError as e:\n"
            "    print(str(e)); sys.stdout.flush(); os._exit(0)\n"
            "except Exception as e:\n"
            "    print(f'WRONG: {e}'); sys.stdout.flush(); os._exit(1)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", wrapped],
            capture_output=True, text=True, timeout=15
        )
        assert result.returncode == 0, f"Subprocess failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "No reply from server" in result.stdout

    def test_automatic_resend_false_peek(self):
        self._run_no_server_test(
            "c = robotmq.RMQClient('x', 'tcp://127.0.0.1:19877', robotmq.RMQLogLevel.WARNING);"
            "c.peek_data('t', 1, timeout_s=0.5, automatic_resend=False)"
        )

    def test_automatic_resend_false_pop(self):
        self._run_no_server_test(
            "c = robotmq.RMQClient('x', 'tcp://127.0.0.1:19878', robotmq.RMQLogLevel.WARNING);"
            "c.pop_data('t', 1, timeout_s=0.5, automatic_resend=False)"
        )

    def test_automatic_resend_false_put(self):
        self._run_no_server_test(
            "c = robotmq.RMQClient('x', 'tcp://127.0.0.1:19879', robotmq.RMQLogLevel.WARNING);"
            "c.put_data('t', b'data', timeout_s=0.5, automatic_resend=False)"
        )

    def test_automatic_resend_false_request(self):
        self._run_no_server_test(
            "c = robotmq.RMQClient('x', 'tcp://127.0.0.1:19880', robotmq.RMQLogLevel.WARNING);"
            "c.request_with_data('t', b'data', timeout_s=0.5, automatic_resend=False)"
        )


class TestNumpyOverNetwork:
    def test_numpy_roundtrip(self, server_client):
        server, client = server_client
        server.add_topic("np", 10.0)

        arr = np.random.rand(100, 50).astype(np.float64)
        server.put_data("np", serialize(arr))
        time.sleep(0.05)

        data, _ = client.peek_data("np", 1)
        result = deserialize(data[0])
        np.testing.assert_array_equal(result, arr)

    def test_nested_structure_roundtrip(self, server_client):
        server, client = server_client
        server.add_topic("nested", 10.0)

        payload = {
            "image": np.random.rand(4, 4, 3).astype(np.float32),
            "joints": np.array([0.1, 0.2], dtype=np.float64),
            "meta": {"frame_id": 42},
        }
        server.put_data("nested", serialize(payload))
        time.sleep(0.05)

        data, _ = client.peek_data("nested", 1)
        result = deserialize(data[0])
        np.testing.assert_array_equal(result["image"], payload["image"])
        np.testing.assert_array_equal(result["joints"], payload["joints"])
        assert result["meta"]["frame_id"] == 42
