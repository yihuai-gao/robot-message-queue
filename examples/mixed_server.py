"""
Copyright (c) 2024 Yihuai Gao

This software is released under the MIT License.
https://opensource.org/licenses/MIT
"""

from robotmq import RMQServer
import time
import numpy as np
import numpy.typing as npt

from robotmq.utils import deserialize, serialize
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
            ckpt_name_list, _ = server.pop_data("ckpt_name", -1)
            if ckpt_name_list:
                ckpt_name = deserialize(ckpt_name_list[0])
                assert isinstance(ckpt_name, str)
                print(f"Received ckpt_name: {ckpt_name}")
                # Simulate loading ckpt

            print("Waiting for request")
            request_data, request_topic = server.wait_for_request(1.0)
            print(f"Received request: {request_topic}")
            if request_topic:
                obs_data = deserialize(request_data)
                if ckpt_name:
                    # Simulate policy inference
                    time.sleep(0.2)
                    action = {
                        "action": np.random.randn(10),
                        "ckpt_name": ckpt_name,
                    }
                    result_data = serialize(action)
                else:
                    result_data = serialize("No ckpt provided")
                server.reply_request(request_topic, result_data)

        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    test_mixed_server()
