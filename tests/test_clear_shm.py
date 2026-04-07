"""Tests for clear_shared_memory utility."""

import os
import robotmq
from robotmq.utils import clear_shared_memory


class TestClearSharedMemory:
    def test_clears_shm_files(self, endpoint):
        server = robotmq.RMQServer("shm_cleanup_server", endpoint, robotmq.RMQLogLevel.WARNING)
        server.add_shared_memory_topic("cleanup_test", 10.0, 0.01)
        server.put_data("cleanup_test", b"data")

        # Verify at least one rmq_ file exists in /dev/shm
        try:
            user_name = os.getlogin()
        except (FileNotFoundError, OSError):
            user_name = os.getuid()
        shm_files = [f for f in os.listdir("/dev/shm") if f.startswith(f"rmq_{user_name}_")]
        assert len(shm_files) > 0

        # Cleanup — server must be deleted first so it releases the shm
        del server

        clear_shared_memory()

        shm_files = [f for f in os.listdir("/dev/shm") if f.startswith(f"rmq_{user_name}_")]
        assert len(shm_files) == 0

    def test_clear_no_files(self):
        # Should not raise even if no rmq files exist
        clear_shared_memory()
