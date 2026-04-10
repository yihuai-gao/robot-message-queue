<!--
 Copyright (c) 2024 Yihuai Gao
 
 This software is released under the MIT License.
 https://opensource.org/licenses/MIT
-->

# Robot Message Queue (robotmq)

## TL;DR

`robotmq` is a lightweight, high-performance message queue for robotics Python programs. An independent C++ thread runs all message passing in background so your Python main thread never blocks.

**Install:**
```bash
pip install robotmq
```

**Key features:**
- ~2 GB/s local throughput via shared memory; ~20 MB/s over the network via ZeroMQ
- No message schema — any `bytes`-serializable data works (numpy arrays, dicts, etc.)
- Automatic message expiration prevents unbounded memory growth
- No dependency: self-contained in a single pip package

**Common use cases:**
- **Peripheral readout** (camera, spacemouse, etc.): run a dedicated reader process with an `RMQServer`, then `peek`/`pop` data from your main program via `RMQClient`.
- **Detached policy inference**: run your neural network on a GPU server with an `RMQServer`, send observations and receive actions from the robot controller via `RMQClient`.

---

## Table of Contents

- [Overview](#overview)
- [Motivation: Why robotmq?](#motivation-why-robotmq)
- [Architecture & Design Patterns](#architecture--design-patterns)
  - [Client-Server Model](#client-server-model)
  - [Dual Transport Layer](#dual-transport-layer)
  - [Topic-Based Message Routing](#topic-based-message-routing)
  - [Hybrid Communication Patterns](#hybrid-communication-patterns)
- [API Reference](#api-reference)
  - [RMQServer](#rmqserver)
  - [RMQClient](#rmqclient)
  - [Utility Functions](#utility-functions)
  - [RMQLogLevel](#rmqloglevel)
- [Usage Patterns](#usage-patterns)
  - [Asynchronous Data Streaming](#1-asynchronous-data-streaming-sensor-readout)
  - [Synchronous Request-Reply](#2-synchronous-request-reply-policy-inference)
  - [Mixed Mode](#3-mixed-mode)
- [Advantages Over Existing Methods](#advantages-over-existing-methods)
- [Performance Characteristics](#performance-characteristics)
- [Installation](#installation)
- [Troubleshooting](#troubleshooting)

---

## Overview

`robotmq` is a lightweight, high-performance message queue designed specifically for robotics applications in Python. It provides a C++ core (exposed via pybind11) that handles all message passing in background threads, allowing Python programs to exchange data asynchronously without blocking the main thread.

The library bridges two common robotics needs:
1. **Streaming sensor data** (cameras, force sensors, spacemouse) from producer processes to consumer processes.
2. **Offloading computation** (neural network inference, motion planning) to separate processes or remote machines.

---

## Motivation: Why robotmq?

Robotics Python programs frequently need to share data between processes — a camera reader feeding frames to a control loop, or a robot controller sending observations to a GPU server for policy inference. The existing solutions each have significant drawbacks:

| Method | Problem |
|---|---|
| **Python `multiprocessing.Queue`** | GIL contention, pickle overhead, no network support, no shared memory for large arrays |
| **ROS / ROS2** | Heavyweight dependency, rigid message types (`.msg` files), complex setup, overkill for simple data passing |
| **Raw ZeroMQ in Python** | Blocks the Python thread during send/recv, no built-in topic management or message expiration |
| **Redis / RabbitMQ** | External service dependency, serialization overhead, not optimized for large binary data (images, point clouds) |
| **Python `shared_memory`** | No built-in synchronization, no network fallback, manual lifecycle management |

`robotmq` solves these problems with a focused design:

- **C++ background threads** handle all network I/O — Python never blocks on send/recv.
- **Shared memory transport** for local communication achieves ~2 GB/s throughput for large numpy arrays.
- **ZeroMQ transport** for network communication provides ~20 MB/s across machines with zero configuration.
- **No message schema required** — any data that can be serialized to `bytes` works. The included `serialize()`/`deserialize()` utilities handle nested structures of numpy arrays without version conflicts.
- **Automatic message expiration** — old messages are discarded based on a configurable time window, preventing unbounded memory growth.
- **Minimal API surface** — two classes (`RMQServer`, `RMQClient`) and a handful of methods cover all use cases.

---

## Architecture & Design Patterns

### Client-Server Model

```
┌─────────────────────┐          ┌─────────────────────┐
│      RMQServer      │          │      RMQClient      │
│                     │          │                     │
│  ┌───────────────┐  │  ZeroMQ  │                     │
│  │ Background    │◄─┼──────────┼─── peek_data()      │
│  │ Thread        │──┼──────────┼──► returns data      │
│  │ (REP socket)  │  │  TCP/IPC │                     │
│  └───────┬───────┘  │          │                     │
│          │          │          │                     │
│  ┌───────▼───────┐  │          │                     │
│  │  DataTopic    │  │          │                     │
│  │  "sensor_A"   │  │          │                     │
│  ├───────────────┤  │          │                     │
│  │  DataTopic    │  │  Shared  │                     │
│  │  "camera"     │◄─┼─ Memory──┼─── (direct read)    │
│  ├───────────────┤  │          │                     │
│  │  DataTopic    │  │          │                     │
│  │  "inference"  │  │          │                     │
│  └───────────────┘  │          │                     │
└─────────────────────┘          └─────────────────────┘
```

The server owns all topics and data. It runs a **background thread** that listens for client requests on a ZeroMQ REP socket. The client sends requests on a REQ socket. This REQ-REP pattern ensures reliable, ordered communication.

Key design decisions:
- The server's background thread is a C++ `std::thread`, completely independent of Python's GIL. The GIL is only acquired briefly to check for Python signals (e.g., `KeyboardInterrupt`).
- Each topic is a `std::deque` of timestamped message pointers, providing O(1) push/pop from both ends.
- Thread safety is guaranteed by `std::mutex` locks on the topic map, request queue, and reply channel.

### Dual Transport Layer

`robotmq` supports two transport mechanisms per topic, chosen at topic creation time:

#### Regular Topics (ZeroMQ only)
```python
server.add_topic("sensor_data", message_remaining_time_s=10.0)
```
- Data is stored in the server process's heap memory.
- Clients receive data through the ZeroMQ REP-REQ channel.
- Suitable for small-to-medium messages or cross-network communication.

#### Shared Memory Topics (SHM + ZeroMQ)
```python
server.add_shared_memory_topic("camera_frames", message_remaining_time_s=5.0, shared_memory_size_gb=1.0)
```
- Data is stored in a **ring buffer** in `/dev/shm` (POSIX shared memory).
- The ZeroMQ channel only transfers metadata (offset, size) — the actual data is read directly from shared memory by the client.
- A `pthread_mutex` in shared memory provides cross-process synchronization.
- The ring buffer automatically wraps around, overwriting the oldest data when full.
- SHM path format: `rmq_{username}_{pid}_{server_name}_{topic_name}`

This dual approach lets you use the optimal transport per topic: shared memory for large, high-frequency local data (camera images, point clouds), and ZeroMQ for smaller data or cross-machine communication.

### Topic-Based Message Routing

Each topic is an independent message queue with:
- **Time-based expiration**: Messages older than `message_remaining_time_s` are automatically pruned on every insertion.
- **Flexible retrieval**: Clients can peek (non-destructive read) or pop (destructive read) messages with flexible indexing:
  - `n > 0`: First `n` messages (oldest first)
  - `n < 0`: Last `|n|` messages (most recent, preserving chronological order)
  - `n = 0`: All messages

This is purpose-built for robotics: a control loop typically wants the **latest** sensor reading (`n=-1`), while a logger might want **all** buffered readings (`n=0`).

### Hybrid Communication Patterns

A single server supports both patterns simultaneously:

1. **Publish-Subscribe (Asynchronous)**: Server calls `put_data()` to publish; clients call `peek_data()` or `pop_data()` to consume. No coordination needed — the server writes at its own rate, clients read at theirs.

2. **Request-Reply (Synchronous)**: Client calls `request_with_data()` to send a request and block until a reply arrives. Server calls `wait_for_request()` + `reply_request()` to handle it. Built-in **deduplication** prevents double-processing if the client retries on timeout.

---

## API Reference

### RMQServer

#### Constructor

```python
RMQServer(server_name: str, server_endpoint: str, log_level: RMQLogLevel = RMQLogLevel.INFO)
```

| Parameter | Description | Example |
|---|---|---|
| `server_name` | Unique name for this server instance (used in logging and SHM paths) | `"robot_server"` |
| `server_endpoint` | ZeroMQ endpoint to bind to | `"tcp://*:5555"` or `"ipc:///tmp/feeds/0"` |
| `log_level` | Logging verbosity | `RMQLogLevel.INFO` |

**Endpoint formats:**
- `tcp://*:PORT` — Listen on all interfaces (use for network communication)
- `tcp://0.0.0.0:PORT` — Same as above, explicit bind-all
- `ipc:///path/to/socket` — Unix domain socket (local only, lower latency than TCP)

#### Topic Management

```python
server.add_topic(topic: str, message_remaining_time_s: float) -> None
```
Creates a regular (ZeroMQ-only) topic. Messages older than `message_remaining_time_s` seconds are automatically discarded.

```python
server.add_shared_memory_topic(topic: str, message_remaining_time_s: float, shared_memory_size_gb: float) -> None
```
Creates a shared memory topic with a ring buffer of `shared_memory_size_gb` gigabytes. Large data is stored directly in `/dev/shm` for zero-copy local access.

#### Data Operations

```python
server.put_data(topic: str, data: bytes) -> None
```
Publishes data to a topic. The data is stored in the topic's queue and timestamped automatically. Expired messages are pruned on each insertion.

```python
server.peek_data(topic: str, n: int) -> tuple[list[bytes], list[float]]
```
Reads `n` messages from the topic **without removing them**. Returns a tuple of `(data_list, timestamp_list)`.

```python
server.pop_data(topic: str, n: int) -> tuple[list[bytes], list[float]]
```
Reads `n` messages from the topic **and removes them**. Same return format as `peek_data`.

**Indexing for `n`:**
| Value | Behavior |
|---|---|
| `n > 0` | First (oldest) `n` messages |
| `n < 0` | Last (newest) `\|n\|` messages, in chronological order |
| `n = 0` | All messages currently in the topic |

#### Request-Reply

```python
server.wait_for_request(timeout_s: float) -> tuple[bytes, str]
```
Blocks until a client sends a `request_with_data()` call, or until `timeout_s` elapses. Returns `(request_data, topic_name)`. If the timeout elapses, returns `(b"", "")`.

```python
server.reply_request(topic: str, data: bytes) -> None
```
Sends a reply back to the client that issued the request on the given topic. Must be called after `wait_for_request()` returns a valid request.

#### Status & Time

```python
server.get_all_topic_status() -> dict[str, int]
```
Returns a dictionary mapping topic names to their current message count.

```python
server.get_timestamp() -> float
```
Returns seconds elapsed since the server's internal clock started (the first message event). Useful for consistent timestamping across topics.

```python
server.reset_start_time(system_time_us: int) -> None
```
Resets the internal clock to align with a system timestamp. Pass `robotmq.system_clock_us()` to synchronize with wall-clock time.

---

### RMQClient

#### Constructor

```python
RMQClient(client_name: str, server_endpoint: str, log_level: RMQLogLevel = RMQLogLevel.INFO)
```

| Parameter | Description | Example |
|---|---|---|
| `client_name` | Unique name for this client instance (used in logging) | `"control_loop"` |
| `server_endpoint` | ZeroMQ endpoint to connect to (must match server) | `"tcp://192.168.1.10:5555"` |
| `log_level` | Logging verbosity | `RMQLogLevel.INFO` |

**Note:** For TCP, the client uses the server's IP address (not `*`). For IPC, the path must match exactly.

#### Data Retrieval

```python
client.peek_data(topic: str, n: int, timeout_s: float = 1.0, automatic_resend: bool = True) -> tuple[list[bytes], list[float]]
```
Reads `n` messages from the remote topic **without removing them**. The `n` parameter follows the same convention as the server (positive = oldest, negative = newest, zero = all).

```python
client.pop_data(topic: str, n: int, timeout_s: float = 1.0, automatic_resend: bool = True) -> tuple[list[bytes], list[float]]
```
Reads `n` messages and **removes them** from the server's topic.

```python
client.put_data(topic: str, data: bytes, timeout_s: float = 1.0, automatic_resend: bool = True) -> None
```
Sends data to a topic on the server. This allows clients to publish data to server-managed topics (useful for bidirectional communication).

| Parameter | Description |
|---|---|
| `timeout_s` | Seconds to wait for server response before retrying. Default: `1.0` |
| `automatic_resend` | If `True`, automatically retry on timeout (up to 800 retries). If `False`, raise an exception immediately on the first timeout. Default: `True` |

#### Request-Reply

```python
client.request_with_data(topic: str, data: bytes, timeout_s: float = 1.0, automatic_resend: bool = True) -> bytes
```
Sends `data` as a request to the server's `topic` and blocks until the server replies. The server must call `wait_for_request()` + `reply_request()` to handle it. Returns the reply data as `bytes`.

Built-in deduplication: if the client retries (due to timeout), the server recognizes the duplicate request by its timestamp and returns the cached reply without re-processing.

#### Connection Status

```python
client.get_topic_status(topic: str, timeout_s: float) -> int
```
Queries the server for the status of a topic. Unlike other client methods, `timeout_s` has **no default value** and must be provided explicitly. If `timeout_s` is negative, the call blocks indefinitely until the server responds.

This is the **only** client method that detects server disconnection via a return code (`-2`) rather than raising an exception. (Other client methods with `automatic_resend=False` raise an exception on timeout instead.)

| Return Value | Meaning |
|---|---|
| `-2` | Server unreachable (no reply within `timeout_s` seconds; never returned when `timeout_s < 0`) |
| `-1` | Server connected, but topic does not exist |
| `0` | Topic exists, but contains no messages |
| `> 0` | Number of messages currently in the topic |

#### Other

```python
client.get_last_retrieved_data() -> tuple[list[bytes], list[float]]
```
Returns the data from the most recent `peek_data`, `pop_data`, `put_data`, or `request_with_data` call. Useful for re-accessing the last result without another network round-trip.

```python
client.get_timestamp() -> float
```
Returns seconds elapsed since the client's internal clock started.

```python
client.reset_start_time(system_time_us: int) -> None
```
Synchronizes the client's internal clock with a system timestamp.

---

### Utility Functions

```python
from robotmq import serialize, deserialize          # top-level exports
from robotmq.utils import clear_shared_memory       # only available from robotmq.utils
```

#### `serialize(data: Any) -> bytes`

Recursively serializes arbitrarily nested structures (dicts, lists, tuples) containing numpy arrays and other picklable types. Numpy arrays are converted to `(raw_bytes, dtype_str, shape_tuple)` before pickling, which avoids numpy version incompatibilities between sender and receiver.

```python
data = {
    "image": np.random.rand(480, 640, 3),
    "joints": np.array([0.1, 0.2, 0.3]),
    "metadata": {"timestamp": 1234.5, "frame_id": 42}
}
payload = serialize(data)  # safe to send across numpy versions
```

#### `deserialize(data: bytes) -> Any`

Reverse of `serialize()`. Automatically detects and reconstructs numpy arrays from the `(bytes, dtype_str, shape)` representation. Returns `None` with a warning if given empty bytes.

```python
result = deserialize(payload)
# result["image"].shape == (480, 640, 3)
```

#### `clear_shared_memory()`

Removes all shared memory files in `/dev/shm` created by `robotmq` for the current user (files matching `rmq_{username}_*`). Call this to clean up leftover shared memory from crashed processes.

---

### RMQLogLevel

An enum controlling the verbosity of the C++ spdlog logger:

| Level | Description |
|---|---|
| `RMQLogLevel.TRACE` | Most verbose — all internal operations |
| `RMQLogLevel.DEBUG` | Debug-level details |
| `RMQLogLevel.INFO` | Normal operation messages (default) |
| `RMQLogLevel.WARNING` | Warnings only |
| `RMQLogLevel.ERROR` | Errors only |
| `RMQLogLevel.CRITICAL` | Critical errors only |
| `RMQLogLevel.OFF` | No logging |

### Clock Functions

```python
robotmq.steady_clock_us() -> int   # Monotonic clock in microseconds (for durations)
robotmq.system_clock_us() -> int   # Wall-clock time in microseconds (for synchronization)
```

---

## Usage Patterns

### 1. Asynchronous Data Streaming (Sensor Readout)

A producer process reads from a sensor and publishes data; a consumer process reads it at its own pace.

**Producer (Server):**
```python
import robotmq
from robotmq.utils import serialize
import numpy as np

server = robotmq.RMQServer("sensor_server", "tcp://*:5555")
server.add_shared_memory_topic("camera", message_remaining_time_s=5.0, shared_memory_size_gb=2.0)

while True:
    frame = capture_camera_frame()  # returns np.ndarray
    server.put_data("camera", serialize(frame))
```

**Consumer (Client):**
```python
import robotmq
from robotmq.utils import deserialize

client = robotmq.RMQClient("controller", "tcp://192.168.1.10:5555")

while True:
    # Get only the latest frame (n=-1), non-destructively
    data_list, timestamps = client.peek_data("camera", n=-1)
    if data_list:
        frame = deserialize(data_list[0])
        process(frame)
```

**Key points:**
- `peek_data` with `n=-1` always gets the most recent message — ideal for control loops that only care about the latest state.
- `pop_data` with `n=0` drains the queue — useful for loggers that need every message.
- The server and client can run at different rates. Old messages expire automatically.

### 2. Synchronous Request-Reply (Policy Inference)

A robot controller sends observations to a GPU server and receives actions back.

**GPU Server:**
```python
import robotmq
from robotmq.utils import serialize, deserialize

server = robotmq.RMQServer("policy_server", "tcp://*:5555")
server.add_shared_memory_topic("inference", message_remaining_time_s=10.0, shared_memory_size_gb=1.0)

model = load_policy_model()

while True:
    request_data, topic = server.wait_for_request(timeout_s=1.0)
    if not topic:  # timeout
        continue
    
    observation = deserialize(request_data)
    action = model.predict(observation)
    server.reply_request(topic, serialize(action))
```

**Robot Controller (Client):**
```python
import robotmq
from robotmq.utils import serialize, deserialize

client = robotmq.RMQClient("robot", "tcp://gpu-server:5555")

while True:
    obs = get_robot_observation()
    action_bytes = client.request_with_data("inference", serialize(obs), timeout_s=5.0)
    action = deserialize(action_bytes)
    execute_action(action)
```

**Key points:**
- `request_with_data` blocks until the server replies — simple synchronous RPC semantics.
- Built-in retry and deduplication: if the client times out and retries, the server won't re-run inference; it returns the cached result.
- Works over the network — run the policy on a GPU server and the robot controller on an edge device.

### 3. Mixed Mode

A single server can handle both asynchronous data streams and synchronous requests simultaneously. This is useful when a robot controller needs to both stream sensor data and handle inference requests.

```python
server = robotmq.RMQServer("robot_server", "tcp://*:5555")
server.add_topic("joint_states", message_remaining_time_s=10.0)
server.add_shared_memory_topic("inference", message_remaining_time_s=5.0, shared_memory_size_gb=1.0)

# In the main loop:
# 1. Publish sensor data asynchronously
server.put_data("joint_states", serialize(joint_positions))

# 2. Handle inference requests synchronously
request_data, topic = server.wait_for_request(timeout_s=0.01)
if topic:
    result = process_request(deserialize(request_data))
    server.reply_request(topic, serialize(result))
```

---

## Advantages Over Existing Methods

### vs. ROS / ROS2

| Aspect | ROS2 | robotmq |
|---|---|---|
| **Setup** | Requires ROS installation, workspace, package structure, CMake/colcon build | `pip install robotmq` |
| **Message types** | Must define `.msg` files, generate code, rebuild | Any picklable Python object works |
| **Cross-version** | Strict version matching between nodes | Server and client can use different Python versions and different numpy versions |
| **Shared memory** | Available in ROS2 (Humble+), but requires DDS configuration | Built-in, one-line `add_shared_memory_topic()` |
| **Learning curve** | Steep — publishers, subscribers, executors, QoS profiles, launch files | Two classes, ~5 methods total |
| **Dependency weight** | Gigabytes of packages | Single pip package, ~few MB |

**When to use ROS2 instead:** If you need a full robotics middleware (TF transforms, parameter server, lifecycle management, multi-language support, standardized message types for interoperability).

### vs. Python `multiprocessing.Queue` / `shared_memory`

| Aspect | multiprocessing | robotmq |
|---|---|---|
| **GIL** | Queue operations acquire the GIL | C++ background thread, GIL-free |
| **Network** | Local only | TCP support for cross-machine communication |
| **Message expiration** | Manual management | Automatic time-based expiration |
| **Peek semantics** | Not supported (get is destructive) | Both peek (non-destructive) and pop (destructive) |
| **Large arrays** | Pickle serialization overhead | Shared memory ring buffer, ~2 GB/s |

### vs. Raw ZeroMQ (pyzmq)

| Aspect | pyzmq | robotmq |
|---|---|---|
| **Blocking** | `recv()` blocks the Python thread | Background C++ thread, non-blocking Python |
| **Topic management** | Manual implementation | Built-in topics with expiration and indexing |
| **Shared memory** | Not included | Integrated SHM ring buffer |
| **Request deduplication** | Manual implementation | Built-in for request-reply pattern |
| **Serialization** | BYO | Included numpy-safe `serialize()`/`deserialize()` |

### vs. Redis / RabbitMQ

| Aspect | Redis/RabbitMQ | robotmq |
|---|---|---|
| **Deployment** | External service to install and maintain | Embedded in your Python process |
| **Large binary data** | Not optimized (base64 encoding, size limits) | Native bytes, shared memory for large payloads |
| **Latency** | Extra network hop to broker | Direct peer-to-peer (or shared memory) |
| **Dependencies** | Server process + client library | Single pip package |

### Summary of Unique Advantages

1. **Zero-GIL data path**: All I/O happens in C++ threads. Python never blocks on network operations.
2. **Adaptive transport**: Choose shared memory (~2 GB/s) or TCP (~20 MB/s) per topic based on data size and network topology.
3. **Robotics-native indexing**: `n=-1` for "latest only", `n=0` for "drain all" — matches how control loops and loggers actually consume data.
4. **Automatic message expiration**: No unbounded memory growth. Set a time window and forget about it.
5. **Cross-environment compatibility**: Server and client can run in different Python environments, different Python versions, and different numpy versions without serialization errors.
6. **Minimal API**: Two classes, ~10 methods. No schema definitions, no build systems, no broker processes.
7. **Request-reply with deduplication**: Synchronous RPC semantics with built-in retry safety — critical for robot control where double-executing an action is dangerous.

---

## Performance Characteristics

| Scenario | Throughput | Notes |
|---|---|---|
| Shared memory, large arrays (76 MB) | ~2 GB/s | Ring buffer in `/dev/shm`, mutex-protected |
| TCP, local loopback | ~500 MB/s | Depends on message size |
| TCP, across network | ~20 MB/s | Limited by network bandwidth |
| Message serialization (numpy) | ~1 GB/s | `tobytes()` is near-memcpy speed |
| `serialize()`/`deserialize()` | Slightly slower | Adds pickle overhead for structure metadata |

**Memory usage:**
- Regular topics: Messages stored in server process heap. Bounded by `message_remaining_time_s` × publish rate × message size.
- Shared memory topics: Fixed allocation of `shared_memory_size_gb` in `/dev/shm`. Ring buffer reclaims space automatically.

---

## Installation

### From PyPI (recommended)

Prebuilt wheels for Linux x86_64 and aarch64:

```bash
pip install robotmq
```

### From Source

```bash
# Using conda (recommended for C++ dependencies)
conda install spdlog cppzmq zeromq boost pybind11 cmake make gxx_linux-64 -y

# Install in development mode
pip install -e .

# Or install as a regular package
pip install .
```

**Build dependencies:** C++17 compiler, CMake, ZeroMQ, cppzmq, spdlog, Boost, pybind11, fmt.

---

## Troubleshooting

### Numpy version errors

If you see errors related to `numpy._core` when exchanging data between processes with different numpy versions, use `serialize()` / `deserialize()` instead of `pickle.dumps()` / `pickle.loads()`. These can be imported directly from `robotmq` (`from robotmq import serialize, deserialize`). They convert numpy arrays to raw bytes with dtype metadata, avoiding version-specific pickle representations.

### Stale shared memory

If a server process crashes, shared memory files may remain in `/dev/shm`. Clean them up with:

```python
from robotmq.utils import clear_shared_memory
clear_shared_memory()
```

Or manually: `rm /dev/shm/rmq_${USER}_*`

### "Too many open files" error

`get_topic_status()` closes and recreates the ZeroMQ socket each time the server is unreachable. Due to file descriptors not being released immediately, calling it repeatedly without a server response can eventually hit the OS file descriptor limit (~1024). Avoid polling `get_topic_status()` in a tight loop — add a sleep or use it only for initial connection checks.

### Server not responding to clients

If you're using mixed mode (both async put/peek and sync request-reply), be aware that the server's background thread handles requests sequentially. If `wait_for_request()` is blocking for a long timeout, other clients may experience delays. Use short timeouts in mixed-mode servers.

### Cross-machine connection via SSH tunnel

If the server's port is firewalled, forward it through SSH:

```bash
ssh -L 5555:server_ip:5555 user@server_ip
```

Then connect the client to `tcp://localhost:5555`.
