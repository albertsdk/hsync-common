# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
JSON Schema contracts for the WebSocket and LAN/mDNS channels.

Companion to the REST OpenAPI snapshot (DESIGN_REVIEW §1 / P0-A, Fase 3): this
module builds the WS and LAN/TXT schemas *from the Python source of truth* — the
handshake constants/capabilities and the shared event/file models — so the
committed snapshots under ``ws/`` and ``lan/`` can never silently drift from the
code. Regenerate them with ``scripts/export_protocol_schemas.py`` and guard them
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
    "server_ready",
    "force_master",
    "never_master",
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
        },
        "required": list(FileDict.__annotations__),
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
        "server_ready": _TXT_BOOL_FLAG,
        "force_master": _TXT_BOOL_FLAG,
        "never_master": _TXT_BOOL_FLAG,
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
