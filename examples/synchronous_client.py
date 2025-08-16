"""
Copyright (c) 2024 Yihuai Gao

This software is released under the MIT License.
https://opensource.org/licenses/MIT
"""

import robotmq
import numpy as np
import numpy.typing as npt
import time
from robotmq.utils import serialize, deserialize


def test_request_with_data():
    client = robotmq.RMQClient("test_client", "tcp://localhost:5555")
    # input_data = serialize(np.array([1, 2, 3], dtype=np.float64))
    topics = ["test_shm_topic", "test_topic"]
    for topic in topics:
        input_data = np.random.randn(100000000)
        data_bytes = serialize(input_data)
        start_time = time.time()
        reply = client.request_with_data(topic, data_bytes, timeout_s=10)
        end_time = time.time()
        reply_data = deserialize(reply)

        print(
            f"Topic: {topic}, request with data (size: {input_data.nbytes / 1024**2:.3f}MB) time spent: {end_time - start_time}, "
            f"correctness: {np.allclose(reply_data, input_data + 1)}"
        )


if __name__ == "__main__":
    test_request_with_data()
