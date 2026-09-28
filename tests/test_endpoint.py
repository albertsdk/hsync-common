"""Tests for hsync_common.endpoint (the shared ``HOST[:PORT]`` parser)."""

import pytest

from hsync_common.endpoint import HostPort, parse_host_port


@pytest.mark.parametrize(
    ("raw", "host", "port"),
    [
        ("example.com", "example.com", None),
        ("boot.example.net", "boot.example.net", None),
        ("192.168.1.102", "192.168.1.102", None),
        ("example.com:443", "example.com", 443),
        ("192.168.1.102:443", "192.168.1.102", 443),
        ("host:1", "host", 1),
        ("host:65535", "host", 65535),
        ("2001:db8::1", "2001:db8::1", None),
        ("[2001:db8::1]", "2001:db8::1", None),
        ("[2001:db8::1]:443", "2001:db8::1", 443),
        ("[::1]:8443", "::1", 8443),
        ("  host:443  ", "host", 443),
    ],
)
def test_parse_host_port_valid(raw: str, host: str, port: int | None) -> None:
    parsed = parse_host_port(raw)
    assert parsed.host == host
    assert parsed.port == port


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "https://example.com",
        "https://example.com:443",
        "example.com/path",
        "host:",
        ":443",
        "host:0",
        "host:65536",
        "host:abc",
        "host:-1",
        "-bad.example.com",
        "bad.example.com.",
        ".bad.example.com",
        "host:12:34",
        "[::1",
        "::1]:443",
        "[not-an-ip]:443",
    ],
)
def test_parse_host_port_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_host_port(raw)


@pytest.mark.parametrize(
    ("host", "authority"),
    [
        ("example.com", "example.com"),
        ("192.168.1.102", "192.168.1.102"),
        ("::1", "[::1]"),
        ("2001:db8::1", "[2001:db8::1]"),
    ],
)
def test_authority_brackets_ipv6(host: str, authority: str) -> None:
    assert HostPort(host=host, port=None).authority == authority
