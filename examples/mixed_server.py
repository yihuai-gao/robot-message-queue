"""
 Copyright (c) 2024 Yihuai Gao
 
 This software is released under the MIT License.
 https://opensource.org/licenses/MIT
"""

from robotmq import RMQServer
import time
import numpy as np
import numpy.typing as npt

from robotmq.utils import deserialize_numpy, serialize_numpy
import pickle


def test_mixed_server():
    """
    Simulate the policy evaluation process
    """
    server = RMQServer("mixed_server", "tcp://0.0.0.0:5555")
    print("Server created")

    server.add_topic("policy_inference", 10)  # Used as synchronous topic
    server.add_topic("result", 10)  # Used as asynchronous topic
    server.add_topic("ckpt_name", 10)  # Used as asynchronous topic

    ckpt_name = ""
    while True:
        try:
            ckpt_name_list, _ = server.pop_data("ckpt_name", "latest", 1)
            if ckpt_name_list:
                ckpt_name = deserialize_numpy(ckpt_name_list[0])
                assert isinstance(ckpt_name, str)
                print(f"Received ckpt_name: {ckpt_name}")
                # Simulate loading ckpt
            if not ckpt_name:
                time.sleep(1)
                print("No ckpt_name received")
                continue

            request_data, request_topic = server.wait_for_request(1.0)
            if request_topic:
                obs_data = deserialize_numpy(request_data)
                # Simulate policy inference
                action = {
                    "action": np.random.randn(10),
                    "ckpt_name": ckpt_name,
                }
                result_data = serialize_numpy(action)
                server.reply_request(request_topic, result_data)

            # result_data_list, _ = server.peek_data("result", "latest", 1)
            # if result_data_list:
            #     result = deserialize_numpy(result_data_list[0])
            #     print(f"Received result: {result}")

        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    test_mixed_server()
