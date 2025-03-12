"""
 Copyright (c) 2024 Yihuai Gao
 
 This software is released under the MIT License.
 https://opensource.org/licenses/MIT
"""

from robotmq import RMQServer
import time
import numpy as np
import numpy.typing as npt

from robotmq.utils import serialize_numpy
import pickle


class TestClass:
    def __init__(self):
        self.name = "test_class"
        self.data = np.random.rand(10)


def test_server():
    server = RMQServer("asynchronous_server", "tcp://0.0.0.0:5555")
    print("Server created")

    # 3 different ways to serialize data. Also applies for synchronous server.
    server.add_topic("test_raw_np", 10)
    server.add_topic("test_nested_np", 10)
    server.add_topic("test_pickle", 10)

    data_cnt = 0
    rand_data_lens = [10000, 100000, 1000000, 10000000]
    while True:
        rand_data = np.random.rand(rand_data_lens[data_cnt % 4])
        # Simulates a data source that keeps getting data from the sensor at a regular interval
        server.put_data("test_raw_np", rand_data.tobytes())

        serialized_data = serialize_numpy(
            {
                "data": rand_data,
                "tag": "test_nested_np",
                "nested_data": {
                    "data": rand_data,
                    "data_list": [
                        np.random.rand(10),
                        np.random.rand(10),
                        (np.random.rand(10), np.random.rand(10)),
                    ],
                },
            }
        )
        server.put_data("test_nested_np", serialized_data)

        serialized_data = pickle.dumps(TestClass())
        server.put_data("test_pickle", serialized_data)

        time.sleep(1)
        data_cnt += 1
        topic_len = server.get_all_topic_status()["test_raw_np"]
        print(
            f"Data cnt: {data_cnt} data size: {rand_data.nbytes / 1024**2:.3f}MB, topic size: {topic_len}"
        )


if __name__ == "__main__":
    test_server()
