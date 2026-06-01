# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Versioned handshake contract shared by every HSYNC component.

This is the single source of truth (DESIGN_REVIEW §1 / P0-A, Fase 2) for the
*protocol version* — deliberately separate from the semantic app version — and
for the *capability registry*. Server and clients import the constants and the
``build_*``/``parse_*`` helpers from here instead of re-spelling the handshake
payloads by hand on each side (REST header, WebSocket auth frame, LAN/TXT).

Because there is no legacy install base to support, a ``protocol_version`` that
differs from the peer's is a *hard failure*: capabilities are only feature flags
*within* the same protocol version, never a cross-version negotiation mechanism.
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
    "encode_capabilities",
    "decode_capabilities",
    "build_ws_auth_request",
    "build_ws_auth_ok",
    "build_ws_auth_error",
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
    """

    compression = "compression"  # zstd-compressed file transfers
    tombstones = "tombstones"  # deletion markers to avoid resurrecting files
    never_master = "never_master"  # node refuses LAN master election
    https = "https"  # TLS-secured master endpoint


ALL_CAPABILITIES: frozenset[Capability] = frozenset(Capability)


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
    known = {c.value: c for c in Capability}
    return {known[v] for v in values if isinstance(v, str) and v in known}


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
