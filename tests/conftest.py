import pytest
import robotmq
from robotmq.utils import clear_shared_memory


# Use a counter to generate unique IPC endpoints per test to avoid collisions
_endpoint_counter = 0


def _next_endpoint():
    global _endpoint_counter
    _endpoint_counter += 1
    return f"ipc:///tmp/rmq_test_{_endpoint_counter}"


@pytest.fixture
def endpoint():
    """Provide a unique IPC endpoint for each test."""
    return _next_endpoint()


@pytest.fixture
def server_client(endpoint):
    """Create a matched server/client pair on a unique IPC endpoint."""
    server = robotmq.RMQServer("test_server", endpoint, robotmq.RMQLogLevel.WARNING)
    client = robotmq.RMQClient("test_client", endpoint, robotmq.RMQLogLevel.WARNING)
    return server, client


@pytest.fixture(autouse=True)
def cleanup_shm():
    """Clean up shared memory before and after each test."""
    clear_shared_memory()
    yield
    clear_shared_memory()
