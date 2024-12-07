"""
 Copyright (c) 2024 Yihuai Gao
 
 This software is released under the MIT License.
 https://opensource.org/licenses/MIT
"""

from difflib import restore
import robotmq as rmq
import time
import pickle
import numpy as np
import numpy.typing as npt
import psutil


def get_memory_usage():
    process = psutil.Process()  # Get the current process
    memory_info = process.memory_info()  # Fetch memory usage details
    return memory_info.rss / 1024.0 / 1024.0  # Convert bytes to MB


def test_timestamps():
    server = rmq.RMQServer("test_rmq_server", "ipc:///tmp/feeds/0")
    client = rmq.RMQClient("test_rmq_client", "ipc:///tmp/feeds/0")
    print("Server and client created")

    topic_name = "test"
    server.add_topic(topic_name, 1.0)

    current_system_time = rmq.system_clock_us()

    # Manually sync the start time of the server and client
    server.reset_start_time(current_system_time)
    client.reset_start_time(current_system_time)

    for i in range(100):
        rand_data = np.random.rand(1000000)
        data_bytes = pickle.dumps(rand_data)
        server.put_data(topic_name, data_bytes)
        # Because of the shared_ptr, the data is stored in the server even if it is dereferenced in python
        del data_bytes
        data, timestamp = server.peek_data(
            topic_name, "latest", -1
        )  # only pass the reference so will take zero time
        print(
            f"Adding data: {i}, data size: {rand_data.nbytes / 1024**2:.3f}MB, stored data size: {len(data)}, memory usage: {get_memory_usage():.3f}MB"
        )
        time.sleep(0.01)
        del data

    for i in range(30):
        raw_data, timestamp = server.pop_data(topic_name, "latest", 1)
        if len(raw_data) == 0:
            print("No data left")
            break
        # restored_data: npt.NDArray[np.float64] = pickle.loads(raw_data[0])
        print(f"Poping latest data: {i}, memory usage: {get_memory_usage():.3f}MB")
        time.sleep(0.01)

    data, timestamp = server.pop_data(topic_name, "latest", -1)
    data_len = len(data)
    del data
    print(f"{data_len=}, memory usage: {get_memory_usage():.3f}MB")

    topics = server.get_topic_status()
    print(f"Topic status after popping: {topics}")


if __name__ == "__main__":
    test_timestamps()
