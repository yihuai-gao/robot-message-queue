<!--
 Copyright (c) 2024 Yihuai Gao
 
 This software is released under the MIT License.
 https://opensource.org/licenses/MIT
-->


# Robot Message Queue

## Features

- C++ multi-threading supports fully asynchronous data manipulation without taking up Python main thread
- ZMQ as the communication backend, supports both tcp and ipc (inter-process communication), ~200 MB/s locally and ~20 MB/s over the network
- No restriction to data type, as long as it can be serialized to bytes (`pickle.dumps()` for arbitrary data or `robotmq.utils.serialize()` for nested list/dict/tuple of numpy arrays)
- TODO: for the same physical machine, implement shared memory for faster communication

## Use Cases

- Peripheral readout (camera, keyboard, spacemouse, etc.): Run a separate python program to read out sensor data in a close loop, then initialize a robotmq server and put these data into the server. In your main python program, initialize a robotmq client to asynchronously query these data (`pop/peek` `arbitrary number` of the `earliest/latest` data messages). See this [repo](https://github.com/yihuai-gao/teleop-utils) for examples.
- Detached policy inference: Run your robot policy in a separate python program (remotely in a server), initialize a robotmq server in this program and run `wait_for_request` to wait for the request from the main program. In the main program, initialize a robotmq client to send the request (usually observations) and get the response (actions). Note that some server may firewall the port, in this case you can use `ssh -L local_port:server_ip:server_port user@server_ip` to forward the port through an ssh connection.

## Installation

The prebuilt wheels for Linux x86_64 are available on [pypi](https://pypi.org/project/robotmq/).

```bash
pip install robotmq
```

If you want to run this library on other platforms, you can clone this repository and build from scratch:

```bash
# It is recommended to install all C++ dependencies into your conda environment
conda install spdlog cppzmq zeromq boost pybind11 cmake make gxx_linux-64 -y
# Alternatively, if you are not using conda, you can install the dependencies using sudo (not recommended)
# sudo apt install spdlog cppzmq zeromq5-dev libboost-all-dev -y

# Install the robotmq package (both ways should work if you want to import this package in other directories)
# If you want to install the package inplace in an editable manner
pip install -e .
# If you want to make a copy and then install (the output path will usually be build/lib.linux-x86_64-cpython-310/robotmq/core)
pip install .
```

## Examples

You can run the server and client in **different Python environments**, even in different **Python versions**.

```bash
# If you are not installing the prebuild wheels, it is required to install the package in an editable way (with -e option).
# Otherwise python interpreter will only check robotmq/core and cannot find the compiled .so file
# pip install -e .
python examples/test_communication.py

# Run the server and client in different terminals

# Asynchronous communication
python examples/asynchronous_server.py # in terminal A
python examples/asynchronous_client.py # in terminal B

# Synchronous communication
python examples/syncronous_server.py # in terminal A
python examples/syncronous_client.py # in terminal B

# Mixed communication (One clinet may not connect to the server if the server is not responding to synchronous request from another client.)
python examples/mixed_server.py # in terminal A
python examples/mixed_client1.py # in terminal B
python examples/mixed_client2.py # in terminal C
```

## Troubleshooting
- If you encounter numpy errors (related to `numpy._core`), this usually happens if you call `pickle.dumps()` and `pickle.loads()` to a struct containing numpy arrays, and you have different numpy versions in the server and client python environments. To handle this, instead of using `pickle.dumps()`, you can call `robotmq.utils.serialize()` to serialize any nested (arbitrarily deep) list/dict/tuple of numpy arrays or other regular types (int/float/str/bytes). This function will use the `tobytes()` method of numpy arrays, thus will not lead any numpy version problems.

- `get_topic_status` is the only client function that support disconnection detection. For all the other client functions, if the server is not created, the client will be blocked forever. However, one should not call `get_topic_status` too frequently, as it will close and recreate a socket connection every time if the server is not responding. Due to some unknown issues, the files descriptor of the socket is not properly released. Therefore, if you call `get_topic_status` and get no response for more than 1024 times, it will throw an error `Too many open files`.
