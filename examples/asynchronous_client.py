"""
 Copyright (c) 2024 Yihuai Gao
 
 This software is released under the MIT License.
 https://opensource.org/licenses/MIT
"""

import pickle
from robotmq import RMQClient
import time
import numpy as np
import numpy.typing as npt

from robotmq.utils import deserialize_numpy
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestClass:  # This class can be defined in client's environment as well (if cannot be imported from server)
    def __init__(self):
        self.name = "test_class"
        self.data = np.random.rand(10)


def test_client():
    client = RMQClient("asynchronous_client", "tcp://localhost:5555")
    print("Client created")

    while True:
        start_time = time.time()
        raw_data_list, timestamps = client.pop_data("test_raw_np", "earliest", 1)
        end_popping_time = time.time()
        if raw_data_list:
            # You can also use pickle to deserialize the arbitrary data
            data = np.frombuffer(raw_data_list[0], dtype=np.float64)
            print(
                f"Received numpy data: shape: {data.shape}, size: {data.nbytes / 1024**2:.3f}MB, receiving time: {end_popping_time - start_time:.3f}s"
            )

        nested_data_list, timestamps = client.pop_data("test_nested_np", "earliest", 1)
        if nested_data_list:
            nested_data = deserialize_numpy(nested_data_list[0])
            print(f"Received nested data: {nested_data}")

        pickle_data_list, timestamps = client.pop_data("test_pickle", "earliest", 1)
        if pickle_data_list:
            pickle_data = pickle.loads(pickle_data_list[0])
            assert isinstance(pickle_data, TestClass)
            print(
                f"Received pickle data type: {type(pickle_data)}, attrs: name={pickle_data.name}, data={pickle_data.data}"
            )

        time.sleep(0.1)


if __name__ == "__main__":
    test_client()
