"""Tests for the optional client-IP whitelist on RMQServer.

When `allowed_ips` is non-empty, a tcp:// server only processes requests whose
source IP is in the list; other peers get an ERROR reply (which the client
surfaces as a RuntimeError) instead of being served. An empty list (the
default) preserves the previous "serve everyone" behavior.
"""

import socket

import pytest

import robotmq


def _free_tcp_port() -> int:
    """Reserve and release a free localhost TCP port for a server to bind."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _tcp_endpoint() -> str:
    return f"tcp://127.0.0.1:{_free_tcp_port()}"


def test_whitelisted_ip_is_served():
    endpoint = _tcp_endpoint()
    server = robotmq.RMQServer(
        "wl_ok_server", endpoint, robotmq.RMQLogLevel.ERROR, allowed_ips=["127.0.0.1"]
    )
    server.add_topic("t", 10.0)
    client = robotmq.RMQClient("wl_ok_client", endpoint, robotmq.RMQLogLevel.ERROR)

    # A whitelisted peer is served normally, end to end.
    assert client.get_topic_status("t", 3.0) == 0
    server.put_data("t", b"payload")
    data, _timestamps = client.pop_data("t", 1, 3.0)
    assert data == [b"payload"]


def test_non_whitelisted_ip_is_rejected():
    endpoint = _tcp_endpoint()
    # 127.0.0.1 (the client) is deliberately NOT in the whitelist.
    server = robotmq.RMQServer(
        "wl_reject_server", endpoint, robotmq.RMQLogLevel.ERROR, allowed_ips=["10.0.0.1"]
    )
    server.add_topic("t", 10.0)
    client = robotmq.RMQClient("wl_reject_client", endpoint, robotmq.RMQLogLevel.ERROR)

    with pytest.raises(RuntimeError, match="whitelist"):
        client.get_topic_status("t", 3.0)


def test_empty_whitelist_serves_all():
    # Backward compatibility: no allowed_ips means every peer is served.
    endpoint = _tcp_endpoint()
    server = robotmq.RMQServer("wl_default_server", endpoint, robotmq.RMQLogLevel.ERROR)
    server.add_topic("t", 10.0)
    client = robotmq.RMQClient("wl_default_client", endpoint, robotmq.RMQLogLevel.ERROR)

    assert client.get_topic_status("t", 3.0) == 0


def test_invalid_ip_raises():
    endpoint = _tcp_endpoint()
    for bad in ["not_an_ip", "256.1.1.1", "192.168.0"]:
        with pytest.raises(ValueError):
            robotmq.RMQServer(
                "wl_bad_server", endpoint, robotmq.RMQLogLevel.ERROR, allowed_ips=[bad]
            )


def test_valid_ipv4_and_ipv6_are_accepted():
    # Construction with well-formed IPv4 and IPv6 entries must not raise.
    endpoint = _tcp_endpoint()
    server = robotmq.RMQServer(
        "wl_valid_server",
        endpoint,
        robotmq.RMQLogLevel.ERROR,
        allowed_ips=["127.0.0.1", "10.0.0.1", "::1", "fe80::1"],
    )
    assert server is not None


def test_allowed_ips_keyword_without_log_level():
    # allowed_ips must be usable without passing log_level positionally.
    endpoint = _tcp_endpoint()
    server = robotmq.RMQServer("wl_kw_server", endpoint, allowed_ips=["127.0.0.1"])
    server.add_topic("t", 10.0)
    client = robotmq.RMQClient("wl_kw_client", endpoint, robotmq.RMQLogLevel.ERROR)
    assert client.get_topic_status("t", 3.0) == 0


def test_ipc_whitelist_is_ignored(endpoint):
    # The `endpoint` fixture is an ipc:// endpoint. IPC peers have no IP, so the
    # whitelist is ignored (with a warning) and normal traffic still flows.
    server = robotmq.RMQServer(
        "wl_ipc_server", endpoint, robotmq.RMQLogLevel.ERROR, allowed_ips=["10.0.0.1"]
    )
    server.add_topic("t", 10.0)
    client = robotmq.RMQClient("wl_ipc_client", endpoint, robotmq.RMQLogLevel.ERROR)
    assert client.get_topic_status("t", 3.0) == 0
