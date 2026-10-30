# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Shared ``HOST[:PORT]`` endpoint parsing for every ``hsync*`` CLI.

Single source of truth for the combined host/port form accepted by the
terminal-launchable commands. Consumers:

* ``hsync-client`` — ``cli.py`` rendezvous/server/trust host arguments;
* ``hsync-rendezvous`` — ``run --host HOST[:PORT]``;
* ``hsync-server`` — ``--host HOST[:PORT]`` bind option.

Grammar:

* ``host`` / ``IPv4`` / ``host:port`` / ``IPv4:port``;
* ``[IPv6]`` / ``[IPv6]:port`` (bracketed IPv6 may carry a port);
* a bare IPv6 literal (more than one ``:``, unbracketed) is a host with no port.

The port, when present, must be an integer in ``1..65535``. URL-like input
(``://`` or a path) is rejected.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from hsync_common.constants import HOSTNAME_PATTERN

__all__ = [
    "HostPort",
    "build_https_url",
    "build_url",
    "format_authority",
    "is_valid_endpoint_host",
    "normalize_bare_endpoint",
    "normalize_endpoint_list",
    "parse_endpoint_list",
    "parse_host_port",
    "parse_https_url",
    "parse_port_list",
]

# Bare hostname / IPv4 (SSOT: HOSTNAME_PATTERN in hsync_common.constants).
_HOST_RE = re.compile(rf"^{HOSTNAME_PATTERN}$")

# An unbracketed IPv6 literal: only hex digits, colons and dots.
_IPV6_RE = re.compile(r"^[0-9A-Fa-f:.]+$")

# A bracketed IPv6 with an optional trailing ``:port``.
_BRACKETED_RE = re.compile(r"^\[([0-9A-Fa-f:.]+)\](?::(\d+))?$")


@dataclass(frozen=True, slots=True)
class HostPort:
    """A parsed endpoint: a raw host plus an optional explicit port.

    ``host`` is always the unbracketed form (an IPv6 address, IPv4 address or
    hostname); ``port`` is ``None`` when the input carried no port. Use
    :attr:`authority` to obtain the bracketed ``host[:port]`` form for URLs and
    display.
    """

    host: str
    port: int | None

    @property
    def authority(self) -> str:
        """Return ``host`` with IPv6 literals bracketed (no port included)."""
        return f"[{self.host}]" if ":" in self.host else self.host


def _parse_port(port_raw: str) -> int:
    """Parse and range-check a port string; raise ``ValueError`` when invalid."""
    if not port_raw.isdigit():
        raise ValueError(f"invalid port: {port_raw!r}")
    port = int(port_raw)
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be between 1 and 65535, got {port}")
    return port


def parse_port_list(raw: str, *, strict: bool = False) -> tuple[int, ...]:
    """Parse a comma-separated UDP port list (order preserved, ``1..65535``).

    Single source of truth for the ordered multi-port set shared by the two
    consumers, which apply different error policies:

    * ``hsync-rendezvous`` — ``run --ports`` calls with ``strict=True`` and turns
      the :class:`ValueError` into a user-facing CLI error;
    * ``hsync-client`` — ``HSYNC_RENDEZVOUS_PORTS`` calls with ``strict=False`` and
      silently drops invalid/duplicate entries (env getters are lenient).

    Empty tokens are ignored on both policies. With ``strict=True`` the first
    invalid token or duplicate raises :class:`ValueError`; with
    ``strict=False`` they are dropped. An empty input (or one with no valid
    entry) yields ``()``; each caller enforces its own minimum (the CLI requires
    at least one port, the client treats ``()`` as single-port dialing).
    """
    ports: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        # ASCII digits only: ``str.isdigit`` also accepts non-ASCII digits that
        # ``int`` would silently coerce (e.g. full-width "５"), which is not a
        # valid port token.
        if not (token.isascii() and token.isdigit()):
            if strict:
                raise ValueError(f"must be comma-separated integers, got {token!r}")
            continue
        try:
            value = int(token)
        except ValueError:  # a >4300-digit token exceeds int()'s string limit
            if strict:
                raise ValueError(f"must be comma-separated integers, got {token!r}") from None
            continue
        if not 1 <= value <= 65535:
            if strict:
                raise ValueError(f"entries must be between 1 and 65535, got {value}")
            continue
        if value in ports:
            if strict:
                raise ValueError(f"has a duplicate port {value}")
            continue
        ports.append(value)
    return tuple(ports)


def parse_host_port(raw: str) -> HostPort:
    """Parse a ``HOST[:PORT]`` endpoint into a :class:`HostPort`.

    Raises:
        ValueError: on empty input, URL-like input, an invalid port, or an
            invalid host (hostname/IPv4/IPv6).
    """
    value = raw.strip()
    if not value:
        raise ValueError("an endpoint must not be empty")
    if "://" in value or "/" in value:
        raise ValueError(f"pass a bare host (HOST[:PORT]), not a URL: {raw!r}")

    host: str
    port: int | None = None
    if value.startswith("["):
        match = _BRACKETED_RE.match(value)
        if match is None:
            raise ValueError(f"invalid bracketed IPv6 endpoint: {value!r}")
        host = match.group(1)
        if match.group(2) is not None:
            port = _parse_port(match.group(2))
    else:
        colons = value.count(":")
        if colons == 0:
            host = value
        elif colons == 1:
            host, port_raw = value.rsplit(":", 1)
            if not host:
                raise ValueError(f"missing host in endpoint: {value!r}")
            port = _parse_port(port_raw)
        else:
            # Bare IPv6 literal (more than one colon): host only, no port.
            host = value

    host = host.strip()
    if not host:
        raise ValueError("missing host in endpoint")
    if ":" in host:
        if not _IPV6_RE.match(host):
            raise ValueError(f"invalid IPv6 address: {host!r}")
    elif not _HOST_RE.match(host):
        raise ValueError(f"invalid hostname or IPv4 address: {host!r}")

    return HostPort(host=host, port=port)


def is_valid_endpoint_host(value: str) -> bool:
    """Return True when *value* is a host a remote peer can dial.

    Accepted: an IPv4/IPv6 literal (bracketed or bare) or an LDH hostname.
    Rejected: everything else — empty values, control characters, path or
    authority separators, empty labels, labels longer than 63 characters, and
    values that look like an IPv4 literal without being one.

    Stricter than :func:`parse_host_port`, which parses operator input that a
    human immediately sees fail: this is the grammar of a value a *remote*
    client will dial, so a shape a resolver cannot turn into an address is an
    invalid value rather than a dial-time error on someone else's host.

    Consumers: ``hsync-rendezvous`` (``protocol.Endpoint``), the rendezvous mirror in
    :mod:`hsync_common.protocol.rendezvous`, and the shared fixtures/tests.
    """
    host = value
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host or len(host) > 253:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    # All-digits-and-dots is an IPv4 attempt; it must be a *valid* one.
    if all(char.isdigit() or char == "." for char in host):
        return False
    if _HOST_RE.fullmatch(host) is None or ".." in host:
        return False
    return all(len(label) <= 63 for label in host.split("."))


def _authority_of(host: str) -> str:
    """Return *host* with IPv6 literals bracketed (strips a pre-existing bracket).

    ``::1`` and ``[::1]`` both yield ``[::1]`` so a caller can never produce a
    double-bracketed authority; hostnames and IPv4 addresses pass through.
    """
    value = host.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return f"[{value}]" if ":" in value else value


def format_authority(host: str, port: int) -> str:
    """Return the canonical ``host:port`` composite, bracketing IPv6 literals.

    The composite form (``[::1]:443``) is unambiguous and parseable by
    :func:`parse_host_port`, so it is the display/key form wherever a host is
    joined with a port. Consumers: ``hsync-client`` (trust-store keys, CLI/log
    display), ``hsync-desktop`` (trust-key table cells), shared fixtures.
    """
    return f"{_authority_of(host)}:{port}"


def build_url(scheme: str, host: str, port: int, path: str = "") -> str:
    """Build ``scheme://authority[:port]path`` with IPv6-safe bracketing.

    The only host+port URL builder: every ``hsync*`` component that composes a
    URL from a discovered/configured host and port routes through here so an
    IPv6 endpoint is never emitted as ``scheme://::1:port``.

    Consumers: ``hsync-client`` (``p2p_peers.server_url``, ``p2p_websocket``
    master URLs), ``hsync-desktop`` (``server_url``), Android parity mirror.
    """
    return f"{scheme}://{_authority_of(host)}:{port}{path}"


def build_https_url(hp: HostPort, default_port: int) -> str:
    """Return the canonical HTTPS URL for a parsed endpoint.

    The scheme is implied (server mode refuses non-HTTPS) and the port is always
    explicit: ``hp.port`` when present, otherwise ``default_port``. The host is
    bracketed for IPv6 via :attr:`HostPort.authority`.

    Consumers: ``hsync-client`` (CLI ``_build_server_url`` and the ``HSYNC_SERVER_URL``
    environment validator), ``hsync-desktop`` (settings normalization).
    """
    port = hp.port if hp.port is not None else default_port
    return f"https://{_authority_of(hp.host)}:{port}"


# URL-like HTTPS base accepted for ``HSYNC_SERVER_URL``: scheme + (IPv6-aware)
# authority + optional port + optional path. Username/password, query and
# fragment are rejected (a server base never carries them).
_HTTPS_URL_RE = re.compile(
    r"^https://"
    r"(?P<host>\[[0-9A-Fa-f:.]+]|[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9]))"
    r"(?::(?P<port>\d+))?"
    r"(?P<path>/.*)?$"
)


def parse_https_url(raw: str) -> str:
    """Validate an already-``https://`` URL and return it unchanged.

    The explicit-URL form is the only one that may carry a path (a base path
    behind a reverse proxy). ``http://``, credentials, query and fragment are
    rejected; the host must be a hostname/IPv4 or a bracketed IPv6 literal and
    the port, when present, 1-65535.

    Consumers: ``hsync-client`` (``HSYNC_SERVER_URL`` validator), ``hsync-desktop``
    (``server_url`` validator).
    """
    value = raw.strip()
    if value.lower().startswith("http://"):
        raise ValueError(f"server URL must use HTTPS, not HTTP: {raw!r}")
    match = _HTTPS_URL_RE.match(value)
    if match is None:
        raise ValueError(f"invalid server URL: {raw!r}")
    port_raw = match.group("port")
    if port_raw is not None:
        port = int(port_raw)
        if not 1 <= port <= 65535:
            raise ValueError(f"port must be between 1 and 65535, got {port}")
    host = match.group("host")
    parsed = parse_host_port(host)
    if parsed.port is not None:
        raise ValueError(f"invalid server URL host: {raw!r}")
    # Reject a query/fragment smuggled past the regex host capture.
    if urlsplit(value).query or urlsplit(value).fragment:
        raise ValueError(f"invalid server URL: {raw!r}")
    return value


def normalize_bare_endpoint(raw: str | None) -> str | None:
    """Canonicalize a scheme-less ``HOST[:PORT]`` value; empty yields ``None``.

    Single definition of the "bare endpoint" normalization: the unbracketed host
    when the input carries no port, otherwise the ``[IPv6]:port`` composite from
    :func:`format_authority`. Values that already are canonical are returned
    unchanged; invalid input raises :class:`ValueError` (from
    :func:`parse_host_port`).

    Used for channels that are not URLs (QUIC/UDP discovery servers) and
    therefore must not gain a scheme or a default port.

    Consumers: ``hsync-client`` (``HSYNC_RENDEZVOUS_SERVER_TRUST`` file keys and
    the single-endpoint trust commands), ``hsync-desktop`` (settings and wizard
    "discovery servers" field), shared tests.
    """
    value = (raw or "").strip()
    if not value:
        return None
    endpoint = parse_host_port(value)
    if endpoint.port is None:
        return endpoint.host
    return format_authority(endpoint.host, endpoint.port)


def _endpoint_key(endpoint: HostPort) -> tuple[str, int | None]:
    """Identity of an endpoint for deduplication (DNS names/IPv6 are case-insensitive)."""
    return endpoint.host.lower(), endpoint.port


def parse_endpoint_list(
    raw: str | None,
    *,
    strict: bool = False,
    default_port: int | None = None,
) -> tuple[HostPort, ...]:
    """Parse a comma-separated list of scheme-less ``HOST[:PORT]`` endpoints.

    Single definition of the ordered multi-endpoint form: one destination per
    entry, order preserved, duplicates collapsed. Two consumers apply different
    error policies, exactly like :func:`parse_port_list`:

    * ``hsync-client`` env (``HSYNC_RENDEZVOUS_SERVER_ENDPOINTS``) calls with
      ``strict=False``: an invalid or duplicate entry is dropped;
    * the repeatable CLI option calls with ``strict=True`` and turns the
      :class:`ValueError` into a user-facing usage error.

    ``default_port`` fills the entries that carry no port, so ``a`` and
    ``a:443`` collapse into one endpoint instead of dialing the same node twice.
    Without it the ports stay ``None`` and the caller applies its own default.

    An empty input (or one with no valid entry) yields ``()``; each caller
    enforces its own minimum (the CLI requires at least one endpoint).
    """
    value = (raw or "").strip()
    if not value:
        return ()
    endpoints: list[HostPort] = []
    seen: set[tuple[str, int | None]] = set()
    for token in value.split(","):
        token = token.strip()
        if not token:
            if strict:
                raise ValueError("empty endpoint in the list")
            continue
        try:
            endpoint = parse_host_port(token)
        except ValueError:
            if strict:
                raise
            continue
        if endpoint.port is None and default_port is not None:
            endpoint = HostPort(host=endpoint.host, port=default_port)
        key = _endpoint_key(endpoint)
        if key in seen:
            if strict:
                raise ValueError(f"duplicate endpoint {token!r}")
            continue
        seen.add(key)
        endpoints.append(endpoint)
    return tuple(endpoints)


def normalize_endpoint_list(raw: str | None, *, strict: bool = False) -> str | None:
    """Canonicalize a comma-separated endpoint list; empty yields ``None``.

    Each entry is canonicalized by :func:`normalize_bare_endpoint` and the list
    is re-joined with ``,`` (no spaces), so the value a GUI writes back into its
    field is byte-identical to the value the client parses. An entry without a
    port keeps omitting it: this is the operator-facing form, not the dialed one
    (:func:`parse_endpoint_list` applies the channel default port).

    Invalid or duplicate entries raise :class:`ValueError` with ``strict=True``
    and are dropped otherwise.
    """
    endpoints = parse_endpoint_list(raw, strict=strict)
    if not endpoints:
        return None
    return ",".join(
        format_authority(e.host, e.port) if e.port is not None else e.host for e in endpoints
    )
