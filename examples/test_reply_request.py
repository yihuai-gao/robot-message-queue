import robotmq
import numpy as np
import numpy.typing as npt

def test_reply_request():
    server = robotmq.RMQServer("test_server", "tcp://*:5555")
    server.add_topic("test_topic", 10.0)
    while True:
        try:
            request_data, request_timestamps = server.wait_for_request("test_topic", 1.0)
            for raw_data in request_data:
                data = np.frombuffer(raw_data, dtype=np.float64).copy()
                data += 1.0
                server.reply_request("test_topic", [data.tobytes()])
        except KeyboardInterrupt:
            break
        
    
if __name__ == "__main__":
    test_reply_request()

