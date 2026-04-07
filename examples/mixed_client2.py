"""
Copyright (c) 2024 Yihuai Gao

This software is released under the MIT License.
https://opensource.org/licenses/MIT
"""

from robotmq import RMQClient, serialize, deserialize
import time
import numpy as np


def test_mixed_client2():
    """
    Simulate the policy training process
    """
    client = RMQClient("mixed_client2", "tcp://localhost:5555")
    print("Client created")

    while True:
        while True:
            status = client.get_topic_status("ckpt_name", 0.5)
            if status == -2:
                print("Server cannot be connected after 0.5 seconds")
            elif status == -1:
                print("Topic does not exist")
            elif status >= 0:
                break
            time.sleep(1)
        ckpt_name = f"ckpt_{np.random.randint(0, 10)}"
        ckpt_name_bytes = serialize(ckpt_name)
        start_time = time.time()
        client.put_data("ckpt_name", ckpt_name_bytes)
        print(f"Put ckpt_name: {ckpt_name}, time spent: {time.time() - start_time}")

        start_time = time.time()
        result_data_list, _ = client.pop_data("result", 0)
        if result_data_list:
            for result_data in result_data_list:
                result = deserialize(result_data)
                print(f"Received result: {result}")

        time.sleep(1)


if __name__ == "__main__":
    test_mixed_client2()
