"""Tests for hsync_common.upnp: SSRF hardening of the SSDP/SOAP IGD client.

No real network is touched: the reply gate is exercised with a fake socket and
an injected fetch, and the URL validators are pure.
"""

from __future__ import annotations

from hsync_common.upnp import (
    IgdService,
    _control_url_on_base,
    _first_igd_location,
    _location_host_matches_source,
    _NoRedirect,
    is_lan_unicast_address,
    is_private_http_location,
    parse_soap_error,
)

NS = "urn:schemas-upnp-org:service:WANIPConnection:1"


def test_lan_unicast_source_filter() -> None:
    for good in ("192.168.1.7", "10.1.2.3", "172.16.5.5", "fd00::7"):
        assert is_lan_unicast_address(good) is True
    for bad in (
        "8.8.8.8",
        "203.0.113.9",
        "2001:db8::1",
        "169.254.169.254",
        "fe80::1",
        "127.0.0.1",
        "::1",
        "not-an-address",
    ):
        assert is_lan_unicast_address(bad) is False


def test_location_must_be_a_private_http_ip_literal() -> None:
    for good in (
        "http://192.168.1.1:5000/rootDesc.xml",
        "https://10.0.0.2/desc",
        "http://[fd00::7]:5000/d",
    ):
        assert is_private_http_location(good) is True
    for bad in (
        "",
        "file:///etc/passwd",
        "ftp://192.168.1.1/desc.xml",
        "http://router.lan/rootDesc.xml",
        "http://203.0.113.9/rootDesc.xml",
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1/",
        "http://user:password@192.168.1.1/desc.xml",
        "http://192.168.1.1:70000/desc.xml",
    ):
        assert is_private_http_location(bad) is False


def test_control_url_must_stay_on_the_igd_host() -> None:
    base = "http://192.168.1.1:5000/rootDesc.xml"
    assert _control_url_on_base(base, "/ctl/IPConn") == "http://192.168.1.1:5000/ctl/IPConn"
    assert _control_url_on_base(base, "ctl/IPConn") == "http://192.168.1.1:5000/ctl/IPConn"
    assert _control_url_on_base(base, "/ctl/../desc") == "http://192.168.1.1:5000/desc"
    assert _control_url_on_base(base, "http://203.0.113.9/steal") is None
    assert _control_url_on_base(base, "//203.0.113.9/steal") is None
    assert _control_url_on_base(base, "https://192.168.1.1:5000/steal") is None


def test_location_host_must_match_the_reply_source() -> None:
    assert _location_host_matches_source("http://192.168.1.1/x", "192.168.1.1") is True
    assert _location_host_matches_source("http://[fd00::7]/x", "fd00::7") is True
    assert _location_host_matches_source("http://192.168.1.1/x", "192.168.1.50") is False
    assert _location_host_matches_source("http://not-an-ip/x", "x") is False


def test_redirects_are_refused() -> None:
    # The opener's redirect handler never builds a follow-up request.
    assert _NoRedirect().redirect_request(None, None, 302, "Found", None, "http://x/") is None


class _FakeSocket:
    def __init__(self, replies: list[tuple[bytes, tuple[str, int]]]) -> None:
        self._replies = list(replies)

    def setsockopt(self, *_args: object) -> None: ...

    def settimeout(self, _value: float) -> None: ...

    def bind(self, _addr: object) -> None: ...

    def sendto(self, _data: bytes, _addr: object) -> None: ...

    def close(self) -> None: ...

    def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
        if not self._replies:
            raise TimeoutError("queue drained")
        return self._replies.pop(0)

    def getsockname(self) -> tuple[str, int]:
        return ("192.168.1.10", 0)


def test_reply_gate_discards_off_lan_and_mismatched_hosts() -> None:
    reply = b"HTTP/1.1 200 OK\r\nLOCATION: http://192.168.1.1:5000/rootDesc.xml\r\n\r\n"
    file_reply = reply.replace(b"http://192.168.1.1:5000/rootDesc.xml", b"file:///etc/passwd")
    fetched: list[str] = []

    def fake_fetch(location: str, local_ip: str) -> IgdService | None:
        fetched.append(location)
        return None

    sock = _FakeSocket(
        [
            (reply, ("203.0.113.9", 50000)),  # off-LAN source
            (file_reply, ("192.168.1.50", 5000)),  # LAN source, file:// LOCATION
            (reply, ("192.168.1.50", 5000)),  # LAN source naming a different host
            (reply, ("192.168.1.1", 1900)),  # LAN source equal to the LOCATION host
        ]
    )
    result = _first_igd_location(sock, 2.0, "192.168.1.10", fetch=fake_fetch)  # type: ignore[arg-type]
    assert result is None
    assert fetched == ["http://192.168.1.1:5000/rootDesc.xml"]


def test_discover_igd_returns_none_without_a_reply() -> None:
    # A socket that never receives anything degrades to "no UPnP", never raises.
    class _Silent(_FakeSocket):
        def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
            raise TimeoutError("silent")

    from hsync_common import upnp as upnp_mod

    monkey_sock = _Silent([])
    # Bind-free path: patch the socket factory so no real network is used.
    original = upnp_mod.socket.socket
    upnp_mod.socket.socket = lambda *a, **k: monkey_sock  # type: ignore[assignment]
    try:
        assert upnp_mod.discover_igd(timeout=0.01) is None
    finally:
        upnp_mod.socket.socket = original  # type: ignore[assignment]


def test_soap_error_parsing_is_bounded() -> None:
    """A SOAP fault body is read under the byte bound, never unbounded."""
    fault = (
        b"<Envelope><Body><Fault><detail><UPnPError>"
        b"<errorCode>718</errorCode></UPnPError></detail></Fault></Body></Envelope>"
    )
    assert parse_soap_error(fault) == 718
    # An error code beyond the bound is not parsed (the read is bounded by bytes).
    padded = b"<r>" + b"<!--pad-->" * 8000 + b"<errorCode>718</errorCode></r>"
    assert parse_soap_error(padded) is None
    # Malformed/empty bodies degrade to "no error code", never raise.
    assert parse_soap_error(b"") is None
    assert parse_soap_error(b"<not-xml") is None


def test_soap_error_refuses_a_document_type_declaration() -> None:
    """An entity expansion bomb from a LAN device is refused, not expanded."""
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        b"<lolz><errorCode>&lol;</errorCode></lolz>"
    )
    assert parse_soap_error(bomb) is None
