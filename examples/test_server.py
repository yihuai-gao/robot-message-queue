from pyrmq import RMQServer
import time
import numpy as np
import numpy.typing as npt


def test_server():
    server = RMQServer("test_rmq_server", "tcp://0.0.0.0:5555")
    print("Server created")

    server.add_topic("test", 10)

    data_cnt = 0
    while True:
        rand_data = np.random.rand(100000)
        # Simulates a data source that keeps getting data from the sensor at a regular interval
        server.put_data("test", rand_data.tobytes())
        time.sleep(0.1)
        data_cnt += 1
        topic_len = server.get_topic_status()["test"]
        print(
            f"Data cnt: {data_cnt} data size: {rand_data.nbytes / 1024**2:.3f}MB, topic size: {topic_len}"
        )


if __name__ == "__main__":
    test_server()
