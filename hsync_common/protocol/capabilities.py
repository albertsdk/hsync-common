# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Binary-capabilities document emitted by ``hsync --capabilities-json``.

This is the single source of truth for the JSON document the client prints so a
parent process (the Desktop GUI) can drive its UI from the *binary's* declared
capabilities instead of coupling to a specific CLI/Semver contract. The document
bundles, in one versioned payload:

* the supported CLI subcommands (``p2p``, ``server``, ``trust``),
* the per-subcommand supported CLI option flags (introspected by the client
  from its own commands, so the lists can never drift from the real interface),
* the per-channel ``protocol_version`` (REST/WS/p2p/boot) from the handshake SSOT,
* the structured-events ``schema_version`` (the ``--events-json-fd`` channel),
* the feature-flag ``capabilities`` registry (the same wire tokens used in the
  handshake).

The Desktop hard-fails (ignores the document) on an unknown ``schema_version``
rather than mis-reading it: there is no legacy channel to fall back to.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, TypedDict

from .bootnode import PROTOCOL_VERSION_BOOT
from .events import EVENTS_SCHEMA_VERSION
from .handshake import (
    ALL_CAPABILITIES,
    PROTOCOL_VERSION_P2P,
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
    "supports_subcommand",
]

# Bump only on a breaking change to the document shape below. The consumer
# rejects any other version outright (see ``parse_capabilities``).
CAPABILITIES_SCHEMA_VERSION = 3


class ProtocolVersions(TypedDict):
    """Per-channel protocol versions advertised by the binary."""

    rest: str
    ws: str
    p2p: str
    boot: str


class CapabilitiesDoc(TypedDict):
    """Type-safe shape of the ``--capabilities-json`` document."""

    schema_version: int
    app_version: str
    protocol_version: ProtocolVersions
    events_schema_version: int
    capabilities: list[str]
    subcommands: list[str]
    cli_options: dict[str, list[str]]


def build_capabilities(
    *,
    app_version: str,
    subcommands: Iterable[str],
    cli_options_by_subcommand: dict[str, Iterable[str]],
    capabilities: Iterable[Capability | str] | None = None,
) -> CapabilitiesDoc:
    """Assemble the capabilities document from the shared protocol SSOT.

    Args:
        app_version: The binary's semantic version (distinct from the protocol).
        subcommands: The supported CLI subcommands (e.g. ``["p2p", "server", "trust"]``).
            Listed explicitly (not derived from ``cli_options_by_subcommand``
            keys) so a subcommand exposing no options stays discoverable.
        cli_options_by_subcommand: The supported CLI option flags per
            subcommand (e.g. ``{"p2p": ["--never-master"], "server":
            ["--ca-cert"]}``).
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
            "p2p": PROTOCOL_VERSION_P2P,
            "boot": PROTOCOL_VERSION_BOOT,
        },
        "events_schema_version": EVENTS_SCHEMA_VERSION,
        "capabilities": encode_capabilities(caps),
        "subcommands": sorted({str(s) for s in subcommands}),
        "cli_options": {
            subcommand: sorted({str(o) for o in flags})
            for subcommand, flags in sorted(cli_options_by_subcommand.items())
        },
    }


# Keys that must be present for a document to be considered well-formed.
_REQUIRED_KEYS = frozenset(CapabilitiesDoc.__annotations__)


def parse_capabilities(text: str) -> CapabilitiesDoc | None:
    """Parse and validate a capabilities document.

    Returns ``None`` for blank input, malformed JSON, a non-object payload, an
    unsupported ``schema_version``, a missing required key or a required key
    holding a value of the wrong type (e.g. ``cli_options`` as a plain string
    would make ``supports_cli_option`` silently mis-answer) — the caller treats
        any of these as "capabilities unknown" and degrades to a best-effort UI.
    """
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
    if not _field_types_valid(data):
        return None
    return data  # type: ignore[return-value]


def _field_types_valid(data: dict[str, Any]) -> bool:
    """Type-check the fields a consumer relies on.

    Key presence alone is not enough: the document travels across a process
    boundary (client binary → desktop GUI), so a producer bug or a hostile
    payload must be rejected here rather than mis-parsed downstream.
    """
    protocol = data["protocol_version"]
    if not isinstance(protocol, dict) or not all(
        isinstance(protocol.get(channel), str) for channel in ("rest", "ws", "p2p", "boot")
    ):
        return False
    if not isinstance(data["app_version"], str):
        return False
    # bool is an int subclass: reject it explicitly for the version field.
    if not isinstance(data["events_schema_version"], int) or isinstance(
        data["events_schema_version"], bool
    ):
        return False
    capabilities = data["capabilities"]
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) for item in capabilities
    ):
        return False
    subcommands = data["subcommands"]
    if not isinstance(subcommands, list) or not all(isinstance(item, str) for item in subcommands):
        return False
    cli_options = data["cli_options"]
    if not isinstance(cli_options, dict):
        return False
    for flags in cli_options.values():
        if not isinstance(flags, list) or not all(isinstance(item, str) for item in flags):
            return False
    return True


def supports_cli_option(
    doc: CapabilitiesDoc | dict[str, Any] | None,
    flag: str,
    subcommand: str | None = None,
) -> bool:
    """Return whether ``flag`` (e.g. ``--never-master``) is in the document.

    With ``subcommand`` the check is scoped to that subcommand's option list;
    without it the union of every subcommand's list is considered. A
    missing/None document means "unknown", which conservatively reports
    ``True`` so the consumer does not hide a control it cannot prove is absent.
    """
    if doc is None:
        return True
    cli_options = doc.get("cli_options", {})
    if subcommand is not None:
        return flag in cli_options.get(subcommand, ())
    return any(flag in flags for flags in cli_options.values())


def supports_subcommand(
    doc: CapabilitiesDoc | dict[str, Any] | None,
    name: str,
) -> bool:
    """Return whether the binary advertises the ``name`` subcommand.

    A missing/None document means "unknown", which conservatively reports
    ``True`` so the consumer does not hide a control it cannot prove is absent.
    """
    if doc is None:
        return True
    return name in doc.get("subcommands", ())
