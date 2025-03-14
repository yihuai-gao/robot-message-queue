"""
 Copyright (c) 2024 Yihuai Gao
 
 This software is released under the MIT License.
 https://opensource.org/licenses/MIT
"""

def steady_clock_us() -> int: ...
def system_clock_us() -> int: ...

class RMQServer:
    def __init__(self, server_name: str, server_endpoint: str) -> None: ...
    def add_topic(self, topic: str, message_remaining_time_s: float) -> None: ...
    def put_data(self, topic: str, data: bytes) -> None: ...
    def peek_data(
        self, topic: str, order: str, n: int
    ) -> tuple[list[bytes], list[float]]:
        """Peek at data from a specified topic without removing it.

        Args:
            topic: The topic name to peek data from
            order: Data ordering, either "earliest" or "latest".
                If "latest", the latest data will appear in the first position
            n: Number of data items to retrieve. If n < 0, all data items will be retrieved.

        Returns:
            tuple[list[bytes], list[float]]: A tuple containing:
                - list[bytes]: The data items
                - list[float]: Corresponding timestamps
        """
        ...

    def pop_data(
        self, topic: str, order: str, n: int
    ) -> tuple[list[bytes], list[float]]:
        """Pop data from a specified topic.

        Args:
            topic: The topic name to pop data from
            order: Data ordering, either "earliest" or "latest". If "latest", the latest data will appear in the first position
            n: Number of data items to retrieve. If n < 0, all data items will be retrieved.

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
    def __init__(self, client_name: str, server_endpoint: str) -> None: ...
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

    def peek_data(
        self, topic: str, order: str, n: int
    ) -> tuple[list[bytes], list[float]]:
        """Peek at data from a specified topic without removing it.

        Args:
            topic: The topic name to peek data from
            order: Data ordering, either "earliest" or "latest".
                If "latest", the latest data will appear in the first position
            n: Number of data items to retrieve. If n < 0, all data items will be retrieved.

        Returns:
            tuple[list[bytes], list[float]]: A tuple containing:
                    - list[bytes]: The data items
                    - list[float]: Corresponding timestamps
        """
        ...

    def pop_data(
        self, topic: str, order: str, n: int
    ) -> tuple[list[bytes], list[float]]:
        """Pop data from a specified topic.

        Args:
            topic: The topic name to pop data from
            order: Data ordering, either "earliest" or "latest".
                If "latest", the latest data will appear in the first position
            n: Number of data items to retrieve. If n < 0, all data items will be retrieved.

        Returns:
            tuple[list[bytes], list[float]]: A tuple containing:
                - list[bytes]: The data items
                - list[float]: Corresponding timestamps
        """
        ...

    def put_data(self, topic: str, data: bytes) -> None:
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
    def request_with_data(self, topic: str, data: bytes) -> bytes: ...
