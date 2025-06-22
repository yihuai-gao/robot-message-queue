"""
 Copyright (c) 2024 Yihuai Gao
 
 This software is released under the MIT License.
 https://opensource.org/licenses/MIT
"""

import robotmq
import numpy as np
import numpy.typing as npt
from robotmq.utils import serialize, deserialize
import time
def test_reply_request():
    server = robotmq.RMQServer("test_server", "tcp://*:5555")
    server.add_topic("test_topic", 10.0)
    while True:
        try:
            print("Waiting for request")
            request_data, request_topic = server.wait_for_request(1.0)
            if not request_topic:
                continue

            data = deserialize(request_data)
            assert isinstance(data, np.ndarray)
            print(data)
            data += 1.0
            data_bytes = serialize(data)
            # server.reply_request(request_topic, [data_bytes])
            server.reply_request("test_topic", data_bytes)
            print("Replied to request")
        except KeyboardInterrupt:
            break
        
    
if __name__ == "__main__":
    test_reply_request()

