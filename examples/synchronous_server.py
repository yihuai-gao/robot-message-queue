"""
Copyright (c) 2024 Yihuai Gao

This software is released under the MIT License.
https://opensource.org/licenses/MIT
"""

import robotmq
import numpy as np
import numpy.typing as npt
from robotmq.utils import serialize, deserialize
import time


def test_reply_request():
    server = robotmq.RMQServer("test_server", "tcp://*:5555", robotmq.LogLevel.INFO)
    server.add_shared_memory_topic("test_shm_topic", message_remaining_time_s=10.0, shared_memory_size_gb=1.0)
    server.add_topic("test_topic", message_remaining_time_s=10.0)

    while True:
        try:
            print("Waiting for request")
            request_data, request_topic = server.wait_for_request(1.0)
            if not request_topic:
                continue

            start_time = time.time()
            data = deserialize(request_data)
            assert isinstance(data, np.ndarray)
            print(data)
            data += 1.0
            data_bytes = serialize(data)
            server.reply_request(request_topic, data_bytes)
            print(
                f"Replied to request, data processing time: {time.time() - start_time:.3f}s"
            )
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    test_reply_request()
