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
    input_data = serialize(np.array([1, 2, 3], dtype=np.float64))
    start_time = time.time()
    reply = client.request_with_data("test_topic", input_data)
    print(f"Request with data time spent: {time.time() - start_time}")

    reply = deserialize(reply)
    print(reply)

if __name__ == "__main__":
    test_request_with_data()
    
