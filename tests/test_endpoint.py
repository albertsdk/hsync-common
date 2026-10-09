"""Tests for hsync_common.endpoint (the shared ``HOST[:PORT]`` parser)."""

import pytest

from hsync_common.endpoint import (
    HostPort,
    build_https_url,
    build_url,
    format_authority,
    parse_host_port,
    parse_https_url,
    parse_port_list,
)


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


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("example.com", 443, "example.com:443"),
        ("192.168.1.102", 443, "192.168.1.102:443"),
        ("::1", 443, "[::1]:443"),
        ("[::1]", 443, "[::1]:443"),
        ("2001:db8::1", 8123, "[2001:db8::1]:8123"),
    ],
)
def test_format_authority_brackets_ipv6_once(host: str, port: int, expected: str) -> None:
    assert format_authority(host, port) == expected


@pytest.mark.parametrize(
    ("scheme", "host", "port", "path", "expected"),
    [
        ("https", "example.com", 443, "", "https://example.com:443"),
        ("http", "192.168.1.102", 8080, "/x", "http://192.168.1.102:8080/x"),
        ("https", "::1", 443, "", "https://[::1]:443"),
        ("https", "[::1]", 443, "/api", "https://[::1]:443/api"),
    ],
)
def test_build_url_brackets_ipv6(
    scheme: str, host: str, port: int, path: str, expected: str
) -> None:
    assert build_url(scheme, host, port, path) == expected


@pytest.mark.parametrize(
    ("host", "port", "default", "expected"),
    [
        ("example.com", None, 9753, "https://example.com:9753"),
        ("example.com", 8443, 9753, "https://example.com:8443"),
        ("::1", None, 9753, "https://[::1]:9753"),
        ("[2001:db8::1]", 443, 9753, "https://[2001:db8::1]:443"),
    ],
)
def test_build_https_url(host: str, port: int | None, default: int, expected: str) -> None:
    assert build_https_url(HostPort(host=host, port=port), default) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com",
        "https://example.com:9753",
        "https://example.com:9753/base",
        "https://[::1]:9753",
        "https://[2001:db8::1]:9753/path",
        "https://[::ffff:192.0.2.1]:443",
    ],
)
def test_parse_https_url_valid(raw: str) -> None:
    assert parse_https_url(raw) == raw


@pytest.mark.parametrize(
    "raw",
    [
        "http://example.com",
        "example.com",
        "example.com:9753",
        "https://example.com:0",
        "https://example.com:65536",
        "https://example.com/base?x=1",
        "https://user@example.com",
        "https://example.com/base#frag",
        "https://2001:db8::1:9753",
    ],
)
def test_parse_https_url_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_https_url(raw)


class TestParsePortList:
    """The shared multi-port SSOT (strict CLI vs lenient env policy)."""

    def test_lenient_keeps_order_and_drops_invalid_and_duplicates(self):
        assert parse_port_list("53, 8443, 53, nope, 0, 70000") == (53, 8443)

    def test_lenient_empty_and_whitespace_yield_empty(self):
        assert parse_port_list("") == ()
        assert parse_port_list("  ,  , ") == ()

    def test_strict_preserves_order(self):
        assert parse_port_list("443,53", strict=True) == (443, 53)
        assert parse_port_list(" 53 , 443 ", strict=True) == (53, 443)

    @pytest.mark.parametrize(
        "raw",
        ["443,notaport", "0", "70000", "65536", "443,443", "1.5", "+53", "1_0", "５３"],
    )
    def test_strict_raises_on_invalid_token(self, raw: str):
        with pytest.raises(ValueError):
            parse_port_list(raw, strict=True)

    def test_strict_empty_yields_empty_tuple(self):
        # The caller enforces its own minimum (the CLI requires at least one).
        assert parse_port_list("", strict=True) == ()
