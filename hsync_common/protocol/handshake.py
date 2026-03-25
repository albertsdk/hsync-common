# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Versioned handshake contract shared by every HSYNC component.

This is the single source of truth for the *protocol version* — deliberately
separate from the semantic app version — and for the *capability registry*.
Server and clients import the constants and the ``build_*``/``parse_*``
helpers from here instead of re-spelling the handshake payloads by hand on
each side (REST header, WebSocket auth frame, LAN/TXT).

Because there is no legacy install base to support, a ``protocol_version`` that
differs from the peer's is a *hard failure*: capabilities are only feature flags
*within* the same protocol version, never a cross-version negotiation mechanism.

The LAN WebSocket channel (master ⇄ slave) reuses the same capability registry:
the master advertises it in the connect-time handshake (greeting/auth reply) so
peers learn each other's capabilities over an **authenticated** channel instead
of relying on the unauthenticated mDNS/TXT record alone (ADR-0024).
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any, NotRequired, TypedDict

__all__ = [
    "PROTOCOL_VERSION_LAN",
    "PROTOCOL_VERSION_REST",
    "PROTOCOL_VERSION_WS",
    "Capability",
    "ALL_CAPABILITIES",
    "WsAuthRequest",
    "WsAuthResponse",
    "WsPresenceFrame",
    "LanAuthRequiredFrame",
    "LanAuthFrame",
    "LanAuthResultFrame",
    "LanHelloFrame",
    "encode_capabilities",
    "decode_capabilities",
    "build_ws_auth_request",
    "build_ws_auth_ok",
    "build_ws_auth_error",
    "build_ws_presence",
    "build_lan_auth_required",
    "build_lan_auth",
    "build_lan_auth_ok",
    "build_lan_auth_failed",
    "build_lan_hello",
]

# Per-channel protocol versions. Bump the channel suffix on any breaking change
# to that channel's wire shape; the matching peer then hard-fails the handshake.
PROTOCOL_VERSION_REST = "api/1"
PROTOCOL_VERSION_WS = "ws/1"
PROTOCOL_VERSION_LAN = "lan/1"


class Capability(StrEnum):
    """Registry of optional features advertised during the handshake.

    Values are the exact on-the-wire tokens shared across REST/WS/LAN and the
    Android client; treat them as stable identifiers, not display strings.

    Consumers: server (WS auth reply, ``build_ws_auth_ok``), clients
    (``decode_capabilities`` on the auth reply and LAN TXT record), Android
    (``Protocol.kt`` ``KNOWN_CAPABILITIES`` mirror), desktop (``--capabilities-json``
    output parsing). ``vector_clocks`` advertises causal version-metadata support
    (ADR-0022): peers that do not advertise it simply omit the ``version`` field
    on file payloads and the receiver treats it as an empty clock — no legacy
    fallback path.
    """

    compression = "compression"  # zstd-compressed file transfers
    tombstones = "tombstones"  # deletion markers to avoid resurrecting files
    never_master = "never_master"  # node refuses LAN master election
    https = "https"  # TLS-secured master endpoint
    delta = "delta"  # rsync-style delta transfer (block-level sync)
    vector_clocks = "vector_clocks"  # causal version metadata exchanged on file payloads (ADR-0022)
    peer_download = "peer_download"  # LAN inventory, source lookup and seeder semantics (ADR-0028)


ALL_CAPABILITIES: frozenset[Capability] = frozenset(Capability)

# Precomputed value -> Capability lookup for decode_capabilities (built once at
# import instead of rebuilding the dict on every handshake decode).
_CAPABILITY_BY_VALUE: dict[str, Capability] = {c.value: c for c in Capability}


def encode_capabilities(capabilities: Iterable[Capability | str]) -> list[str]:
    """Serialize capabilities to a sorted, de-duplicated list of wire tokens."""
    return sorted({str(c) for c in capabilities})


def decode_capabilities(values: Any) -> set[Capability]:
    """Parse a wire capability list into known :class:`Capability` members.

    Unknown tokens are dropped silently: an unrecognised capability is simply a
    feature this peer does not understand, never a protocol-version mismatch.
    """
    if not isinstance(values, (list, tuple, set, frozenset)):
        return set()
    return {
        _CAPABILITY_BY_VALUE[v] for v in values if isinstance(v, str) and v in _CAPABILITY_BY_VALUE
    }


class WsAuthRequest(TypedDict):
    """Client → server first WebSocket frame (authentication)."""

    type: str  # always "auth"
    token: str
    app_version: str
    protocol_version: str
    capabilities: list[str]


class WsAuthResponse(TypedDict):
    """Server → client WebSocket auth reply (ok or error)."""

    type: str  # always "auth"
    status: str  # "ok" | "error"
    protocol_version: str
    app_version: NotRequired[str]
    capabilities: NotRequired[list[str]]
    error: NotRequired[str]
    client_protocol_version: NotRequired[str]


def build_ws_auth_request(
    *, token: str, app_version: str, capabilities: Iterable[Capability | str]
) -> WsAuthRequest:
    """Build the client's WebSocket auth frame with protocol + capabilities."""
    return {
        "type": "auth",
        "token": token,
        "app_version": app_version,
        "protocol_version": PROTOCOL_VERSION_WS,
        "capabilities": encode_capabilities(capabilities),
    }


def build_ws_auth_ok(
    *, app_version: str, capabilities: Iterable[Capability | str]
) -> WsAuthResponse:
    """Build the server's successful WebSocket auth reply."""
    return {
        "type": "auth",
        "status": "ok",
        "protocol_version": PROTOCOL_VERSION_WS,
        "app_version": app_version,
        "capabilities": encode_capabilities(capabilities),
    }


def build_ws_auth_error(*, error: str, client_protocol_version: str) -> WsAuthResponse:
    """Build the server's WebSocket auth rejection (e.g. protocol mismatch)."""
    return {
        "type": "auth",
        "status": "error",
        "protocol_version": PROTOCOL_VERSION_WS,
        "error": error,
        "client_protocol_version": client_protocol_version,
    }


class WsPresenceFrame(TypedDict):
    """Server → client presence frame, broadcast to a bucket's connected clients.

    Carries the display-ready presence counters for the bucket: ``connected``
    is the number of accounts currently connected (self included), ``total``
    is the number of clients that have access to the bucket. Both are always
    present and ``connected <= total``.
    """

    type: str  # always "presence"
    connected: int  # accounts currently connected (self included)
    total: int  # accounts with access to the bucket (self included)


def build_ws_presence(*, connected: int, total: int) -> WsPresenceFrame:
    """Build the server's presence frame for a bucket."""
    return {
        "type": "presence",
        "connected": connected,
        "total": total,
    }


class LanAuthRequiredFrame(TypedDict):
    """LAN master → slave first frame (``auth_required`` greeting).

    Carries the LAN protocol version and the master's capabilities so the auth
    path and the unauthenticated ``hello`` path exchange the same information
    (ADR-0024).
    """

    type: str  # always "auth_required"
    protocol_version: str
    capabilities: list[str]


class LanAuthFrame(TypedDict):
    """LAN slave → master authentication frame."""

    type: str  # always "auth"
    token: str
    cid: str
    protocol_version: str
    capabilities: list[str]


class LanAuthResultFrame(TypedDict):
    """LAN master → slave auth reply (``ok`` or ``failed``)."""

    type: str  # always "auth"
    status: str  # "ok" | "failed"
    protocol_version: str
    capabilities: NotRequired[list[str]]
    reason: NotRequired[str]


class LanHelloFrame(TypedDict):
    """LAN hello frame (both directions on the unauthenticated path).

    The master greets with ``{"type": "hello", protocol_version, capabilities}``
    and the slave replies with the same shape plus its ``cid``. The CID is a
    logging hint only when no ``LAN_KEY`` is configured.
    """

    type: str  # always "hello"
    protocol_version: str
    capabilities: list[str]
    cid: NotRequired[str]


def build_lan_auth_required(*, capabilities: Iterable[Capability | str]) -> LanAuthRequiredFrame:
    """Build the LAN master's ``auth_required`` greeting frame."""
    return {
        "type": "auth_required",
        "protocol_version": PROTOCOL_VERSION_LAN,
        "capabilities": encode_capabilities(capabilities),
    }


def build_lan_auth(
    *, token: str, cid: str, capabilities: Iterable[Capability | str]
) -> LanAuthFrame:
    """Build the LAN slave's authentication frame."""
    return {
        "type": "auth",
        "token": token,
        "cid": cid,
        "protocol_version": PROTOCOL_VERSION_LAN,
        "capabilities": encode_capabilities(capabilities),
    }


def build_lan_auth_ok(*, capabilities: Iterable[Capability | str]) -> LanAuthResultFrame:
    """Build the LAN master's successful auth reply."""
    return {
        "type": "auth",
        "status": "ok",
        "protocol_version": PROTOCOL_VERSION_LAN,
        "capabilities": encode_capabilities(capabilities),
    }


def build_lan_auth_failed(*, reason: str) -> LanAuthResultFrame:
    """Build the LAN master's auth rejection frame."""
    return {
        "type": "auth",
        "status": "failed",
        "protocol_version": PROTOCOL_VERSION_LAN,
        "reason": reason,
    }


def build_lan_hello(
    *, capabilities: Iterable[Capability | str], cid: str | None = None
) -> LanHelloFrame:
    """Build a LAN hello frame (master greeting or slave reply with ``cid``)."""
    frame: LanHelloFrame = {
        "type": "hello",
        "protocol_version": PROTOCOL_VERSION_LAN,
        "capabilities": encode_capabilities(capabilities),
    }
    if cid is not None:
        frame["cid"] = cid
    return frame
