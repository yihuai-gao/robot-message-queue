"""Tests for RMQLogLevel enum and constructor log_level parameter."""

import robotmq


class TestLogLevel:
    def test_all_levels_exist(self):
        levels = [
            robotmq.RMQLogLevel.TRACE,
            robotmq.RMQLogLevel.DEBUG,
            robotmq.RMQLogLevel.INFO,
            robotmq.RMQLogLevel.WARNING,
            robotmq.RMQLogLevel.ERROR,
            robotmq.RMQLogLevel.CRITICAL,
            robotmq.RMQLogLevel.OFF,
        ]
        assert len(levels) == 7

    def test_server_accepts_all_levels(self):
        for level in [robotmq.RMQLogLevel.TRACE, robotmq.RMQLogLevel.OFF, robotmq.RMQLogLevel.WARNING]:
            server = robotmq.RMQServer(
                "log_test_server", f"ipc:///tmp/rmq_log_test_{id(level)}", level
            )

    def test_client_accepts_all_levels(self):
        for level in [robotmq.RMQLogLevel.DEBUG, robotmq.RMQLogLevel.ERROR]:
            client = robotmq.RMQClient(
                "log_test_client", f"ipc:///tmp/rmq_log_test_c_{id(level)}", level
            )

    def test_default_log_level(self, endpoint):
        # Should work without specifying log_level (defaults to INFO)
        server = robotmq.RMQServer("default_log_server", endpoint)
        assert server is not None
