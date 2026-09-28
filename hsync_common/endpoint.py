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

from hsync_common.constants import HOSTNAME_PATTERN

__all__ = ["HostPort", "parse_host_port"]

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
