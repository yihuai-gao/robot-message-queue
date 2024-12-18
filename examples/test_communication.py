"""
 Copyright (c) 2024 Yihuai Gao
 
 This software is released under the MIT License.
 https://opensource.org/licenses/MIT
"""

import robotmq as rmq
import pickle
import time
import numpy as np
import numpy.typing as npt


def test_communication():
    server = rmq.RMQServer(
        server_name="test_rmq_server", server_endpoint="ipc:///tmp/feeds/0"
    )
    client = rmq.RMQClient(
        client_name="test_rmq_client", server_endpoint="ipc:///tmp/feeds/0"
    )
    print("Server and client created")

    server.add_topic("test", 10)
    rand_data_list: list[npt.NDArray[np.float64]] = []
    for k in range(10):
        rand_data = np.random.rand(1000000).astype(np.float64)
        rand_data_list.append(rand_data)
        start_time = time.time()
        # Using pickle also works, especially for arbitrary python objects
        # pickle_data = pickle.dumps(rand_data)
        dump_end_time = time.time()
        server.put_data("test", rand_data.tobytes())
        send_end_time = time.time()
        time.sleep(0.01)
        retrieve_start_time = time.time()
        retrieved_data, timestamp = client.peek_data(topic="test", order="latest", n=1)
        retrieve_end_time = time.time()
        received_data = np.frombuffer(retrieved_data[0], dtype=np.float64)
        # received_data = pickle.loads(retrieved_data[0])
        print(
            f"Data size: {rand_data.nbytes / 1024**2:.3f}MB. dump: {dump_end_time - start_time:.4f}s, send: {send_end_time - dump_end_time: .4f}s, retrieve: {retrieve_end_time - retrieve_start_time:.4f}s, load: {time.time() - retrieve_end_time:.4f}s, correctness: {np.allclose(received_data, rand_data)}"
        )

    start_time = time.time()
    all_pickle_data, all_timestamps = client.peek_data(
        topic="test", order="earliest", n=-1
    )
    request_end_time = time.time()
    # all_data = [pickle.loads(data) for data in all_pickle_data]
    all_data = [np.frombuffer(data, dtype=np.float64) for data in all_pickle_data]
    loads_end_time = time.time()
    correctness = [np.allclose(a, b) for a, b in zip(all_data, rand_data_list)]
    print(
        f"Request all data. Time: {request_end_time - start_time:.4f}s, load time: {loads_end_time - request_end_time: .4f}, correctness: {np.all(correctness)}"
    )

    start_time = time.time()
    last_k_pickle_data, last_k_timestamps = client.peek_data(
        topic="test", order="latest", n=5
    )
    request_end_time = time.time()
    # last_k_data = [pickle.loads(data) for data in last_k_pickle_data]
    last_k_data = [np.frombuffer(data, dtype=np.float64) for data in last_k_pickle_data]
    loads_end_time = time.time()
    correctness = [
        np.allclose(a, b)
        for a, b in zip(last_k_data, rand_data_list[-1:-6:-1])  # reverse order
    ]
    print(
        f"Request last 5 data. Time: {request_end_time - start_time:.4f}s, load time: {loads_end_time - request_end_time: .4f}, correctness: {np.all(correctness)}"
    )


if __name__ == "__main__":
    test_communication()
