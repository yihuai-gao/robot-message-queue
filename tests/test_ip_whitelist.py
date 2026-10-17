"""Tests for the optional client-IP whitelist on RMQServer.

When `allowed_ips` is non-empty, a tcp:// server only processes requests whose
source IP matches an entry (a single IPv4 address or an IPv4 CIDR network);
other peers get an ERROR reply (which the client surfaces as a RuntimeError)
instead of being served. IPv6 entries are rejected at construction time (the
server socket is IPv4-only). An empty list (the default) preserves the
previous "serve everyone" behavior.
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


def test_cidr_network_is_served():
    endpoint = _tcp_endpoint()
    # 127.0.0.1 falls inside 127.0.0.0/8.
    server = robotmq.RMQServer(
        "wl_cidr_server", endpoint, robotmq.RMQLogLevel.ERROR, allowed_ips=["127.0.0.0/8"]
    )
    server.add_topic("t", 10.0)
    client = robotmq.RMQClient("wl_cidr_client", endpoint, robotmq.RMQLogLevel.ERROR)
    assert client.get_topic_status("t", 3.0) == 0


def test_cidr_network_rejects_outside():
    endpoint = _tcp_endpoint()
    # 127.0.0.1 is outside 10.0.0.0/8.
    server = robotmq.RMQServer(
        "wl_cidr_rej_server", endpoint, robotmq.RMQLogLevel.ERROR, allowed_ips=["10.0.0.0/8"]
    )
    server.add_topic("t", 10.0)
    client = robotmq.RMQClient("wl_cidr_rej_client", endpoint, robotmq.RMQLogLevel.ERROR)
    with pytest.raises(RuntimeError, match="whitelist"):
        client.get_topic_status("t", 3.0)


def _served(allowed_ips, tag):
    """Build a server with `allowed_ips` and return the server and client."""
    endpoint = _tcp_endpoint()
    server = robotmq.RMQServer(
        f"wl_{tag}_server", endpoint, robotmq.RMQLogLevel.ERROR, allowed_ips=allowed_ips
    )
    server.add_topic("t", 10.0)
    client = robotmq.RMQClient(f"wl_{tag}_client", endpoint, robotmq.RMQLogLevel.ERROR)
    return server, client


@pytest.mark.parametrize(
    "allowed_ips, tag",
    [
        (["0.0.0.0/0"], "any"),  # /0 matches every peer
        (["127.0.0.1/32"], "host32"),  # /32 is an exact host match
        (["10.0.0.0/8", "127.0.0.1"], "mixed"),  # served via the second entry
        (["127.0.0.0/9"], "nonoctet"),  # 127.0.0.1 has bit 8 clear -> inside
    ],
)
def test_matching_entries_serve_localhost(allowed_ips, tag):
    server, client = _served(allowed_ips, tag)
    assert client.get_topic_status("t", 3.0) == 0


@pytest.mark.parametrize(
    "allowed_ips, tag",
    [
        (["127.0.0.2/32"], "host32_rej"),  # /32 of a different loopback address
        (["127.128.0.0/9"], "nonoctet_rej"),  # 127.0.0.1 has bit 8 clear -> outside
    ],
)
def test_non_matching_entries_reject_localhost(allowed_ips, tag):
    server, client = _served(allowed_ips, tag)
    with pytest.raises(RuntimeError, match="whitelist"):
        client.get_topic_status("t", 3.0)


def test_rejected_requests_do_not_wedge_the_server():
    # Every rejected request must get its ERROR reply so the REP socket stays usable.
    server, client = _served(["10.0.0.1"], "repeat_rej")
    for _ in range(3):
        with pytest.raises(RuntimeError, match="whitelist"):
            client.get_topic_status("t", 3.0)


def test_ipv6_entries_are_rejected():
    # The server socket is IPv4-only, so IPv6 entries are rejected at construction time.
    endpoint = _tcp_endpoint()
    for entry in ["::1", "fe80::1", "fe80::/64", "::ffff:127.0.0.1", "::/0"]:
        with pytest.raises(ValueError, match="IPv6"):
            robotmq.RMQServer(
                "wl_v6_server", endpoint, robotmq.RMQLogLevel.ERROR, allowed_ips=[entry]
            )


def test_invalid_ip_raises():
    endpoint = _tcp_endpoint()
    bad_entries = [
        "not_an_ip",
        "256.1.1.1",
        "192.168.0",
        "192.168.1.5/24",  # host bits set below the prefix
        "10.0.0.0/33",  # prefix out of range
        "10.0.0.0/024",  # leading zero in prefix
        "10.0.0.0/",  # empty prefix
        "10.0.0.0/x",  # non-numeric prefix
        "/24",  # missing address
        "10.0.0.0/0",  # host bits set below a /0 prefix
        " 127.0.0.1",  # leading whitespace
        "127.1",  # shorthand dotted form is not accepted
        "0.0.0.0\0/0",  # inet_pton must not silently truncate the address
        "127.0.0.1\0ignored",
    ]
    for bad in bad_entries:
        with pytest.raises(ValueError):
            robotmq.RMQServer(
                "wl_bad_server", endpoint, robotmq.RMQLogLevel.ERROR, allowed_ips=[bad]
            )


@pytest.mark.parametrize(
    "bad, message",
    [
        ("192.168.1.5/24", "host bits"),
        ("10.0.0.0/33", "exceeds /32"),
        ("10.0.0.0/x", "CIDR prefix"),
    ],
)
def test_invalid_entry_error_message(bad, message):
    with pytest.raises(ValueError, match=message):
        robotmq.RMQServer(
            "wl_msg_server", _tcp_endpoint(), robotmq.RMQLogLevel.ERROR, allowed_ips=[bad]
        )


def test_valid_entries_are_accepted():
    # Construction with well-formed IPv4 addresses and CIDR networks must not raise.
    endpoint = _tcp_endpoint()
    server = robotmq.RMQServer(
        "wl_valid_server",
        endpoint,
        robotmq.RMQLogLevel.ERROR,
        allowed_ips=["127.0.0.1", "10.0.0.1", "192.168.1.0/24", "10.0.0.0/8", "0.0.0.0/0"],
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
