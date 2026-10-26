"""
Copyright (c) 2024 Yihuai Gao

This software is released under the MIT License.
https://opensource.org/licenses/MIT
"""

def steady_clock_us() -> int: ...
def system_clock_us() -> int: ...

class RMQLogLevel:
    TRACE: "RMQLogLevel"
    DEBUG: "RMQLogLevel"
    INFO: "RMQLogLevel"
    WARNING: "RMQLogLevel"
    ERROR: "RMQLogLevel"
    CRITICAL: "RMQLogLevel"
    OFF: "RMQLogLevel"

class RMQServer:
    def __init__(
        self,
        server_name: str,
        server_endpoint: str,
        log_level: RMQLogLevel = RMQLogLevel.INFO,
        allowed_ips: list[str] = [],
    ) -> None:
        """Create a message-queue server.

        Args:
            server_name: Human-readable name used for logging.
            server_endpoint: ZMQ endpoint to bind, e.g. ``tcp://*:5555`` or ``ipc:///tmp/rmq``.
            log_level: Logging verbosity.
            allowed_ips: Optional whitelist of client addresses. Each entry is an IPv4 address
                (``"192.168.1.10"``) or an IPv4 CIDR network (``"192.168.1.0/24"``). When empty
                (the default) every peer is served. When non-empty, only requests whose source IP
                matches an entry are processed; others receive an error reply. Only applies to
                ``tcp://`` endpoints (``ipc://`` peers have no IP and are local-only, so the
                whitelist is ignored with a warning). Malformed entries — including IPv6 entries
                (the socket is IPv4-only, so they could never match a peer) and CIDR networks
                with host bits set, e.g. ``192.168.1.5/24`` — raise ``ValueError``.
        """
        ...
    def add_topic(self, topic: str, message_remaining_time_s: float) -> None: ...
    def add_shared_memory_topic(
        self, topic: str, message_remaining_time_s: float, shared_memory_size_gb: float
    ) -> None:
        """Add a topic whose data and replies travel through a ``/dev/shm`` segment of ``shared_memory_size_gb``.

        Only clients that share ``/dev/shm`` with the server (the same host and IPC namespace, with permission to
        open the segments) can use it; ``RMQClient.check_shared_memory`` tells a client so before its first request.
        A request whose segment the server cannot read is answered with an error at once, and the server keeps
        serving. Data larger than the whole segment is refused: ``put_data`` and ``reply_request`` raise
        ``ValueError`` and store nothing, and a client waiting for that reply gets an error reply (``RuntimeError``)
        at once.
        """
        ...
    def put_data(self, topic: str, data: bytes) -> None:
        """Store ``data`` in ``topic``, timestamped now.

        Raises ``ValueError`` for empty data, and on a shared memory topic for data larger than the whole segment
        (nothing is stored).
        """
        ...
    def peek_data(self, topic: str, n: int) -> tuple[list[bytes], list[float]]:
        """Peek at data from a specified topic without removing it.

        Args:
            topic: The topic name to peek data from
            n: Number of data items to peek. If n < 0, will peek data from from the latest position (still remaining the order)
                If n = 0, will peek all data in the topic

        Returns:
            tuple[list[bytes], list[float]]: A tuple containing:
                - list[bytes]: The data items
                - list[float]: Corresponding timestamps
        """
        ...

    def pop_data(self, topic: str, n: int) -> tuple[list[bytes], list[float]]:
        """Pop data from a specified topic.

        Args:
            topic: The topic name to pop data from
            n: Number of data items to pop. If n < 0, will pop data from from the latest position (still remaining the order)
                If n = 0, will pop all data in the topic

        Returns:
            tuple[list[bytes], list[float]]: A tuple containing:
                - list[bytes]: The data items
                - list[float]: Corresponding timestamps
        """
        ...

    def get_all_topic_status(self) -> dict[str, int]: ...
    def get_timestamp(self) -> float: ...
    def reset_start_time(self, system_time_us: int) -> None: ...
    def wait_for_request(self, timeout_s: float) -> tuple[bytes, str]: ...
    def reply_request(self, topic: str, data: bytes) -> None:
        """Answer the request that ``wait_for_request`` returned for ``topic`` with ``data``.

        Raises ``ValueError`` like ``put_data`` when the reply cannot be stored (empty, or larger than a shared
        memory topic's segment); the client then receives an error reply at once instead of waiting for a timeout.
        """
        ...

class RMQClient:
    def __init__(self, client_name: str, server_endpoint: str, log_level: RMQLogLevel=RMQLogLevel.INFO) -> None: ...
    def get_topic_status(self, topic: str, timeout_s: float) -> int:
        """
        Get the status of a specified topic.

        Args:
            topic: The topic name to get status from
            timeout_s: Timeout in seconds. If negative, will wait forever.

        Returns:
            int: The status of the topic
                -2 if the server cannot be connected after timeout_s seconds
                -1 if the topic does not exist
                0 if the topic exists but has no data
                positive number means the number of data in the topic
        """
        ...

    def peek_data(self, topic: str, n: int, timeout_s: float = 1.0, automatic_resend: bool = True) -> tuple[list[bytes], list[float]]:
        """Peek at data from a specified topic without removing it.

        Args:
            topic: The topic name to peek data from
            n: Number of data items to peek. If n < 0, will peek data from from the latest position (still remaining the order)
                If n = 0, will peek all data in the topic

        Returns:
            tuple[list[bytes], list[float]]: A tuple containing:
                    - list[bytes]: The data items
                    - list[float]: Corresponding timestamps
        """
        ...

    def pop_data(self, topic: str, n: int, timeout_s: float = 1.0, automatic_resend: bool = True) -> tuple[list[bytes], list[float]]:
        """Pop data from a specified topic.

        Args:
            topic: The topic name to pop data from
            n: Number of data items to pop. If n < 0, will pop data from from the latest position (still remaining the order)
                If n = 0, will pop all data in the topic

        Returns:
            tuple[list[bytes], list[float]]: A tuple containing:
                - list[bytes]: The data items
                - list[float]: Corresponding timestamps
        """
        ...

    def put_data(self, topic: str, data: bytes, timeout_s: float = 1.0, automatic_resend: bool = True) -> None:
        """
        Put data into a specified topic.

        Args:
            topic: The topic name to put data into
            data: The data to put into the topic
        """
        ...

    def get_last_retrieved_data(self) -> tuple[list[bytes], list[float]]: ...
    def get_timestamp(self) -> float: ...
    def reset_start_time(self, system_time_us: int) -> None: ...
    def request_with_data(self, topic: str, data: bytes, timeout_s: float = 1.0, automatic_resend: bool = True) -> bytes: ...
    def check_shared_memory(self, topic: str, timeout_s: float = 1.0) -> tuple[bool, str]:
        """Whether shared memory works between this client and the server for ``topic``, before any request.

        One round trip, answered by the server's background thread (no handler code of the server runs for it): the
        client writes a random probe segment that the server must verify against the supplied nonce, then opens
        the topic's data segment (read-only) and checks it is the server's file, and checks the mutex size before
        mapping it read-write. It fails on another host, in another IPC namespace (a container without
        ``--ipc=host``), or under a user who may not open the segments. The server echoes only a verified client
        nonce; failed checks return no shared-memory contents. The background thread serves one request at a time
        and, inside an in-flight
        ``request_with_data``, blocks until the server's Python calls ``reply_request``, so this check waits behind
        the slowest handler: use a ``timeout_s`` above the slowest request handler's duration.

        Returns:
            ``(True, "")`` when it works, else ``(False, reason)``. It never raises for an unreachable server, a
            missing or plain topic, or a server whose robotmq predates this call (the reason names each case). A
            reason starting ``"the exchange with the server failed"`` means a malformed reply or a socket error. A
            negative ``timeout_s`` is refused with ``(False, "timeout_s must be non-negative, ...")`` instead of
            waiting forever. Non-finite values and values above ``INT_MAX / 1000`` seconds (2147483.647 seconds
            on supported platforms) are also refused with ``(False, reason)`` before creating a probe.
        """
        ...
