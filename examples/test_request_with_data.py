import robotmq
import numpy as np
import numpy.typing as npt
import time

def test_request_with_data():
    client = robotmq.RMQClient("test_client", "tcp://localhost:5555")
    input_data = [np.array([1, 2, 3], dtype=np.float64).tobytes()]
    start_time = time.time()
    replies, timestamps = client.request_with_data("test_topic", input_data)
    print(f"Request with data time spent: {time.time() - start_time}")

    for raw_reply in replies:
        reply = np.frombuffer(raw_reply, dtype=np.float64)
        print(reply)

if __name__ == "__main__":
    test_request_with_data()
    
