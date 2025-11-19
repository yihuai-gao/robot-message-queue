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
    def __init__(self, server_name: str, server_endpoint: str, log_level: RMQLogLevel=RMQLogLevel.INFO) -> None: ...
    def add_topic(self, topic: str, message_remaining_time_s: float) -> None: ...
    def add_shared_memory_topic(
        self, topic: str, message_remaining_time_s: float, shared_memory_size_gb: float
    ) -> None: ...
    def put_data(self, topic: str, data: bytes) -> None: ...
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
    def reply_request(self, topic: str, data: bytes) -> None: ...

class RMQClient:
    def __init__(self, client_name: str, server_endpoint: str, log_level: RMQLogLevel=RMQLogLevel.INFO) -> None: ...
    def get_topic_status(self, topic: str, timeout_s: float) -> int:
        """
        Get the status of a specified topic.

        Args:
            topic: The topic name to get status from
            timeout_s: Timeout in seconds

        Returns:
            int: The status of the topic
                -2 if the server does not exist (getting no reply after timeout_s seconds)
                -1 if topic does not exist
                0 if the topic exists but has no data
                positive number means the number of data in the topic
        """
        ...

    def peek_data(self, topic: str, n: int, timeout_s: float = 1.0) -> tuple[list[bytes], list[float]]:
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

    def pop_data(self, topic: str, n: int, timeout_s: float = 1.0) -> tuple[list[bytes], list[float]]:
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

    def put_data(self, topic: str, data: bytes, timeout_s: float = 1.0) -> None:
        """
        Put data into a specified topic.

        Args:
            topic: The topic name to put data into
            data: The data to put into the topic
        """
        ...

    def get_last_retrieved_data(self) -> tuple[bytes, str]: ...
    def get_timestamp(self) -> float: ...
    def reset_start_time(self, system_time_us: int) -> None: ...
    def request_with_data(self, topic: str, data: bytes, timeout_s: float = 1.0) -> bytes: ...
