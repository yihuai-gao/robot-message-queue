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
    Simulate an simulation environment
    """

    client = RMQClient("mixed_client1", "tcp://localhost:5555")
    print("Client created")

    while True:
        while True:
            status = client.get_topic_status("policy_inference", 0.1)
            if status == -2:
                print("Server does not exist")
            elif status == -1:
                print("Topic does not exist")
            elif status >= 0:
                break
            time.sleep(1)
        obs_data = {
            "obs": np.random.randn(10),
        }
        obs_data_bytes = serialize_numpy(obs_data)
        start_time = time.time()
        action_data = client.request_with_data("policy_inference", obs_data_bytes)
        if action_data:
            action_data = deserialize_numpy(action_data)
            assert isinstance(action_data, dict)
            print(
                f"Received action, shape: {action_data['action'].shape}, time spent: {time.time() - start_time}"
            )

            # Simulate env rollout
            time.sleep(0.2)
            result_data = {
                "ckpt_name": action_data["ckpt_name"],
                "result": np.random.randn(1),
            }
            result_data_bytes = serialize_numpy(result_data)
            start_time = time.time()
            client.put_data("result", result_data_bytes)
            print(f"Put result, time spent: {time.time() - start_time}")
        else:
            time.sleep(1)


if __name__ == "__main__":
    test_mixed_client1()
