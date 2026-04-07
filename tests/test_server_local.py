"""Tests for RMQServer local operations (put/peek/pop without a client)."""

import time
import numpy as np
import robotmq


class TestServerPutPeekPop:
    def test_put_and_peek(self, server_client):
        server, _ = server_client
        server.add_topic("t", 10.0)
        server.put_data("t", b"hello")

        data, ts = server.peek_data("t", 1)
        assert len(data) == 1
        assert data[0] == b"hello"
        assert len(ts) == 1

    def test_peek_does_not_remove(self, server_client):
        server, _ = server_client
        server.add_topic("t", 10.0)
        server.put_data("t", b"msg")

        server.peek_data("t", 1)
        data, _ = server.peek_data("t", 1)
        assert len(data) == 1
        assert data[0] == b"msg"

    def test_pop_removes(self, server_client):
        server, _ = server_client
        server.add_topic("t", 10.0)
        server.put_data("t", b"msg")

        data, _ = server.pop_data("t", 1)
        assert len(data) == 1
        assert data[0] == b"msg"

        data, _ = server.peek_data("t", 0)
        assert len(data) == 0

    def test_n_positive_returns_oldest(self, server_client):
        server, _ = server_client
        server.add_topic("t", 10.0)
        for i in range(5):
            server.put_data("t", str(i).encode())

        data, _ = server.peek_data("t", 2)
        assert len(data) == 2
        assert data[0] == b"0"
        assert data[1] == b"1"

    def test_n_negative_returns_newest(self, server_client):
        server, _ = server_client
        server.add_topic("t", 10.0)
        for i in range(5):
            server.put_data("t", str(i).encode())

        data, _ = server.peek_data("t", -2)
        assert len(data) == 2
        assert data[0] == b"3"
        assert data[1] == b"4"

    def test_n_zero_returns_all(self, server_client):
        server, _ = server_client
        server.add_topic("t", 10.0)
        for i in range(5):
            server.put_data("t", str(i).encode())

        data, _ = server.peek_data("t", 0)
        assert len(data) == 5

    def test_peek_empty_topic(self, server_client):
        server, _ = server_client
        server.add_topic("t", 10.0)

        for n in [1, 0, -5]:
            data, ts = server.peek_data("t", n)
            assert len(data) == 0
            assert len(ts) == 0

    def test_n_larger_than_available(self, server_client):
        server, _ = server_client
        server.add_topic("t", 10.0)
        server.put_data("t", b"only_one")

        data, _ = server.peek_data("t", 10)
        assert len(data) == 1

        data, _ = server.peek_data("t", -10)
        assert len(data) == 1

    def test_multiple_topics(self, server_client):
        server, _ = server_client
        server.add_topic("a", 10.0)
        server.add_topic("b", 10.0)

        server.put_data("a", b"data_a")
        server.put_data("b", b"data_b")

        data_a, _ = server.peek_data("a", 1)
        data_b, _ = server.peek_data("b", 1)
        assert data_a[0] == b"data_a"
        assert data_b[0] == b"data_b"

    def test_timestamps_are_monotonic(self, server_client):
        server, _ = server_client
        server.add_topic("t", 10.0)
        for _ in range(5):
            server.put_data("t", b"x")
            time.sleep(0.01)

        _, timestamps = server.peek_data("t", 0)
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1]


class TestServerTopicStatus:
    def test_get_all_topic_status(self, server_client):
        server, _ = server_client
        server.add_topic("a", 10.0)
        server.add_topic("b", 10.0)
        server.put_data("a", b"1")
        server.put_data("a", b"2")

        status = server.get_all_topic_status()
        assert status["a"] == 2
        assert status["b"] == 0


class TestServerMessageExpiration:
    def test_messages_expire(self, server_client):
        server, _ = server_client
        server.add_topic("t", 0.3)

        server.put_data("t", b"old")
        time.sleep(0.5)
        # Inserting a new message triggers pruning of expired messages
        server.put_data("t", b"new")

        data, _ = server.peek_data("t", 0)
        assert len(data) == 1
        assert data[0] == b"new"


class TestServerTimestamp:
    def test_get_timestamp(self, server_client):
        server, _ = server_client
        ts = server.get_timestamp()
        assert isinstance(ts, float)

    def test_reset_start_time(self, server_client):
        server, _ = server_client
        sys_time = robotmq.system_clock_us()
        server.reset_start_time(sys_time)
        ts = server.get_timestamp()
        assert ts >= 0.0
        assert ts < 1.0  # should be near zero right after reset
