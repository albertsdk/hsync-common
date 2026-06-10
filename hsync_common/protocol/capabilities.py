# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Binary-capabilities document emitted by ``hsync --capabilities-json``.

This is the single source of truth for the JSON document the client prints so a
parent process (the Desktop GUI) can drive its UI from the *binary's* declared
capabilities instead of coupling to a specific CLI/Semver contract. The document
bundles, in one versioned payload:

* the supported CLI option flags (introspected by the client from its own
  command, so the list can never drift from the real interface),
* the per-channel ``protocol_version`` (REST/WS/LAN) from the handshake SSOT,
* the structured-events ``schema_version`` (the ``--events-json-fd`` channel),
* the feature-flag ``capabilities`` registry (the same wire tokens used in the
  handshake).

The Desktop hard-fails (ignores the document) on an unknown ``schema_version``
rather than mis-reading it: there is no legacy channel to fall back to.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypedDict

from .events import EVENTS_SCHEMA_VERSION
from .handshake import (
    ALL_CAPABILITIES,
    PROTOCOL_VERSION_LAN,
    PROTOCOL_VERSION_REST,
    PROTOCOL_VERSION_WS,
    Capability,
    encode_capabilities,
)

__all__ = [
    "CAPABILITIES_SCHEMA_VERSION",
    "CapabilitiesDoc",
    "ProtocolVersions",
    "build_capabilities",
    "parse_capabilities",
    "supports_cli_option",
]

# Bump only on a breaking change to the document shape below. The consumer
# rejects any other version outright (see ``parse_capabilities``).
CAPABILITIES_SCHEMA_VERSION = 1


class ProtocolVersions(TypedDict):
    """Per-channel protocol versions advertised by the binary."""

    rest: str
    ws: str
    lan: str


class CapabilitiesDoc(TypedDict):
    """Type-safe shape of the ``--capabilities-json`` document."""

    schema_version: int
    app_version: str
    protocol_version: ProtocolVersions
    events_schema_version: int
    capabilities: list[str]
    cli_options: list[str]


def build_capabilities(
    *,
    app_version: str,
    cli_options: Iterable[str],
    capabilities: Iterable[Capability | str] | None = None,
) -> CapabilitiesDoc:
    """Assemble the capabilities document from the shared protocol SSOT.

    Args:
        app_version: The binary's semantic version (distinct from the protocol).
        cli_options: The supported CLI option flags (e.g. ``--never-master``).
        capabilities: Advertised feature flags; defaults to every known
            :class:`Capability`.
    """
    caps = ALL_CAPABILITIES if capabilities is None else capabilities
    return {
        "schema_version": CAPABILITIES_SCHEMA_VERSION,
        "app_version": app_version,
        "protocol_version": {
            "rest": PROTOCOL_VERSION_REST,
            "ws": PROTOCOL_VERSION_WS,
            "lan": PROTOCOL_VERSION_LAN,
        },
        "events_schema_version": EVENTS_SCHEMA_VERSION,
        "capabilities": encode_capabilities(caps),
        "cli_options": sorted({str(o) for o in cli_options}),
    }


# Keys that must be present for a document to be considered well-formed.
_REQUIRED_KEYS = frozenset(CapabilitiesDoc.__annotations__)


def parse_capabilities(text: str) -> CapabilitiesDoc | None:
    """Parse and validate a capabilities document.

    Returns ``None`` for blank input, malformed JSON, a non-object payload, an
    unsupported ``schema_version`` or a missing required key — the caller treats
    any of these as "capabilities unknown" and degrades to a best-effort UI.
    """
    import json

    stripped = text.strip()
    if not stripped:
        return None
    try:
        data = json.loads(stripped)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != CAPABILITIES_SCHEMA_VERSION:
        return None
    if not _REQUIRED_KEYS.issubset(data):
        return None
    return data  # type: ignore[return-value]


def supports_cli_option(doc: CapabilitiesDoc | dict[str, Any] | None, flag: str) -> bool:
    """Return whether ``flag`` (e.g. ``--never-master``) is in the document.

    A missing/None document means "unknown", which conservatively reports
    ``True`` so the consumer does not hide a control it cannot prove is absent.
    """
    if doc is None:
        return True
    return flag in doc.get("cli_options", ())
