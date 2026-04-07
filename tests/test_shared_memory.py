"""Tests for shared memory topics."""

import time
import numpy as np
import robotmq
from robotmq import serialize, deserialize


class TestSharedMemoryTopic:
    def test_put_and_peek_shm(self, server_client):
        server, client = server_client
        server.add_shared_memory_topic("shm", 10.0, 0.01)  # 10 MB
        server.put_data("shm", b"shm_data")
        time.sleep(0.05)

        data, ts = client.peek_data("shm", 1)
        assert len(data) == 1
        assert data[0] == b"shm_data"

    def test_shm_pop(self, server_client):
        server, client = server_client
        server.add_shared_memory_topic("shm", 10.0, 0.01)
        server.put_data("shm", b"msg1")
        server.put_data("shm", b"msg2")
        time.sleep(0.05)

        data, _ = client.pop_data("shm", 0)
        assert len(data) == 2
        assert data[0] == b"msg1"
        assert data[1] == b"msg2"

    def test_shm_large_numpy(self, server_client):
        server, client = server_client
        server.add_shared_memory_topic("shm_np", 10.0, 0.1)  # 100 MB

        arr = np.random.rand(1000, 1000).astype(np.float64)  # ~8 MB
        server.put_data("shm_np", serialize(arr))
        time.sleep(0.05)

        data, _ = client.peek_data("shm_np", -1)
        result = deserialize(data[0])
        np.testing.assert_array_equal(result, arr)

    def test_shm_n_indexing(self, server_client):
        server, client = server_client
        server.add_shared_memory_topic("shm", 10.0, 0.01)

        for i in range(5):
            server.put_data("shm", str(i).encode())
        time.sleep(0.05)

        # Newest 2
        data, _ = client.peek_data("shm", -2)
        assert len(data) == 2
        assert data[0] == b"3"
        assert data[1] == b"4"

        # All
        data, _ = client.peek_data("shm", 0)
        assert len(data) == 5

    def test_shm_server_local_peek_pop(self, server_client):
        server, _ = server_client
        server.add_shared_memory_topic("shm", 10.0, 0.01)
        server.put_data("shm", b"local")

        data, _ = server.peek_data("shm", 1)
        assert data[0] == b"local"

        data, _ = server.pop_data("shm", 1)
        assert data[0] == b"local"

        data, _ = server.peek_data("shm", 0)
        assert len(data) == 0

    def test_shm_topic_status(self, server_client):
        server, client = server_client
        server.add_shared_memory_topic("shm", 10.0, 0.01)

        status = client.get_topic_status("shm", 1.0)
        assert status == 0

        server.put_data("shm", b"x")
        status = client.get_topic_status("shm", 1.0)
        assert status == 1

    def test_shm_client_put_data(self, server_client):
        server, client = server_client
        server.add_shared_memory_topic("shm", 10.0, 0.01)
        time.sleep(0.05)

        client.put_data("shm", b"from_client")
        time.sleep(0.05)

        # Client-written data to SHM topics is read back via client (through ZeroMQ metadata path)
        data, _ = client.peek_data("shm", 1)
        assert len(data) == 1
        assert data[0] == b"from_client"
