"""
 Copyright (c) 2024 Yihuai Gao
 
 This software is released under the MIT License.
 https://opensource.org/licenses/MIT
"""

from robotmq import RMQServer
import time
import numpy as np
import numpy.typing as npt

from robotmq.core.robotmq_core import RMQClient
from robotmq.utils import deserialize_numpy, serialize_numpy
import pickle


def test_mixed_client1():
    """
    Simulate the policy training process
    """
    client = RMQClient("mixed_client2", "tcp://localhost:5555")
    print("Client created")

    while True:
        while True:
            status = client.get_topic_status("ckpt_name", 0.1)
            if status == -2:
                print("Server does not exist")
            elif status == -1:
                print("Topic does not exist")
            elif status >= 0:
                break
            time.sleep(1)
        ckpt_name = f"ckpt_{np.random.randint(0, 10)}"
        ckpt_name_bytes = serialize_numpy(ckpt_name)
        client.put_data("ckpt_name", ckpt_name_bytes)
        print(f"Put ckpt_name: {ckpt_name}")

        result_data_list, _ = client.pop_data("result", "latest", -1)
        if result_data_list:
            for result_data in result_data_list:
                result = deserialize_numpy(result_data)
                print(f"Received result: {result}")

        time.sleep(1)


if __name__ == "__main__":
    test_mixed_client1()
