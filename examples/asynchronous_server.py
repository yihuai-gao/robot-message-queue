"""
Copyright (c) 2024 Yihuai Gao

This software is released under the MIT License.
https://opensource.org/licenses/MIT
"""

from robotmq import RMQServer, LogLevel
import time
import numpy as np
import numpy.typing as npt

from robotmq.utils import serialize
import pickle


class TestClass:
    def __init__(self):
        self.name = "test_class"
        self.data = np.random.rand(10)


def test_server():
    server = RMQServer("asynchronous_server", "tcp://0.0.0.0:5555", LogLevel.INFO)
    print("Server created")

    # 3 different ways to serialize data. Also applies for synchronous server.
    server.add_shared_memory_topic("test_raw_np", 10, 1)
    # server.add_topic("test_raw_np", 10)
    server.add_topic("test_nested_np", 10)
    server.add_topic("test_pickle", 10)
    # This topic is used to test the client's put_data function
    server.add_topic("put_data_test", 10)

    data_cnt = 0
    rand_data_lens = [10000, 100000, 1000000, 10000000]
    while True:
        rand_data = np.random.rand(rand_data_lens[data_cnt % 4])
        # Simulates a data source that keeps getting data from the sensor at a regular interval
        server.put_data("test_raw_np", rand_data.tobytes())

        serialized_data = serialize(
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
        client_put_message_num = server.get_all_topic_status()["put_data_test"]
        print(
            f"Data cnt: {data_cnt} data size: {rand_data.nbytes / 1024**2:.3f}MB, server topic size: {topic_len}, client put message num: {client_put_message_num}"
        )


if __name__ == "__main__":
    test_server()
