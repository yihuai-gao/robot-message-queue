"""Cross-version tests: this repo's robotmq against the OLD robotmq release installed in
site-packages (one without RMQClient.check_shared_memory).

The old side always runs in a ``python -I`` subprocess: isolated mode ignores PYTHONPATH, the
script directory and the cwd, so ``import robotmq`` there resolves to site-packages while the
test process keeps importing the repo copy. The module is skipped unless such an old install
exists, lives outside this repo, lacks check_shared_memory, and has the RMQLogLevel enum and
request_with_data's automatic_resend keyword that the old-side scripts use.

Covered:

* new client -> old server: check_shared_memory reports that the server does not support it,
  removes its probe segment, and the old server survives the unknown command.
* old client -> new server: a 1 MB reply on a 0.0001 GB shared-memory topic is refused by the
  new server's reply_request, and the old client gets that error reply (a RuntimeError) at once
  instead of hanging; the raw GET_TOPIC_STATUS reply first proves the topic is shared-memory on
  the wire, so the refusal is the segment-size check.
* old client -> new server: a small request_with_data still round-trips through shared memory,
  and the old client's request segment is gone afterwards; the raw GET_TOPIC_STATUS reply first
  proves the old client saw the 8-byte status with the flag set, i.e. took the segment path.

Every old-release subprocess is bounded with a timeout and killed in a finally block; the spawned
new servers are stopped through a stop event and joined, so their destructor unlinks their
segments (asserted on exit by running_echo_server).
"""

from __future__ import annotations

import glob
import hashlib
import os
import pathlib
import random
import select
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid

import pytest

import robotmq
from tests._rmq_wire import assert_shared_memory_topic
from tests._shm_server_processes import SMALL_SEGMENT_GB, SPAWN, random_bytes, running_echo_server

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


# Four lines: module path, has check_shared_memory, has RMQLogLevel, request_with_data takes
# automatic_resend (pybind puts the signature in __doc__).
PROBE_CODE = (
    "import robotmq, robotmq.core.robotmq_core as c; "
    "print(robotmq.__file__); print(hasattr(c.RMQClient, 'check_shared_memory')); "
    "print(hasattr(robotmq, 'RMQLogLevel')); "
    "print('automatic_resend' in (c.RMQClient.request_with_data.__doc__ or ''))"
)


def _inside(path: pathlib.Path, root: pathlib.Path) -> bool:
    """Whether `path` lies under `root` (pathlib.Path.is_relative_to needs Python 3.9)."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _find_old_robotmq() -> str:
    """Path of the site-packages robotmq, or a module-level skip when it is not an old build."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            probe = subprocess.run(
                [sys.executable, "-I", "-c", PROBE_CODE], cwd=tmp, capture_output=True, text=True, timeout=60
            )
        except subprocess.TimeoutExpired:
            pytest.skip("probing the site-packages robotmq timed out", allow_module_level=True)
    if probe.returncode != 0:
        pytest.skip(
            f"no importable robotmq in site-packages (python -I): {probe.stderr.strip()[-300:]}",
            allow_module_level=True,
        )
    lines = probe.stdout.strip().splitlines()
    if len(lines) < 4:
        pytest.skip(f"unexpected probe output: {probe.stdout!r}", allow_module_level=True)
    old_path, has_check, has_log_level, has_resend = (line.strip() for line in lines[-4:])
    if _inside(pathlib.Path(old_path).resolve(), REPO_ROOT):
        pytest.skip(f"the site-packages robotmq resolves into this repo: {old_path}", allow_module_level=True)
    if has_check != "False":
        pytest.skip(f"the installed robotmq already has check_shared_memory: {old_path}", allow_module_level=True)
    if has_log_level != "True":
        pytest.skip(
            f"the installed robotmq has no RMQLogLevel, which the old-side scripts use: {old_path}",
            allow_module_level=True,
        )
    if has_resend != "True":
        pytest.skip(
            f"the installed robotmq's request_with_data takes no automatic_resend, which the old client script uses: "
            f"{old_path}",
            allow_module_level=True,
        )
    return old_path


if not _inside(pathlib.Path(robotmq.__file__).resolve(), REPO_ROOT):
    pytest.skip(f"the robotmq under test is not this repo's copy: {robotmq.__file__}", allow_module_level=True)

OLD_ROBOTMQ_PATH = _find_old_robotmq()


# --------------------------------------------------------------------------------------
# Old-side scripts (run with `python -I`, so they import the site-packages robotmq)
# --------------------------------------------------------------------------------------

OLD_SERVER_SCRIPT = textwrap.dedent(
    """
    import sys, time
    import robotmq

    endpoint, topic, hold_s = sys.argv[1], sys.argv[2], float(sys.argv[3])
    server = robotmq.RMQServer("old_server", endpoint, robotmq.RMQLogLevel.WARNING)
    server.add_shared_memory_topic(topic, 10.0, 0.0001)
    print("READY " + robotmq.__file__, flush=True)
    deadline = time.time() + hold_s
    while time.time() < deadline:
        time.sleep(0.05)
    """
)

OLD_CLIENT_SCRIPT = textwrap.dedent(
    """
    import hashlib, sys
    import robotmq

    endpoint, topic, request_hex = sys.argv[1], sys.argv[2], sys.argv[3]
    print("MODULE " + robotmq.__file__, flush=True)
    client = robotmq.RMQClient("old_client", endpoint, robotmq.RMQLogLevel.WARNING)
    try:
        reply = client.request_with_data(topic, bytes.fromhex(request_hex), timeout_s=5.0, automatic_resend=False)
    except Exception as e:
        print("ERROR " + type(e).__name__ + " " + str(e).replace("\\n", " "), flush=True)
    else:
        print("REPLY " + str(len(reply)) + " " + hashlib.sha256(reply).hexdigest(), flush=True)
    """
)


def _wait_for_line(proc: subprocess.Popen, prefix: str, timeout_s: float) -> str:
    """Read the subprocess's unbuffered stdout line by line until one starts with `prefix`."""
    deadline = time.monotonic() + timeout_s
    seen: list[str] = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"timed out waiting for {prefix!r}; stdout so far: {seen}")
        readable, _, _ = select.select([proc.stdout], [], [], remaining)
        if not readable:
            continue
        line = proc.stdout.readline()
        if not line:
            err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            raise AssertionError(f"subprocess exited (rc={proc.poll()}) before {prefix!r}: {err[-500:]}")
        text = line.decode(errors="replace").strip()
        seen.append(text)
        if text.startswith(prefix):
            return text


def _run_old_client(tmp_path: pathlib.Path, endpoint: str, topic: str, request: bytes) -> tuple[str, int]:
    """Run the old client once; return (its outcome line, subprocess pid). The outcome line is
    ``REPLY <length> <sha256>`` or ``ERROR <exception type> <message>``."""
    script = tmp_path / "old_client.py"
    script.write_text(OLD_CLIENT_SCRIPT)
    proc = subprocess.Popen(
        [sys.executable, "-I", str(script), endpoint, topic, request.hex()],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        try:
            out, err = proc.communicate(timeout=20.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            pytest.fail(f"old client did not finish within 20 s; stdout={out[-500:]!r} stderr={err[-500:]!r}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5.0)
    assert proc.returncode == 0, f"old client failed (rc={proc.returncode}): {err.decode(errors='replace')[-800:]}"

    lines = out.decode(errors="replace").splitlines()
    module_line = next((line for line in lines if line.startswith("MODULE ")), None)
    assert module_line == f"MODULE {OLD_ROBOTMQ_PATH}", f"old client did not import the old robotmq: {lines}"
    outcome = next((line for line in lines if line.startswith(("REPLY ", "ERROR "))), None)
    assert outcome is not None, f"old client printed no REPLY or ERROR line: {lines}"
    return outcome, proc.pid


def _reply_length_and_digest(outcome: str) -> tuple[int, str]:
    assert outcome.startswith("REPLY "), f"old client got no reply: {outcome}"
    _tag, length, digest = outcome.split()
    return int(length), digest


class TestCrossVersion:
    def test_new_client_check_against_old_server(self, endpoint, tmp_path):
        topic = "shm"
        script = tmp_path / "old_server.py"
        script.write_text(OLD_SERVER_SCRIPT)
        proc = subprocess.Popen(
            [sys.executable, "-I", str(script), endpoint, topic, "20"],
            cwd=tmp_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        try:
            ready_line = _wait_for_line(proc, "READY ", timeout_s=10.0)
            assert ready_line == f"READY {OLD_ROBOTMQ_PATH}", f"old server did not import the old robotmq: {ready_line}"

            client_name = f"new_client_{uuid.uuid4().hex[:8]}"
            client = robotmq.RMQClient(client_name, endpoint, robotmq.RMQLogLevel.ERROR)
            ok, reason = client.check_shared_memory(topic, timeout_s=2.0)
            assert ok is False
            assert "does not support check_shared_memory" in reason

            leftover = glob.glob(f"/dev/shm/rmq_*_{os.getpid()}_{client_name}_{topic}_*_probe")
            assert leftover == [], f"check_shared_memory left its probe segment behind: {leftover}"

            # The old server survived the unknown command.
            assert client.get_topic_status(topic, 3.0) == 0
        finally:
            proc.kill()
            proc.wait(timeout=5.0)
            proc.stdout.close()
            proc.stderr.close()

    def test_old_client_gets_error_reply_for_oversized_reply_from_new_server(self, endpoint, tmp_path):
        topic = "shm"
        big = random_bytes(random.Random(20261025), 1 << 20)
        assert len(big) > int(SMALL_SEGMENT_GB * 1024**3)
        reply_errors = SPAWN.Queue()
        with running_echo_server(endpoint, "new_server", topic, fixed_reply=big, reply_errors=reply_errors):
            # The topic is shared-memory on the wire, so the refusal below is the segment-size check.
            assert_shared_memory_topic(endpoint, topic)
            outcome, _pid = _run_old_client(tmp_path, endpoint, topic, b"send the big one")
            assert outcome.startswith("ERROR RuntimeError "), outcome
            assert "could not store its reply on topic `shm`" in outcome and "does not fit" in outcome, outcome
            assert "does not fit" in reply_errors.get(timeout=5.0)

    def test_old_client_small_request_round_trips_through_shared_memory(self, endpoint, tmp_path):
        topic = "shm"
        request = random_bytes(random.Random(5), 1000)
        with running_echo_server(endpoint, "new_server", topic):
            # The old client takes the segment path only on an 8-byte status reply with the flag set;
            # without this check, length, digest and the empty glob below also hold for an inline fallback.
            assert_shared_memory_topic(endpoint, topic)
            outcome, old_pid = _run_old_client(tmp_path, endpoint, topic, request)
            length, digest = _reply_length_and_digest(outcome)
            assert length == len(request)
            assert digest == hashlib.sha256(request).hexdigest()
            # The old client unlinks its request segment itself once the reply is in (old naming
            # scheme: no random token).
            leftover = glob.glob(f"/dev/shm/rmq_*_{old_pid}_old_client_{topic}_request")
            assert leftover == [], f"old client's request segment left behind: {leftover}"
