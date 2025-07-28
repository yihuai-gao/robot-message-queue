"""
Copyright (c) 2024 Yihuai Gao

This software is released under the MIT License.
https://opensource.org/licenses/MIT
"""

import robotmq as rmq
import time
import pickle
import numpy as np


def test_corner_cases():
    server = rmq.RMQServer("test_rmq_server", "ipc:///tmp/feeds/0")
    client = rmq.RMQClient("test_rmq_client", "ipc:///tmp/feeds/0")

    print("Server and client created")
    server.add_topic("test", 10)
    # server.put_data("test", pickle.dumps(np.random.rand(10)))

    data, timestamp = client.peek_data("test", 1)  # No data available
    print(f"peek_data(1) if no data available: {data}, {timestamp}")

    data, timestamp = client.peek_data("test", 0)  # No data available, return all data
    print(f"peek_data(0) if no data available: {data}, {timestamp}")

    data, timestamp = client.peek_data("test", -5)  # No data available
    print(f"peek_data(-5) if no data available: {data}, {timestamp}")


if __name__ == "__main__":
    test_corner_cases()
