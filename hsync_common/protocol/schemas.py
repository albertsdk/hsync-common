# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
JSON Schema contracts for the WebSocket and LAN/mDNS channels.

Companion to the REST OpenAPI snapshot: this module builds the WS and LAN/TXT
schemas *from the Python source of truth* — the handshake constants/capabilities
and the shared event/file models — so the committed snapshots under ``ws/`` and
``lan/`` can never silently drift from the code.
Regenerate them with ``scripts/export_protocol_schemas.py`` and guard them
with the matching drift-check test.

JSON Schema (draft 2020-12) is used for both channels — the alternative the
design review allows over an AsyncAPI/YAML document — to avoid extra runtime
dependencies and to mirror the existing REST JSON contract exactly.
"""

from __future__ import annotations

from typing import Any

from hsync_common.models.event import EventName
from hsync_common.models.file import FileDict

from .handshake import (
    PROTOCOL_VERSION_LAN,
    PROTOCOL_VERSION_WS,
    Capability,
    encode_capabilities,
)

__all__ = [
    "JSON_SCHEMA_DIALECT",
    "LAN_TXT_KEYS",
    "LAN_TXT_OPTIONAL_KEYS",
    "LAN_TXT_REQUIRED_KEYS",
    "build_lan_txt_schema",
    "build_lan_wss_schema",
    "build_ws_schema",
]

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

# Canonical mDNS/TXT keys advertised on the LAN channel — single source of truth
# for ``lan/txt-schema.json``. Boolean flags are advertised only when true.
LAN_TXT_REQUIRED_KEYS: tuple[str, ...] = (
    "cid",
    "bucket",
    "version",
    "protocol",
    "startup_time",
    "sync_direction",
)
LAN_TXT_OPTIONAL_KEYS: tuple[str, ...] = (
    "group",
    "https",
    "cert_fp",
    "compression",
    "delta",
    "vector_clocks",
    "tombstones",
    "server_ready",
    "force_master",
    "never_master",
    "connected",
)
LAN_TXT_KEYS: tuple[str, ...] = LAN_TXT_REQUIRED_KEYS + LAN_TXT_OPTIONAL_KEYS

# A TXT boolean flag is a string present only when the value is true.
_TXT_BOOL_FLAG: dict[str, Any] = {"type": "string", "enum": ["true"]}


def _capability_tokens() -> list[str]:
    """Wire capability tokens, derived from the :class:`Capability` registry."""
    return encode_capabilities(Capability)


def _event_names() -> list[str]:
    """File-event discriminators, derived from :class:`EventName`."""
    return [e.value for e in EventName]


def _file_object() -> dict[str, Any]:
    """JSON Schema for a serialized :class:`File` (keys from ``FileDict``)."""
    nullable_str = {"type": ["string", "null"]}
    nullable_int = {"type": ["integer", "null"]}
    return {
        "type": "object",
        "title": "File",
        "properties": {
            "filepath": nullable_str,
            "name": nullable_str,
            "ctime": nullable_int,
            "mtime": nullable_int,
            "size": {"type": "integer"},
            "sha256sum": nullable_str,
            "permissions": nullable_str,
            "version": {
                "type": "object",
                "title": "VersionInfo",
                "description": (
                    "Causal version metadata joined from the version store "
                    "(ADR-0022). Optional: absent ⇒ empty vector clock."
                ),
                "properties": {
                    "vclock": {
                        "type": "object",
                        "additionalProperties": {"type": "integer", "minimum": 0},
                        "description": "Node cid → logical counter.",
                    },
                    "version_id": {"type": "string"},
                    "origin_cid": {"type": ["string", "null"]},
                    "ts": {"type": ["integer", "null"]},
                    "corrected_mtime": {
                        "type": "integer",
                        "description": (
                            "Clock-offset-corrected modification time used as the "
                            "chronological tie-break on concurrent divergence "
                            "(ADR-0023). 0 or absent ⇒ unknown, hash fallback."
                        ),
                    },
                },
                "required": ["vclock", "version_id", "origin_cid", "ts"],
                "additionalProperties": False,
            },
        },
        "required": sorted(FileDict.__required_keys__),
        "additionalProperties": False,
    }


def _dir_object() -> dict[str, Any]:
    """JSON Schema for a serialized :class:`Dir`."""
    return {
        "type": "object",
        "title": "Dir",
        "properties": {
            "path": {"type": ["string", "null"]},
            "permissions": {"type": ["string", "null"]},
            "recursive": {
                "type": "boolean",
                "description": (
                    "On a `deleted` event the directory deletion applies "
                    "recursively (single message replaces the per-descendant "
                    "delete stream). Optional: absent ⇒ non-recursive."
                ),
            },
        },
        "required": ["path", "permissions"],
        "additionalProperties": False,
    }


def _symlink_object() -> dict[str, Any]:
    """JSON Schema for a serialized :class:`Symlink`."""
    return {
        "type": "object",
        "title": "Symlink",
        "properties": {
            "type": {"const": "symlink"},
            "filepath": {"type": ["string", "null"]},
            "name": {"type": ["string", "null"]},
            "target": {"type": ["string", "null"]},
            "ctime": {"type": ["number", "null"]},
            "mtime": {"type": ["number", "null"]},
        },
        "required": ["type", "filepath", "name", "target"],
        "additionalProperties": False,
    }


def _event_message() -> dict[str, Any]:
    """JSON Schema for a file-system event frame (``EventDict``, both ways)."""
    return {
        "type": "object",
        "title": "FileEvent",
        "description": "File-system event exchanged over the WebSocket (EventDict).",
        "properties": {
            "cid": {"type": "string"},
            "name": {"enum": _event_names()},
            "bucket": {"type": "string"},
            "src": {"$ref": "#/$defs/entity"},
            "dst": {"oneOf": [{"$ref": "#/$defs/entity"}, {"type": "null"}]},
        },
        "required": ["cid", "name", "bucket", "src"],
        "additionalProperties": False,
    }


def _auth_request() -> dict[str, Any]:
    """Client → server authentication frame (``WsAuthRequest``)."""
    return {
        "type": "object",
        "title": "AuthRequest",
        "properties": {
            "type": {"const": "auth"},
            "token": {"type": "string"},
            "app_version": {"type": "string"},
            "protocol_version": {"const": PROTOCOL_VERSION_WS},
            "capabilities": {
                "type": "array",
                "items": {"enum": _capability_tokens()},
                "uniqueItems": True,
            },
        },
        "required": ["type", "token", "app_version", "protocol_version", "capabilities"],
        "additionalProperties": False,
    }


def _auth_ok() -> dict[str, Any]:
    """Server → client successful auth reply (``WsAuthResponse`` ok)."""
    return {
        "type": "object",
        "title": "AuthOk",
        "properties": {
            "type": {"const": "auth"},
            "status": {"const": "ok"},
            "protocol_version": {"const": PROTOCOL_VERSION_WS},
            "app_version": {"type": "string"},
            "capabilities": {
                "type": "array",
                "items": {"enum": _capability_tokens()},
                "uniqueItems": True,
            },
        },
        "required": ["type", "status", "protocol_version", "app_version", "capabilities"],
        "additionalProperties": False,
    }


def _auth_error() -> dict[str, Any]:
    """Server → client auth rejection (``WsAuthResponse`` error)."""
    return {
        "type": "object",
        "title": "AuthError",
        "properties": {
            "type": {"const": "auth"},
            "status": {"const": "error"},
            "protocol_version": {"const": PROTOCOL_VERSION_WS},
            "error": {"type": "string"},
            "client_protocol_version": {"type": "string"},
        },
        "required": ["type", "status", "protocol_version", "error", "client_protocol_version"],
        "additionalProperties": False,
    }


def _heartbeat(kind: str) -> dict[str, Any]:
    """Heartbeat frame schema (``ping`` from server, ``pong`` from client)."""
    return {
        "type": "object",
        "title": kind.capitalize(),
        "properties": {"type": {"const": kind}},
        "required": ["type"],
        "additionalProperties": False,
    }


def _presence() -> dict[str, Any]:
    """Server → client presence frame (``WsPresenceFrame``)."""
    return {
        "type": "object",
        "title": "Presence",
        "properties": {
            "type": {"const": "presence"},
            "connected": {"type": "integer", "minimum": 0},
            "total": {"type": "integer", "minimum": 0},
        },
        "required": ["type", "connected", "total"],
        "additionalProperties": False,
    }


def build_ws_schema() -> dict[str, Any]:
    """Build the WebSocket channel JSON Schema from the Python source of truth."""
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": f"https://hsync.dev/protocol/{PROTOCOL_VERSION_WS}",
        "title": f"HSYNC WebSocket protocol ({PROTOCOL_VERSION_WS})",
        "description": (
            "Wire contract for the real-time event WebSocket. Generated from "
            "hsync_common.protocol.schemas; do not hand-edit."
        ),
        "$defs": {
            "file": _file_object(),
            "dir": _dir_object(),
            "symlink": _symlink_object(),
            "entity": {
                "oneOf": [
                    {"$ref": "#/$defs/file"},
                    {"$ref": "#/$defs/dir"},
                    {"$ref": "#/$defs/symlink"},
                ]
            },
            "authRequest": _auth_request(),
            "authOk": _auth_ok(),
            "authError": _auth_error(),
            "ping": _heartbeat("ping"),
            "pong": _heartbeat("pong"),
            "presence": _presence(),
            "fileEvent": _event_message(),
        },
        "clientToServer": {
            "oneOf": [
                {"$ref": "#/$defs/authRequest"},
                {"$ref": "#/$defs/pong"},
                {"$ref": "#/$defs/fileEvent"},
            ]
        },
        "serverToClient": {
            "oneOf": [
                {"$ref": "#/$defs/authOk"},
                {"$ref": "#/$defs/authError"},
                {"$ref": "#/$defs/ping"},
                {"$ref": "#/$defs/presence"},
                {"$ref": "#/$defs/fileEvent"},
            ]
        },
    }


def _lan_capabilities() -> dict[str, Any]:
    """LAN-WSS capabilities list (same registry tokens as the WS channel)."""
    return {
        "type": "array",
        "items": {"enum": _capability_tokens()},
        "uniqueItems": True,
    }


def _lan_auth_required() -> dict[str, Any]:
    """LAN master → slave greeting frame (``LanAuthRequiredFrame``)."""
    return {
        "type": "object",
        "title": "LanAuthRequired",
        "properties": {
            "type": {"const": "auth_required"},
            "protocol_version": {"const": PROTOCOL_VERSION_LAN},
            "capabilities": _lan_capabilities(),
        },
        "required": ["type", "protocol_version", "capabilities"],
        "additionalProperties": False,
    }


def _lan_auth() -> dict[str, Any]:
    """LAN slave → master auth frame (``LanAuthFrame``)."""
    return {
        "type": "object",
        "title": "LanAuth",
        "properties": {
            "type": {"const": "auth"},
            "token": {"type": "string"},
            "cid": {"type": "string"},
            "protocol_version": {"const": PROTOCOL_VERSION_LAN},
            "capabilities": _lan_capabilities(),
        },
        "required": ["type", "token", "cid", "protocol_version", "capabilities"],
        "additionalProperties": False,
    }


def _lan_auth_result(kind: str) -> dict[str, Any]:
    """LAN master → slave auth reply (``LanAuthResultFrame`` ok/failed)."""
    success = kind == "ok"
    properties: dict[str, Any] = {
        "type": {"const": "auth"},
        "status": {"const": kind},
        "protocol_version": {"const": PROTOCOL_VERSION_LAN},
    }
    required = ["type", "status", "protocol_version"]
    if success:
        properties["capabilities"] = _lan_capabilities()
        required.append("capabilities")
    else:
        properties["reason"] = {"type": "string"}
        required.append("reason")
    return {
        "type": "object",
        "title": f"LanAuth{'Ok' if success else 'Failed'}",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _lan_hello() -> dict[str, Any]:
    """LAN hello frame, both directions (``LanHelloFrame``)."""
    return {
        "type": "object",
        "title": "LanHello",
        "properties": {
            "type": {"const": "hello"},
            "protocol_version": {"const": PROTOCOL_VERSION_LAN},
            "capabilities": _lan_capabilities(),
            "cid": {"type": "string"},
        },
        "required": ["type", "protocol_version", "capabilities"],
        "additionalProperties": False,
    }


def build_lan_wss_schema() -> dict[str, Any]:
    """Build the LAN WebSocket handshake JSON Schema from the Python SSOT.

    Codifies the master⇄slave handshake frames (ADR-0024): they exchange the
    capability registry over the authenticated channel, so the mDNS/TXT record
    is not the only capability source on the LAN.
    """
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": f"https://hsync.dev/protocol/{PROTOCOL_VERSION_LAN}/wss",
        "title": f"HSYNC LAN WebSocket handshake ({PROTOCOL_VERSION_LAN})",
        "description": (
            "Wire contract for the LAN master⇄slave WebSocket handshake "
            "(ADR-0024). Generated from hsync_common.protocol.schemas; "
            "do not hand-edit."
        ),
        "$defs": {
            "file": _file_object(),
            "dir": _dir_object(),
            "symlink": _symlink_object(),
            "entity": {
                "oneOf": [
                    {"$ref": "#/$defs/file"},
                    {"$ref": "#/$defs/dir"},
                    {"$ref": "#/$defs/symlink"},
                ]
            },
            "authRequired": _lan_auth_required(),
            "auth": _lan_auth(),
            "authOk": _lan_auth_result("ok"),
            "authFailed": _lan_auth_result("failed"),
            "hello": _lan_hello(),
            "fileEvent": _event_message(),
        },
        "masterToSlave": {
            "oneOf": [
                {"$ref": "#/$defs/authRequired"},
                {"$ref": "#/$defs/authOk"},
                {"$ref": "#/$defs/authFailed"},
                {"$ref": "#/$defs/hello"},
                {"$ref": "#/$defs/fileEvent"},
            ]
        },
        "slaveToMaster": {
            "oneOf": [
                {"$ref": "#/$defs/auth"},
                {"$ref": "#/$defs/hello"},
                {"$ref": "#/$defs/fileEvent"},
            ]
        },
    }


def build_lan_txt_schema() -> dict[str, Any]:
    """Build the LAN/mDNS TXT-record JSON Schema from the Python source of truth."""
    properties: dict[str, Any] = {
        "cid": {"type": "string"},
        "bucket": {"type": "string"},
        "version": {"type": "string", "description": "Semantic app version (informational)."},
        "protocol": {"const": PROTOCOL_VERSION_LAN},
        "startup_time": {
            "type": "string",
            "pattern": r"^[0-9]+(\.[0-9]+)?$",
            "description": "Unix start time; earlier wins master election.",
        },
        "sync_direction": {"type": "string"},
        "group": {"type": "string"},
        "https": _TXT_BOOL_FLAG,
        "cert_fp": {"type": "string", "description": "TLS certificate fingerprint."},
        "compression": _TXT_BOOL_FLAG,
        "delta": _TXT_BOOL_FLAG,
        "vector_clocks": _TXT_BOOL_FLAG,
        "tombstones": _TXT_BOOL_FLAG,
        "server_ready": _TXT_BOOL_FLAG,
        "force_master": _TXT_BOOL_FLAG,
        "never_master": _TXT_BOOL_FLAG,
        "connected": {
            "type": "string",
            "pattern": r"^[0-9]+$",
            "description": (
                "Count of clients currently connected to this bucket's share "
                "(master included). Present only on a serving master; "
                "informational, never part of the election."
            ),
        },
    }
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": f"https://hsync.dev/protocol/{PROTOCOL_VERSION_LAN}",
        "title": f"HSYNC LAN mDNS/TXT record ({PROTOCOL_VERSION_LAN})",
        "description": (
            "Contract for the mDNS service TXT record. All values are strings "
            "(mDNS encoding). Generated from hsync_common.protocol.schemas."
        ),
        "type": "object",
        "properties": properties,
        "required": list(LAN_TXT_REQUIRED_KEYS),
        "additionalProperties": False,
    }
