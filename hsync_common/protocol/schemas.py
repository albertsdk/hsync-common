# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
JSON Schema contracts for the WebSocket and LAN/mDNS channels.

Companion to the REST OpenAPI snapshot: this module builds the WS, LAN TXT/WSS,
and LAN peer-source payload schemas *from the Python source of truth* — the
handshake constants/capabilities, peer-download bounds, and shared event/file
models — so the committed snapshots under ``ws/`` and ``lan/`` cannot silently
drift from the code.
Regenerate them with ``scripts/export_protocol_schemas.py`` and guard them
with the matching drift-check test.

JSON Schema (draft 2020-12) is used for both channels — the alternative the
design review allows over an AsyncAPI/YAML document — to avoid extra runtime
dependencies and to mirror the existing REST JSON contract exactly.
"""

from __future__ import annotations

from typing import Any

from hsync_common.constants import CONTENT_TYPE_JSON
from hsync_common.models.event import CID_PATTERN, EventName
from hsync_common.models.file import FileDict
from hsync_common.path_validation import MAX_REMOTE_RELPATH_BYTES

from .handshake import (
    PROTOCOL_VERSION_LAN,
    PROTOCOL_VERSION_WS,
    Capability,
    encode_capabilities,
)
from .peer_download import (
    LAN_INVENTORY_ACK_REASON_MAX_LENGTH,
    LAN_INVENTORY_MAX_ENTRIES,
    LAN_INVENTORY_MAX_FRAME_BYTES,
    LAN_SERVE_SLOTS_MAX,
    LAN_SERVE_SLOTS_MIN,
    LAN_SOURCES_MAX_BODY_BYTES,
    LAN_SOURCES_MAX_CANDIDATES,
    LAN_SOURCES_MAX_FILES,
    LAN_WIRE_INT_MAX,
)

__all__ = [
    "JSON_SCHEMA_DIALECT",
    "LAN_TXT_KEYS",
    "LAN_TXT_OPTIONAL_KEYS",
    "LAN_TXT_REQUIRED_KEYS",
    "build_lan_sources_schema",
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
    "server_ready",
    "force_master",
    "never_master",
    "connected",
    "heartbeat",
    "peer_download",
)
LAN_TXT_KEYS: tuple[str, ...] = LAN_TXT_REQUIRED_KEYS + LAN_TXT_OPTIONAL_KEYS

# A TXT boolean flag is a string present only when the value is true.
_TXT_BOOL_FLAG: dict[str, Any] = {"type": "string", "enum": ["true"]}

# Reusable "nullable primitive" schema fragments shared by the file/dir/symlink
# object builders, so the three entity schemas cannot drift on the same shape.
_NULLABLE_STR: dict[str, Any] = {"type": ["string", "null"]}
_NULLABLE_INT: dict[str, Any] = {"type": ["integer", "null"]}
_NULLABLE_NUM: dict[str, Any] = {"type": ["number", "null"]}


def _capability_tokens() -> list[str]:
    """Wire capability tokens, derived from the :class:`Capability` registry."""
    return encode_capabilities(Capability)


def _capabilities_array() -> dict[str, Any]:
    """JSON Schema for a handshake capabilities list (WS and LAN)."""
    return {
        "type": "array",
        "items": {"enum": _capability_tokens()},
        "uniqueItems": True,
    }


def _lan_cid() -> dict[str, Any]:
    """Strict schema for the canonical 21-character LAN client ID."""
    return {
        "type": "string",
        "pattern": CID_PATTERN,
        "minLength": 21,
        "maxLength": 21,
    }


def _lan_relpath() -> dict[str, Any]:
    """Schema-level bounds for a path also checked by validate_remote_relpath."""
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": MAX_REMOTE_RELPATH_BYTES,
        "x-maxUtf8Bytes": MAX_REMOTE_RELPATH_BYTES,
        "description": (
            "Canonical bucket-relative path. Implementations additionally apply "
            "validate_remote_relpath, including its UTF-8 byte and component limits."
        ),
    }


def _lan_sha256() -> dict[str, Any]:
    """Canonical lowercase SHA-256 digest schema."""
    return {"type": "string", "pattern": r"^[0-9a-f]{64}$", "minLength": 64, "maxLength": 64}


def _lan_wire_int() -> dict[str, Any]:
    """Non-negative signed 64-bit integer used by inventory frames."""
    return {"type": "integer", "minimum": 0, "maximum": LAN_WIRE_INT_MAX}


def _lan_sources_request_file() -> dict[str, Any]:
    return {
        "type": "object",
        "title": "LanSourceFile",
        "properties": {"path": _lan_relpath(), "sha256": _lan_sha256()},
        "required": ["path", "sha256"],
        "additionalProperties": False,
    }


def _lan_serve_slots() -> dict[str, Any]:
    """Seeder concurrent-read capacity advertised on a LAN frame or candidate."""
    return {
        "type": "integer",
        "minimum": LAN_SERVE_SLOTS_MIN,
        "maximum": LAN_SERVE_SLOTS_MAX,
        "description": (
            "Concurrent peer-download response bodies this seeder accepts; the "
            "requester uses it as its per-seeder admission limit (ADR-0028)."
        ),
    }


def _lan_source_candidate() -> dict[str, Any]:
    return {
        "type": "object",
        "title": "LanSourceCandidate",
        "properties": {
            "cid": _lan_cid(),
            "download_url": {
                "type": "string",
                "format": "uri",
                "pattern": r"^https://",
                "x-host": "ip-literal",
                "x-explicitPort": True,
                "description": (
                    "Complete HTTPS /api/v1/buckets/{bucket}/files/download endpoint "
                    "with an explicit port and bracketed IPv6 literal."
                ),
            },
            "cert_fp": _lan_sha256(),
            "compression": {"type": "boolean"},
            "serve_slots": _lan_serve_slots(),
        },
        "required": ["cid", "download_url", "cert_fp", "compression", "serve_slots"],
        "additionalProperties": False,
    }


def build_lan_sources_schema() -> dict[str, Any]:
    """Build the batch LAN peer-source REST payload schema (ADR-0028).

    Consumers: hsync-client source lookup, the Android protocol mirror, the
    schema exporter, and protocol drift tests.
    """
    request_file = _lan_sources_request_file()
    response_file = {
        "type": "object",
        "title": "LanSourcesResponseFile",
        "properties": {
            "path": _lan_relpath(),
            "sha256": _lan_sha256(),
            "sources": {
                "type": "array",
                "items": {"$ref": "#/$defs/sourceCandidate"},
                "maxItems": LAN_SOURCES_MAX_CANDIDATES,
                "uniqueItems": True,
                "description": "At most one candidate per normalized CID.",
            },
        },
        "required": ["path", "sha256", "sources"],
        "additionalProperties": False,
    }
    request = {
        "type": "object",
        "title": "LanSourcesRequest",
        "properties": {
            "cid": _lan_cid(),
            "files": {
                "type": "array",
                "items": {"$ref": "#/$defs/requestFile"},
                "minItems": 1,
                "maxItems": LAN_SOURCES_MAX_FILES,
                "uniqueItems": True,
                "description": "Each normalized path occurs exactly once.",
            },
        },
        "required": ["cid", "files"],
        "additionalProperties": False,
    }
    response = {
        "type": "object",
        "title": "LanSourcesResponse",
        "properties": {
            "files": {
                "type": "array",
                "items": {"$ref": "#/$defs/responseFile"},
                "minItems": 1,
                "maxItems": LAN_SOURCES_MAX_FILES,
                "uniqueItems": True,
                "description": "Each normalized path occurs exactly once.",
            }
        },
        "required": ["files"],
        "additionalProperties": False,
    }
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": f"https://hsync.dev/protocol/{PROTOCOL_VERSION_LAN}/files/sources",
        "title": f"HSYNC LAN peer sources ({PROTOCOL_VERSION_LAN})",
        "description": (
            "Request/response contract for POST "
            "/api/v1/buckets/{bucket}/files/sources (ADR-0028). Generated from "
            "hsync_common.protocol.schemas; do not hand-edit."
        ),
        "x-contentType": CONTENT_TYPE_JSON,
        "x-maxBodyBytes": LAN_SOURCES_MAX_BODY_BYTES,
        "$defs": {
            "requestFile": request_file,
            "sourceCandidate": _lan_source_candidate(),
            "responseFile": response_file,
            "request": request,
            "response": response,
        },
        "request": {"$ref": "#/$defs/request"},
        "response": {"$ref": "#/$defs/response"},
    }


def _event_names() -> list[str]:
    """File-event discriminators, derived from :class:`EventName`."""
    return [e.value for e in EventName]


def _file_object() -> dict[str, Any]:
    """JSON Schema for a serialized :class:`File` (keys from ``FileDict``)."""
    return {
        "type": "object",
        "title": "File",
        "properties": {
            "filepath": _NULLABLE_STR,
            "name": _NULLABLE_STR,
            "ctime": _NULLABLE_INT,
            "mtime": _NULLABLE_INT,
            "size": {"type": "integer"},
            "sha256sum": _NULLABLE_STR,
            "permissions": _NULLABLE_STR,
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
                    "origin_cid": _NULLABLE_STR,
                    "ts": _NULLABLE_INT,
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
            "path": _NULLABLE_STR,
            "permissions": _NULLABLE_STR,
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
            "filepath": _NULLABLE_STR,
            "name": _NULLABLE_STR,
            "target": _NULLABLE_STR,
            "ctime": _NULLABLE_NUM,
            "mtime": _NULLABLE_NUM,
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


def _entity_defs() -> dict[str, Any]:
    """Shared ``$defs`` for the file/dir/symlink entities and the file event."""
    return {
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
        "fileEvent": _event_message(),
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
            "capabilities": _capabilities_array(),
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
            "capabilities": _capabilities_array(),
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
            **_entity_defs(),
            "authRequest": _auth_request(),
            "authOk": _auth_ok(),
            "authError": _auth_error(),
            "ping": _heartbeat("ping"),
            "pong": _heartbeat("pong"),
            "presence": _presence(),
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


def _lan_auth_required() -> dict[str, Any]:
    """LAN master → slave greeting frame (``LanAuthRequiredFrame``)."""
    return {
        "type": "object",
        "title": "LanAuthRequired",
        "properties": {
            "type": {"const": "auth_required"},
            "protocol_version": {"const": PROTOCOL_VERSION_LAN},
            "capabilities": _capabilities_array(),
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
            "capabilities": _capabilities_array(),
            "serve_slots": _lan_serve_slots(),
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
        properties["capabilities"] = _capabilities_array()
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
            "capabilities": _capabilities_array(),
            "cid": {"type": "string"},
            "serve_slots": _lan_serve_slots(),
        },
        "required": ["type", "protocol_version", "capabilities"],
        "additionalProperties": False,
    }


def _lan_inventory_upsert() -> dict[str, Any]:
    """LAN seeder inventory upsert entry."""
    return {
        "type": "object",
        "title": "LanInventoryUpsertEntry",
        "properties": {
            "path": _lan_relpath(),
            "sha256": _lan_sha256(),
            "size": _lan_wire_int(),
        },
        "required": ["path", "sha256", "size"],
        "additionalProperties": False,
    }


def _lan_inventory_delete() -> dict[str, Any]:
    """LAN seeder inventory delta deletion entry."""
    return {
        "type": "object",
        "title": "LanInventoryDeleteEntry",
        "properties": {"path": _lan_relpath(), "deleted": {"const": True}},
        "required": ["path", "deleted"],
        "additionalProperties": False,
    }


def _lan_inventory_frame(mode: str) -> dict[str, Any]:
    """LAN inventory snapshot/delta frame with mode-specific entry rules."""
    snapshot = mode == "snapshot"
    entries: dict[str, Any] = {
        "type": "array",
        "items": {"$ref": "#/$defs/inventoryUpsert" if snapshot else "#/$defs/inventoryEntry"},
        "maxItems": LAN_INVENTORY_MAX_ENTRIES,
        "uniqueItems": True,
        "description": "Each normalized path occurs exactly once in the frame.",
    }
    if not snapshot:
        entries["minItems"] = 1
    frame = {
        "type": "object",
        "title": f"LanInventory{'Snapshot' if snapshot else 'Delta'}",
        "properties": {
            "type": {"const": "inventory"},
            "gen": _lan_wire_int(),
            "seq": _lan_wire_int(),
            "mode": {"const": mode},
            "more": {"type": "boolean"} if snapshot else {"const": False},
            "entries": entries,
        },
        "required": ["type", "gen", "seq", "mode", "more", "entries"],
        "additionalProperties": False,
    }
    if snapshot:
        frame["allOf"] = [
            {
                "if": {"properties": {"entries": {"maxItems": 0}}, "required": ["entries"]},
                "then": {
                    "properties": {
                        "seq": {"const": 0},
                        "more": {"const": False},
                    }
                },
            }
        ]
    return frame


def _lan_inventory_ack(status: str) -> dict[str, Any]:
    """LAN inventory acknowledgement for one exact status."""
    rejected = status == "rejected"
    properties: dict[str, Any] = {
        "type": {"const": "inventory_ack"},
        "gen": _lan_wire_int(),
        "seq": _lan_wire_int(),
        "status": {"const": status},
    }
    required = ["type", "gen", "seq", "status"]
    if rejected:
        properties["reason"] = {
            "type": "string",
            "pattern": r"^[a-z][a-z0-9_]{0,63}$",
            "maxLength": LAN_INVENTORY_ACK_REASON_MAX_LENGTH,
        }
        required.append("reason")
    return {
        "type": "object",
        "title": f"LanInventoryAck{status.capitalize()}",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def build_lan_wss_schema() -> dict[str, Any]:
    """Build the additive LAN WebSocket JSON Schema from the Python SSOT.

    Codifies the master⇄slave handshake frames (ADR-0024): they exchange the
    capability registry over the authenticated channel, so the mDNS/TXT record
    is not the only capability source on the LAN. Inventory publication and its
    acknowledgements extend ``lan/1`` additively under ADR-0028.
    """
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": f"https://hsync.dev/protocol/{PROTOCOL_VERSION_LAN}/wss",
        "title": f"HSYNC LAN WebSocket protocol ({PROTOCOL_VERSION_LAN})",
        "description": (
            "Wire contract for the LAN master⇄slave WebSocket handshake and "
            "peer inventory channel (ADR-0024, ADR-0028). Generated from "
            "hsync_common.protocol.schemas; do not hand-edit."
        ),
        "x-maxMessageBytes": LAN_INVENTORY_MAX_FRAME_BYTES,
        "$defs": {
            **_entity_defs(),
            "authRequired": _lan_auth_required(),
            "auth": _lan_auth(),
            "authOk": _lan_auth_result("ok"),
            "authFailed": _lan_auth_result("failed"),
            "hello": _lan_hello(),
            "inventoryUpsert": _lan_inventory_upsert(),
            "inventoryDelete": _lan_inventory_delete(),
            "inventoryEntry": {
                "oneOf": [
                    {"$ref": "#/$defs/inventoryUpsert"},
                    {"$ref": "#/$defs/inventoryDelete"},
                ]
            },
            "inventorySnapshot": _lan_inventory_frame("snapshot"),
            "inventoryDelta": _lan_inventory_frame("delta"),
            "inventory": {
                "oneOf": [
                    {"$ref": "#/$defs/inventorySnapshot"},
                    {"$ref": "#/$defs/inventoryDelta"},
                ]
            },
            "inventoryAckOk": _lan_inventory_ack("ok"),
            "inventoryAckResync": _lan_inventory_ack("resync"),
            "inventoryAckRejected": _lan_inventory_ack("rejected"),
            "inventoryAck": {
                "oneOf": [
                    {"$ref": "#/$defs/inventoryAckOk"},
                    {"$ref": "#/$defs/inventoryAckResync"},
                    {"$ref": "#/$defs/inventoryAckRejected"},
                ]
            },
        },
        "masterToSlave": {
            "oneOf": [
                {"$ref": "#/$defs/authRequired"},
                {"$ref": "#/$defs/authOk"},
                {"$ref": "#/$defs/authFailed"},
                {"$ref": "#/$defs/hello"},
                {"$ref": "#/$defs/fileEvent"},
                {"$ref": "#/$defs/inventoryAck"},
            ]
        },
        "slaveToMaster": {
            "oneOf": [
                {"$ref": "#/$defs/auth"},
                {"$ref": "#/$defs/hello"},
                {"$ref": "#/$defs/fileEvent"},
                {"$ref": "#/$defs/inventory"},
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
        "server_ready": _TXT_BOOL_FLAG,
        "force_master": _TXT_BOOL_FLAG,
        "never_master": _TXT_BOOL_FLAG,
        "peer_download": {
            **_TXT_BOOL_FLAG,
            "description": (
                "This node implements LAN inventory, batch source lookup and "
                "read-only seeder semantics (ADR-0028)."
            ),
        },
        "connected": {
            "type": "string",
            "pattern": r"^[0-9]+$",
            "description": (
                "Count of clients currently connected to this bucket's share "
                "(master included). Present only on a serving master; "
                "informational, never part of the election."
            ),
        },
        "heartbeat": {
            "type": "string",
            "pattern": r"^[0-9]+$",
            "description": (
                "Monotonic liveness counter, incremented on every periodic "
                "re-announce. Opaque: receivers only rely on it changing so "
                "their staleness sweep sees fresh records for otherwise "
                "quiescent peers. Never part of the election."
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
