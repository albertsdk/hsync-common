# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""``boot/1`` bootstrap-protocol mirror for the client (SSOT = ``hsync-bootnode``).

The canonical specification and the canonical golden fixtures live in the
``hsync-bootnode`` repository (``protocol-spec/boot-1.md`` and ``fixtures/``);
the bootnode daemon does **not** import ``hsync-common`` (it stays a standalone
package so it can be ported to Rust). This module is therefore a *mirror* of
that contract for the consumers that do live in this monorepo — today the
``hsync-client`` bootnode discovery (Fase C2) and the shared fixtures/drift
tests. A drift test (``tests/test_protocol_bootnode.py``) compares the mirrored
fixtures against the canonical ``hsync-bootnode/fixtures/`` bytes so the two
copies cannot diverge silently.

Like the rest of the protocol package this mirror is dependency-free: TypedDicts
describe the wire shape and strict ``validate_*`` helpers reject unknown or
malformed fields without partially accepting them (the same strictness the
bootnode's ``extra="forbid"`` models provide).

Consumers: ``hsync-client`` (bootnode register/refresh/query), shared
fixtures/tests.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from typing import Literal, NotRequired, TypedDict

from hsync_common.models.event import CID_PATTERN, is_valid_cid
from hsync_common.path_validation import is_valid_bucket_name

__all__ = [
    "PROTOCOL_VERSION_BOOT",
    "BOOT_ALPN",
    "CID_PATTERN",
    "BUCKET_TOKEN_LEN",
    "CAPACITY_MAX",
    "BucketProto",
    "Endpoint",
    "ObservedEndpoint",
    "BootRegister",
    "BootRefresh",
    "BootLeave",
    "BootQuery",
    "BootAck",
    "BootPeer",
    "BootResponse",
    "BootFrame",
    "validate_boot_frame",
    "validate_boot_ack",
    "validate_boot_response",
    "derive_bucket_token",
    "is_valid_bucket_token",
    "constant_time_equals",
    "verify_bucket_token",
]

# Per-channel protocol version. Bump the suffix on any breaking change to the
# bootstrap channel's wire shape; peers then hard-fail instead of drifting.
PROTOCOL_VERSION_BOOT: Literal["boot/1"] = "boot/1"

# QUIC ALPN offered by the bootnode's TLS handshake.
BOOT_ALPN = "hsync-boot/1"

# hex(32 bytes) = 64 chars. Absent = open bucket (D11).
BUCKET_TOKEN_LEN = 64
_BUCKET_TOKEN_RE = re.compile(rf"^[0-9a-f]{{{BUCKET_TOKEN_LEN}}}$")

BucketProto = Literal["tcp", "udp"]

# Advisory service-capacity hint domain (``0..32``; ``0`` = not a peer-download
# seeder). Mirrors the authenticated ``serve_slots`` range (1..32); the bootnode
# relays the value in ``query`` responses but never treats it as authoritative
# (ADR-0030) — the authoritative value stays on the authenticated WSS handshake.
CAPACITY_MAX = 32

_TOKEN_DOMAIN = b"boot/1"

# Wire bounds, mirrored from the bootnode models. Bucket names are bounded by
# ``is_valid_bucket_name`` (``MAX_BUCKET_NAME_LENGTH``), not by a length here.
_MAX_GROUP_LEN = 128
_MAX_CERT_FP_LEN = 256
_MAX_VERSION_LEN = 64
_MAX_ENDPOINTS = 16
_MIN_QUERY_LIMIT = 1
_MAX_QUERY_LIMIT = 50
_MIN_TTL = 1
_MAX_TTL = 3600


def derive_bucket_token(key: bytes, bucket: str) -> str:
    """Derive the 64-char hex bucket token for the given group key + bucket."""
    digest = hmac.new(key, _TOKEN_DOMAIN + bucket.encode("utf-8"), hashlib.sha256).digest()
    return digest[:32].hex()


def is_valid_bucket_token(value: str) -> bool:
    """True iff ``value`` is a well-formed 64-char lowercase hex token."""
    return _BUCKET_TOKEN_RE.match(value) is not None


def constant_time_equals(a: bytes, b: bytes) -> bool:
    """Constant-time byte-string comparison (no timing side-channel)."""
    return hmac.compare_digest(a, b)


def verify_bucket_token(expected: str, provided: str | None) -> bool:
    """Return True iff a provided token matches the expected one, uniformly.

    A missing/malformed token simply never matches (caller decides whether the
    bucket requires one — this helper never reveals that a bucket exists).
    """
    if provided is None:
        return False
    if not is_valid_bucket_token(provided):
        return False
    return constant_time_equals(
        expected.encode("ascii"),
        provided.encode("ascii"),
    )


class Endpoint(TypedDict):
    """An advertised listen endpoint (register's ``endpoints[]``)."""

    proto: BucketProto
    host: str
    port: int


class ObservedEndpoint(TypedDict):
    """The source endpoint observed by the server (STUN-echo in ``ack``)."""

    proto: BucketProto
    ip: str
    port: int


class BootRegister(TypedDict):
    """Client announces presence in a bucket (first contact).

    ``capacity`` is the advisory service-capacity hint: the number of
    concurrent peer-download reads the peer declares it can serve right now
    (``0`` = not a seeder). The bootnode relays it in ``query`` responses; the
    authoritative value is the authenticated ``serve_slots`` (ADR-0030).
    """

    protocol_version: Literal["boot/1"]
    type: Literal["register"]
    cid: str
    bucket: str
    cert_fp: str
    version: str
    capacity: int
    endpoints: list[Endpoint]
    group: NotRequired[str]
    bucket_token: NotRequired[str]
    connected: NotRequired[int]


class BootRefresh(TypedDict):
    """Client renews its TTL (and/or connected count)."""

    protocol_version: Literal["boot/1"]
    type: Literal["refresh"]
    cid: str
    bucket: str
    group: NotRequired[str]
    bucket_token: NotRequired[str]
    connected: NotRequired[int]


class BootLeave(TypedDict):
    """Client announces departure."""

    protocol_version: Literal["boot/1"]
    type: Literal["leave"]
    cid: str
    bucket: str
    bucket_token: NotRequired[str]


class BootQuery(TypedDict):
    """Client asks for a random sample of peers. Only generic — no file targeting."""

    protocol_version: Literal["boot/1"]
    type: Literal["query"]
    bucket: str
    group: NotRequired[str]
    bucket_token: NotRequired[str]
    limit: NotRequired[int]


class BootAck(TypedDict):
    """Server reply to register/refresh: STUN-echo observed endpoint + TTL."""

    protocol_version: Literal["boot/1"]
    type: Literal["ack"]
    observed_endpoint: ObservedEndpoint
    ttl: int
    server_time: str
    retry_after: NotRequired[int]


class BootPeer(TypedDict):
    """A single advertised peer in a BootResponse.

    ``capacity`` is the peer's advisory service-capacity hint as relayed from
    its ``register`` (``0`` = not a seeder); ``reachable`` is derived from
    ``bool(endpoints)``. Neither is authoritative (ADR-0030).
    """

    cid: str
    ip: str
    port: int
    proto: BucketProto
    cert_fp: str
    bucket: str
    version: str
    capacity: int
    reachable: bool
    group: NotRequired[str]


class BootResponse(TypedDict):
    """Server reply to query: random sample of peers (or a uniform refusal)."""

    protocol_version: Literal["boot/1"]
    type: Literal["response"]
    peers: list[BootPeer]
    count: int
    ttl: int
    error: NotRequired[Literal["token_required", "rate_limited"]]
    retry_after: NotRequired[int]


# Client→server frames, dispatched on ``type``. ``BootResponse``/``BootAck``/
# ``BootPeer`` are server→client and deliberately excluded from the request
# union: they are never validated on the input path.
BootFrame = BootRegister | BootRefresh | BootLeave | BootQuery

_REGISTER_REQUIRED = frozenset({"protocol_version", "type", "cid", "bucket", "cert_fp", "version"})
_REGISTER_OPTIONAL = frozenset({"group", "bucket_token", "connected", "capacity", "endpoints"})
_REFRESH_REQUIRED = frozenset({"protocol_version", "type", "cid", "bucket"})
_REFRESH_OPTIONAL = frozenset({"group", "bucket_token", "connected"})
_LEAVE_REQUIRED = frozenset({"protocol_version", "type", "cid", "bucket"})
_LEAVE_OPTIONAL = frozenset({"bucket_token"})
_QUERY_REQUIRED = frozenset({"protocol_version", "type", "bucket"})
_QUERY_OPTIONAL = frozenset({"group", "bucket_token", "limit"})
_ACK_REQUIRED = frozenset({"protocol_version", "type", "observed_endpoint", "ttl", "server_time"})
_ACK_OPTIONAL = frozenset({"retry_after"})
_RESPONSE_REQUIRED = frozenset({"protocol_version", "type", "peers", "count", "ttl"})
_RESPONSE_OPTIONAL = frozenset({"error", "retry_after"})
_PEER_REQUIRED = frozenset(
    {"cid", "ip", "port", "proto", "cert_fp", "bucket", "version", "capacity", "reachable"}
)
_PEER_OPTIONAL = frozenset({"group"})
_ENDPOINT_KEYS = frozenset({"proto", "host", "port"})
_OBSERVED_KEYS = frozenset({"proto", "ip", "port"})


def _is_object(value: object, required: frozenset[str], optional: frozenset[str]) -> bool:
    """True when ``value`` is a mapping whose keys are exactly required ∪ optional."""
    if not isinstance(value, Mapping):
        return False
    keys = set(value)
    return keys <= (required | optional) and required <= keys


def _is_str(value: object, *, max_len: int, min_len: int = 1) -> bool:
    return isinstance(value, str) and min_len <= len(value) <= max_len


def _is_port(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535


def _is_int(value: object, *, minimum: int = 0, maximum: int | None = None) -> bool:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        return False
    return maximum is None or value <= maximum


def _is_capacity(value: object) -> bool:
    return _is_int(value, maximum=CAPACITY_MAX)


def _optional_str(value: Mapping, clean: dict, key: str, max_len: int) -> bool:
    """Copy an optional bounded string field; return False when it is malformed."""
    if key not in value or value[key] is None:
        return True
    item = value[key]
    if not _is_str(item, max_len=max_len):
        return False
    clean[key] = item
    return True


def _optional_token(value: Mapping, clean: dict) -> bool:
    if "bucket_token" not in value or value["bucket_token"] is None:
        return True
    token = value["bucket_token"]
    if not isinstance(token, str) or not is_valid_bucket_token(token):
        return False
    clean["bucket_token"] = token
    return True


def _optional_connected(value: Mapping, clean: dict) -> bool:
    if "connected" not in value or value["connected"] is None:
        return True
    if not _is_int(value["connected"]):
        return False
    clean["connected"] = value["connected"]
    return True


def _validate_endpoint(value: object) -> Endpoint | None:
    if not _is_object(value, _ENDPOINT_KEYS, frozenset()):
        return None
    proto = value["proto"]
    host = value["host"]
    port = value["port"]
    if proto not in ("tcp", "udp") or not _is_str(host, max_len=255) or not _is_port(port):
        return None
    return Endpoint(proto=proto, host=host, port=port)


def _validate_observed(value: object) -> ObservedEndpoint | None:
    if not _is_object(value, _OBSERVED_KEYS, frozenset()):
        return None
    proto = value["proto"]
    ip = value["ip"]
    port = value["port"]
    if proto not in ("tcp", "udp") or not isinstance(ip, str) or not _is_port(port):
        return None
    return ObservedEndpoint(proto=proto, ip=ip, port=port)


def _validate_peer(value: object) -> BootPeer | None:
    if not _is_object(value, _PEER_REQUIRED, _PEER_OPTIONAL):
        return None
    cid = value["cid"]
    proto = value["proto"]
    cert_fp = value["cert_fp"]
    bucket = value["bucket"]
    version = value["version"]
    if (
        not is_valid_cid(cid)
        or not isinstance(value["ip"], str)
        or not _is_port(value["port"])
        or proto not in ("tcp", "udp")
        or not _is_str(cert_fp, max_len=_MAX_CERT_FP_LEN)
        or not is_valid_bucket_name(bucket)
        or not _is_str(version, max_len=_MAX_VERSION_LEN)
        or not _is_capacity(value["capacity"])
        or not isinstance(value["reachable"], bool)
    ):
        return None
    clean = BootPeer(
        cid=cid,
        ip=value["ip"],
        port=value["port"],
        proto=proto,
        cert_fp=cert_fp,
        bucket=bucket,
        version=version,
        capacity=value["capacity"],
        reachable=value["reachable"],
    )
    if not _optional_str(value, clean, "group", _MAX_GROUP_LEN):
        return None
    return clean


def validate_boot_register(value: object) -> BootRegister | None:
    """Strictly validate a ``register`` frame."""
    if not _is_object(value, _REGISTER_REQUIRED, _REGISTER_OPTIONAL):
        return None
    if value["protocol_version"] != PROTOCOL_VERSION_BOOT or value["type"] != "register":
        return None
    # ``capacity`` (default 0) and ``endpoints`` (default []) are optional on the
    # wire: the first STUN register has no known public endpoint yet, and a
    # non-seeder declares no capacity. Explicit ``null`` is still rejected, like
    # the bootnode's pydantic models.
    capacity = value.get("capacity", 0)
    endpoints = value.get("endpoints", [])
    if (
        not is_valid_cid(value["cid"])
        or not is_valid_bucket_name(value["bucket"])
        or not _is_str(value["cert_fp"], max_len=_MAX_CERT_FP_LEN)
        or not _is_str(value["version"], max_len=_MAX_VERSION_LEN)
        or not _is_capacity(capacity)
        or not isinstance(endpoints, list)
        or len(endpoints) > _MAX_ENDPOINTS
    ):
        return None
    clean_endpoints: list[Endpoint] = []
    for item in endpoints:
        clean_endpoint = _validate_endpoint(item)
        if clean_endpoint is None:
            return None
        clean_endpoints.append(clean_endpoint)
    clean = BootRegister(
        protocol_version=PROTOCOL_VERSION_BOOT,
        type="register",
        cid=value["cid"],
        bucket=value["bucket"],
        cert_fp=value["cert_fp"],
        version=value["version"],
        capacity=capacity,
        endpoints=clean_endpoints,
    )
    if not (
        _optional_str(value, clean, "group", _MAX_GROUP_LEN)
        and _optional_token(value, clean)
        and _optional_connected(value, clean)
    ):
        return None
    return clean


def validate_boot_refresh(value: object) -> BootRefresh | None:
    """Strictly validate a ``refresh`` frame."""
    if not _is_object(value, _REFRESH_REQUIRED, _REFRESH_OPTIONAL):
        return None
    if value["protocol_version"] != PROTOCOL_VERSION_BOOT or value["type"] != "refresh":
        return None
    if not is_valid_cid(value["cid"]) or not is_valid_bucket_name(value["bucket"]):
        return None
    clean = BootRefresh(
        protocol_version=PROTOCOL_VERSION_BOOT,
        type="refresh",
        cid=value["cid"],
        bucket=value["bucket"],
    )
    if not (
        _optional_str(value, clean, "group", _MAX_GROUP_LEN)
        and _optional_token(value, clean)
        and _optional_connected(value, clean)
    ):
        return None
    return clean


def validate_boot_leave(value: object) -> BootLeave | None:
    """Strictly validate a ``leave`` frame."""
    if not _is_object(value, _LEAVE_REQUIRED, _LEAVE_OPTIONAL):
        return None
    if value["protocol_version"] != PROTOCOL_VERSION_BOOT or value["type"] != "leave":
        return None
    if not is_valid_cid(value["cid"]) or not is_valid_bucket_name(value["bucket"]):
        return None
    clean = BootLeave(
        protocol_version=PROTOCOL_VERSION_BOOT,
        type="leave",
        cid=value["cid"],
        bucket=value["bucket"],
    )
    if not _optional_token(value, clean):
        return None
    return clean


def validate_boot_query(value: object) -> BootQuery | None:
    """Strictly validate a ``query`` frame."""
    if not _is_object(value, _QUERY_REQUIRED, _QUERY_OPTIONAL):
        return None
    if value["protocol_version"] != PROTOCOL_VERSION_BOOT or value["type"] != "query":
        return None
    if not is_valid_bucket_name(value["bucket"]):
        return None
    clean = BootQuery(
        protocol_version=PROTOCOL_VERSION_BOOT,
        type="query",
        bucket=value["bucket"],
    )
    if not (_optional_str(value, clean, "group", _MAX_GROUP_LEN) and _optional_token(value, clean)):
        return None
    if "limit" in value and value["limit"] is not None:
        if not _is_int(value["limit"], minimum=_MIN_QUERY_LIMIT, maximum=_MAX_QUERY_LIMIT):
            return None
        clean["limit"] = value["limit"]
    return clean


def validate_boot_ack(value: object) -> BootAck | None:
    """Strictly validate an ``ack`` frame (server→client)."""
    if not _is_object(value, _ACK_REQUIRED, _ACK_OPTIONAL):
        return None
    if value["protocol_version"] != PROTOCOL_VERSION_BOOT or value["type"] != "ack":
        return None
    observed = _validate_observed(value["observed_endpoint"])
    if (
        observed is None
        or not _is_int(value["ttl"], minimum=_MIN_TTL, maximum=_MAX_TTL)
        or not isinstance(value["server_time"], str)
    ):
        return None
    clean = BootAck(
        protocol_version=PROTOCOL_VERSION_BOOT,
        type="ack",
        observed_endpoint=observed,
        ttl=value["ttl"],
        server_time=value["server_time"],
    )
    if "retry_after" in value and value["retry_after"] is not None:
        if not _is_int(value["retry_after"], minimum=1):
            return None
        clean["retry_after"] = value["retry_after"]
    return clean


def validate_boot_response(value: object) -> BootResponse | None:
    """Strictly validate a ``response`` frame (server→client)."""
    if not _is_object(value, _RESPONSE_REQUIRED, _RESPONSE_OPTIONAL):
        return None
    if value["protocol_version"] != PROTOCOL_VERSION_BOOT or value["type"] != "response":
        return None
    peers = value["peers"]
    if (
        not isinstance(peers, list)
        or not _is_int(value["count"])
        or not _is_int(value["ttl"], minimum=_MIN_TTL, maximum=_MAX_TTL)
    ):
        return None
    clean_peers: list[BootPeer] = []
    for item in peers:
        clean_peer = _validate_peer(item)
        if clean_peer is None:
            return None
        clean_peers.append(clean_peer)
    if value["count"] != len(clean_peers):
        return None
    error = value.get("error")
    if error is not None and error not in ("token_required", "rate_limited"):
        return None
    clean = BootResponse(
        protocol_version=PROTOCOL_VERSION_BOOT,
        type="response",
        peers=clean_peers,
        count=value["count"],
        ttl=value["ttl"],
    )
    if error is not None:
        clean["error"] = error
    if "retry_after" in value and value["retry_after"] is not None:
        if not _is_int(value["retry_after"], minimum=1):
            return None
        clean["retry_after"] = value["retry_after"]
    return clean


def validate_boot_frame(value: object) -> BootFrame | None:
    """Dispatch on ``type`` and strictly validate one client→server frame."""
    if not isinstance(value, Mapping):
        return None
    frame_type = value.get("type")
    if frame_type == "register":
        return validate_boot_register(value)
    if frame_type == "refresh":
        return validate_boot_refresh(value)
    if frame_type == "leave":
        return validate_boot_leave(value)
    if frame_type == "query":
        return validate_boot_query(value)
    return None
