"""Tests for hsync_common.endpoint (the shared ``HOST[:PORT]`` parser)."""

import pytest

from hsync_common.endpoint import (
    HostPort,
    build_https_url,
    build_url,
    format_authority,
    is_valid_endpoint_host,
    normalize_bare_endpoint,
    normalize_endpoint_list,
    parse_endpoint_list,
    parse_host_port,
    parse_https_url,
    parse_port_list,
)


class TestNormalizeBareEndpoint:
    """The canonicalization used by the rendezvous-server field and the GUI."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("example.com", "example.com"),
            ("example.com:443", "example.com:443"),
            ("  example.com  ", "example.com"),
            ("[::1]", "::1"),
            ("[::1]:443", "[::1]:443"),
            ("::1", "::1"),
        ],
    )
    def test_canonical_forms(self, raw: str, expected: str):
        assert normalize_bare_endpoint(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_empty_is_none(self, raw: str | None):
        assert normalize_bare_endpoint(raw) is None

    @pytest.mark.parametrize("raw", ["https://example.com", "example.com:0", "host:port"])
    def test_invalid_raises(self, raw: str):
        with pytest.raises(ValueError):
            normalize_bare_endpoint(raw)

    def test_idempotent(self):
        once = normalize_bare_endpoint("[::1]:443")
        assert normalize_bare_endpoint(once) == once


@pytest.mark.parametrize(
    ("raw", "host", "port"),
    [
        ("example.com", "example.com", None),
        ("rdv.example.net", "rdv.example.net", None),
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


class TestEndpointHostGrammar:
    """The dialable-host grammar of ``rdv/1`` ``endpoints[].host``."""

    @pytest.mark.parametrize(
        "host",
        [
            "10.0.0.1",
            "198.51.100.7",
            "2001:db8::1",
            "[2001:db8::1]",
            "peer.example",
            "a",
            "x" * 63 + ".example",
        ],
    )
    def test_accepts_dialable_hosts(self, host: str):
        assert is_valid_endpoint_host(host) is True

    @pytest.mark.parametrize(
        "host",
        [
            "",
            " ",
            "..\\..",
            "../etc/passwd",
            "a b",
            "a\x00b",
            "évil",
            "999.1.1.1",
            "a..b",
            ".leading.dot",
            "trailing.dot.",
            "x" * 64 + ".example",
            "a" * 254,
            "[::1",
            "http://peer.example",
        ],
    )
    def test_rejects_non_dialable_values(self, host: str):
        assert is_valid_endpoint_host(host) is False


class TestParseEndpointList:
    """The ordered multi-endpoint form (``HSYNC_RENDEZVOUS_SERVER_ENDPOINTS``)."""

    def test_empty_is_empty(self):
        assert parse_endpoint_list(None) == ()
        assert parse_endpoint_list("") == ()
        assert parse_endpoint_list("  ,  ") == ()

    def test_preserves_order_and_ports(self):
        assert parse_endpoint_list("a.example,b.example:8443") == (
            HostPort("a.example", None),
            HostPort("b.example", 8443),
        )

    def test_strips_spaces_and_ignores_empty_tokens(self):
        assert parse_endpoint_list(" a.example , , b.example:53 ") == (
            HostPort("a.example", None),
            HostPort("b.example", 53),
        )

    def test_ipv6_entries(self):
        assert parse_endpoint_list("[2001:db8::1]:443,::1") == (
            HostPort("2001:db8::1", 443),
            HostPort("::1", None),
        )

    def test_default_port_fills_missing_and_collapses(self):
        # ``a`` and ``a:443`` are the same destination once the channel default
        # applies: one lease, never two.
        assert parse_endpoint_list("a.example,a.example:443", default_port=443) == (
            HostPort("a.example", 443),
        )

    def test_duplicates_collapse_case_insensitively(self):
        assert parse_endpoint_list("Boot.Example,boot.example") == (HostPort("Boot.Example", None),)

    def test_lenient_drops_invalid_entries(self):
        assert parse_endpoint_list("good.example,https://evil.example,bad:0,other:53") == (
            HostPort("good.example", None),
            HostPort("other", 53),
        )

    @pytest.mark.parametrize(
        "raw",
        ["good.example,,other.example", "good.example,https://evil.example", "a.example:0"],
    )
    def test_strict_rejects_invalid_or_empty(self, raw: str):
        with pytest.raises(ValueError):
            parse_endpoint_list(raw, strict=True)

    def test_strict_rejects_duplicates(self):
        with pytest.raises(ValueError):
            parse_endpoint_list("a.example,a.example:443", strict=True, default_port=443)


class TestNormalizeEndpointList:
    """The operator-facing canonical form written back by a GUI."""

    def test_empty_is_none(self):
        assert normalize_endpoint_list(None) is None
        assert normalize_endpoint_list("   ") is None

    def test_canonical_join_without_spaces(self):
        assert (
            normalize_endpoint_list(" a.example , [2001:db8::1]:8443 ,b.example:53")
            == "a.example,[2001:db8::1]:8443,b.example:53"
        )

    def test_keeps_an_omitted_port_omitted(self):
        # The GUI must not invent the channel default port in the field.
        assert normalize_endpoint_list("a.example") == "a.example"

    def test_drops_invalid_entries_leniently(self):
        assert normalize_endpoint_list("good.example,ftp://bad.example") == "good.example"

    def test_strict_raises(self):
        with pytest.raises(ValueError):
            normalize_endpoint_list("a.example,a.example", strict=True)
