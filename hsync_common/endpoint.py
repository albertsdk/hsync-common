# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Shared ``HOST[:PORT]`` endpoint parsing for every ``hsync*`` CLI.

Single source of truth for the combined host/port form accepted by the
terminal-launchable commands. Consumers:

* ``hsync-client`` — ``cli.py`` bootnode/server/trust host arguments;
* ``hsync-bootnode`` — ``run --host HOST[:PORT]``;
* ``hsync-server`` — ``--host HOST[:PORT]`` bind option.

Grammar:

* ``host`` / ``IPv4`` / ``host:port`` / ``IPv4:port``;
* ``[IPv6]`` / ``[IPv6]:port`` (bracketed IPv6 may carry a port);
* a bare IPv6 literal (more than one ``:``, unbracketed) is a host with no port.

The port, when present, must be an integer in ``1..65535``. URL-like input
(``://`` or a path) is rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from hsync_common.constants import HOSTNAME_PATTERN

__all__ = [
    "HostPort",
    "build_https_url",
    "build_url",
    "format_authority",
    "parse_host_port",
    "parse_https_url",
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

    Consumers: ``hsync-client`` (CLI ``_build_server_url`` and the ``HSYNC_SERVER``
    environment validator), ``hsync-desktop`` (settings normalization).
    """
    port = hp.port if hp.port is not None else default_port
    return f"https://{_authority_of(hp.host)}:{port}"


# URL-like HTTPS base accepted for ``HSYNC_SERVER``: scheme + (IPv6-aware)
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

    Consumers: ``hsync-client`` (``HSYNC_SERVER`` validator), ``hsync-desktop``
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
