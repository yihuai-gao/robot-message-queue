"""Tests for clock utility functions."""

import time
import robotmq


class TestClockFunctions:
    def test_steady_clock_returns_int(self):
        result = robotmq.steady_clock_us()
        assert isinstance(result, int)

    def test_system_clock_returns_int(self):
        result = robotmq.system_clock_us()
        assert isinstance(result, int)

    def test_steady_clock_is_monotonic(self):
        t1 = robotmq.steady_clock_us()
        time.sleep(0.01)
        t2 = robotmq.steady_clock_us()
        assert t2 > t1

    def test_system_clock_is_reasonable(self):
        # System clock should be in the ballpark of current time in microseconds
        us = robotmq.system_clock_us()
        # Should be after year 2020 in microseconds
        assert us > 1_577_836_800_000_000

    def test_steady_clock_microsecond_resolution(self):
        t1 = robotmq.steady_clock_us()
        t2 = robotmq.steady_clock_us()
        # Two back-to-back calls should differ by at most a few thousand us
        assert (t2 - t1) < 1_000_000  # less than 1 second apart
