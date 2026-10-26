"""Server processes for the shared-memory tests, and the context manager that runs one.

They live here, in a module without import-time side effects (the context manager is a plain
function), because the tests start them with the ``spawn`` start method (``SPAWN``): forking the
multi-threaded pytest process (zmq I/O threads) can deadlock the child, and a spawned child
imports its target's module afresh.
"""

from __future__ import annotations

import contextlib
import glob
import multiprocessing
import random
import time

import robotmq

SPAWN = multiprocessing.get_context("spawn")

# 0.0001 GB = 107374 bytes: a few hundred KB is "oversized" for this topic.
SMALL_SEGMENT_GB = 0.0001


def random_bytes(rng: random.Random, n: int) -> bytes:
    """`n` deterministic bytes from `rng` (random.Random.randbytes needs Python 3.9)."""
    return rng.getrandbits(8 * n).to_bytes(n, "little")


def shm_echo_server_process(
    endpoint,
    server_name,
    topic,
    ready_event,
    seen_count=None,
    received_queue=None,
    fixed_reply=None,
    reply_errors=None,
    duration_s=10.0,
    stop_event=None,
):
    """Server with one small shared-memory topic that answers every request from Python.

    Replies with ``fixed_reply`` when given, otherwise echoes the request. Counts the requests
    its Python loop saw in ``seen_count`` and forwards their bytes to ``received_queue``. A
    ``ValueError`` from ``reply_request`` (a reply that does not fit the segment) is put on
    ``reply_errors`` and the loop goes on; without that queue it propagates and ends the server.
    Returns once ``stop_event`` is set or after ``duration_s`` seconds (the safety deadline),
    whichever comes first; returning destroys the server, whose destructor unlinks its segments.
    """
    server = robotmq.RMQServer(server_name, endpoint, robotmq.RMQLogLevel.ERROR)
    server.add_shared_memory_topic(topic, 10.0, SMALL_SEGMENT_GB)
    ready_event.set()

    deadline = time.time() + duration_s
    while time.time() < deadline and not (stop_event is not None and stop_event.is_set()):
        req_data, req_topic = server.wait_for_request(0.2)
        if not req_topic:
            continue
        if seen_count is not None:
            seen_count.value += 1
        if received_queue is not None:
            received_queue.put(req_data)
        reply = fixed_reply if fixed_reply is not None else (req_data or b"<empty request>")
        try:
            server.reply_request(req_topic, reply)
        except ValueError as e:
            if reply_errors is None:
                raise
            reply_errors.put(str(e))


@contextlib.contextmanager
def running_echo_server(endpoint, server_name, topic, **kwargs):
    """Run ``shm_echo_server_process`` in a spawned process for the duration of the block.

    Yields the process once the server is up; ``kwargs`` go to ``shm_echo_server_process``. On
    exit the server is told to stop and joined, so its target returns and ~RMQServer unlinks the
    topic's segments. When the block did not raise, the exit code must be 0 and no
    ``rmq_*_<pid>_<server_name>_<topic>`` / ``..._mutex`` segment may remain in /dev/shm: every
    spawned-server test thereby also checks the clean shutdown path.
    """
    ready = SPAWN.Event()
    stop = SPAWN.Event()
    process = SPAWN.Process(
        target=shm_echo_server_process,
        args=(endpoint, server_name, topic, ready),
        kwargs={**kwargs, "stop_event": stop},
    )
    process.start()
    try:
        assert ready.wait(timeout=30.0), "server process did not come up within 30 s"
        yield process
    finally:
        stop.set()
        process.join(timeout=10.0)
        if process.is_alive():
            process.kill()
            process.join(timeout=5.0)
    assert process.exitcode == 0, f"server process exited with {process.exitcode}"
    for suffix in ("", "_mutex"):
        leftover = glob.glob(f"/dev/shm/rmq_*_{process.pid}_{server_name}_{topic}{suffix}")
        assert leftover == [], (
            f"the server's destructor did not unlink its segments on a clean return: {leftover}"
        )
