<!--
 Copyright (c) 2024 Yihuai Gao
 
 This software is released under the MIT License.
 https://opensource.org/licenses/MIT
-->


# Robot Message Queue

## Features

- C++ multi-threading supports fully asynchronous data manipulation without taking up Python main thread
- ZMQ as the communication backend, supports both tcp and ipc (inter-process communication), ~200 MB/s locally and ~20 MB/s over the network
- No restriction to data type, as long as it can be serialized to bytes (numpy arrays `tobytes()` or `pickle.dumps()` for arbitrary data)
- Python bindings with minimal data transfer overhead (only copy once before sending and receiving)
- TODO: for the same physical machine, implement shared memory for faster communication

## Use Cases

- Peripheral readout (camera, keyboard, spacemouse, etc.): Run a separate python program to read out sensor data in a close loop, then initialize a robotmq server and put these data into the server. In your main python program, initialize a robotmq client to asynchronously query these data (`pop/peek` `arbitrary number` of the `earliest/latest` data messages). See this [repo](https://github.com/yihuai-gao/teleop-utils) for examples.
- Detached policy inference: Run your robot policy in a separate python program (remotely in a server), initialize a robotmq server in this program and run `wait_for_request` to wait for the request from the main program. In the main program, initialize a robotmq client to send the request (usually observations) and get the response (actions). Note that some server may firewall the port, in this case you can use `ssh -L local_port:server_ip:server_port user@server_ip` to forward the port through an ssh connection.

## Installation

```bash
# It is recommended to install all C++ dependencies into your conda environment
conda install spdlog cppzmq zeromq boost -y
# Alternatively, if you are not using conda, you can install the dependencies using sudo (not recommended)
# sudo apt install spdlog cppzmq zeromq5-dev libboost-all-dev -y

# Install the robotmq package
pip install robotmq
```

## Examples

```bash
pip install robotmq[examples]
python examples/test_communication.py

# Run the server and client in different terminals

# Asynchronous communication
python examples/asynchronous_server.py # in terminal A
python examples/asynchronous_client.py # in terminal B

# Synchronous communication
python examples/syncronous_server.py # in terminal A
python examples/syncronous_client.py # in terminal B
```
