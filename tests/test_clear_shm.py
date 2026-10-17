"""Tests for clear_shared_memory utility."""

import os
import pwd
import pytest
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
        except OSError:
            try:
                user_name = pwd.getpwuid(os.getuid()).pw_name
            except KeyError:
                user_name = str(os.getuid())
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

    @pytest.mark.parametrize("has_passwd_entry", [True, False])
    def test_cleanup_without_login_session(self, monkeypatch, has_passwd_entry):
        def no_login():
            raise OSError(6, "No such device or address")

        def lookup_user(uid):
            if not has_passwd_entry:
                raise KeyError(uid)
            return type("Passwd", (), {"pw_name": "wheel_test_user"})()

        monkeypatch.setattr(os, "getlogin", no_login)
        monkeypatch.setattr(pwd, "getpwuid", lookup_user)
        username = "wheel_test_user" if has_passwd_entry else str(os.getuid())
        stale_file = f"rmq_{username}_stale"
        monkeypatch.setattr(os, "listdir", lambda path: [stale_file, "unrelated_file"])
        removed = []
        monkeypatch.setattr(os, "remove", removed.append)
        clear_shared_memory()
        assert removed == [f"/dev/shm/{stale_file}"]
