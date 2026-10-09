# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""``boot/1`` bootstrap-protocol mirror for the client (SSOT = ``hsync-bootnode``).

The canonical specification and the canonical golden fixtures live in the
``hsync-bootnode`` repository (``protocol-spec/boot-1.md`` and ``fixtures/``);
this module is a *mirror* of that contract for the consumers that live in this
monorepo — today the ``hsync-client`` bootnode discovery and the
shared fixtures/drift tests. The daemon keeps its own frame models and never
imports this mirror (the fixtures are the cross-language contract), but its
Python v1 does reuse a small set of generic ``hsync-common`` utilities
(``ssl_utils``, ``CID_PATTERN``, ``is_valid_bucket_name``) — see ADR-0033. A
drift test (``tests/test_protocol_bootnode.py``) compares the mirrored fixtures
against the canonical ``hsync-bootnode/fixtures/`` bytes so the two copies
cannot diverge silently.

Like the rest of the protocol package this mirror is dependency-free: TypedDicts
describe the wire shape and strict ``validate_*`` helpers reject unknown or
malformed fields without partially accepting them (the same strictness the
bootnode's ``extra="forbid"`` models provide).

Besides the advisory ``capacity`` hint, ``register`` and ``peers[]`` carry the
**election advertisement** (``server_ready``/``force_master``/``never_master``/
``startup_time``/``sync_direction``) — the same values the mDNS TXT record
carries, relayed verbatim by the bootnode so both discovery plans feed the one
shared election algorithm in :mod:`hsync_common.protocol.p2p`. The bootnode never
interprets them and they are not authenticated (the data plane authenticates
identity by certificate pinning); the vocabulary is the canonical sync-direction
set from :mod:`hsync_common.protocol.pairing`.

Consumers: ``hsync-client`` (bootnode register/refresh/query), shared
fixtures/tests.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
from collections.abc import Mapping
from typing import Literal, NotRequired, TypedDict

from hsync_common.models.event import CID_PATTERN, is_valid_cid
from hsync_common.path_validation import is_valid_bucket_name
from hsync_common.protocol.p2p import SYNC_DIRECTION_BIDIRECTIONAL
from hsync_common.protocol.pairing import (
    SYNC_DIRECTION_DOWNLOAD_ONLY,
    SYNC_DIRECTION_UPLOAD_ONLY,
)

__all__ = [
    "BOOT_ALPN",
    "BUCKET_TOKEN_LEN",
    "CAPACITY_MAX",
    "CID_PATTERN",
    "PROTOCOL_VERSION_BOOT",
    "BootAck",
    "BootError",
    "BootFrame",
    "BootLeave",
    "BootPeer",
    "BootQuery",
    "BootRefresh",
    "BootRegister",
    "BootResponse",
    "BucketProto",
    "Endpoint",
    "ObservedEndpoint",
    "constant_time_equals",
    "derive_bucket_token",
    "is_valid_bucket_token",
    "validate_boot_ack",
    "validate_boot_frame",
    "validate_boot_response",
    "verify_bucket_token",
]

# Per-channel protocol version. Bump the suffix on any breaking change to the
# bootstrap channel's wire shape; peers then hard-fail instead of drifting.
PROTOCOL_VERSION_BOOT: Literal["boot/1"] = "boot/1"

# QUIC ALPN offered by the bootnode's TLS handshake.
BOOT_ALPN = "hsync-boot/1"

# hex(32 bytes) = 64 chars. Absent = open bucket.
BUCKET_TOKEN_LEN = 64
_BUCKET_TOKEN_RE = re.compile(rf"^[0-9a-f]{{{BUCKET_TOKEN_LEN}}}$")

BucketProto = Literal["tcp", "udp"]

# Uniform refusal codes on a ``response`` frame: ``token_required`` (authorization,
# no bucket-existence oracle), ``rate_limited`` (per-source/per-(IP,bucket) limit;
# ``retry_after`` = limiter refill) and ``overloaded`` (the node is at its
# host-derived routing-table ceiling; ``retry_after`` is advisory backpressure,
# not a client abuse signal). Mirrors ``hsync_bootnode.protocol.BootError``.
BootError = Literal["token_required", "rate_limited", "overloaded"]
_BOOT_ERRORS = ("token_required", "rate_limited", "overloaded")

# Advisory service-capacity hint domain (``0..32``; ``0`` = not a peer-download
# seeder). Mirrors the authenticated ``serve_slots`` range (1..32); the bootnode
# relays the value in ``query`` responses but never treats it as authoritative
# (ADR-0030) — the authoritative value stays on the authenticated WSS handshake.
CAPACITY_MAX = 32

# Canonical sync-direction vocabulary (SSOT: :mod:`hsync_common.protocol.p2p`
# and :mod:`hsync_common.protocol.pairing`). The election advertisement on
# ``boot/1`` reuses the same values as the mDNS TXT record, so both discovery
# plans feed the shared election algorithm one identical vocabulary.
_SYNC_DIRECTIONS = frozenset(
    {
        SYNC_DIRECTION_BIDIRECTIONAL,
        SYNC_DIRECTION_UPLOAD_ONLY,
        SYNC_DIRECTION_DOWNLOAD_ONLY,
    }
)

# Bound on the advertised unix ``startup_time``: keeps the value inside the
# exactly-representable integer range of a JSON number. A peer that does not
# advertise one defaults to ``0.0`` ("unknown"), which the election only reads
# as a last-resort ordering key before the CID tiebreaker.
_MAX_STARTUP_TIME = float(2**53)

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

    ``server_ready``/``force_master``/``never_master``/``startup_time``/
    ``sync_direction`` are the **election advertisement**, the same values the
    mDNS TXT record carries. The bootnode relays them verbatim in ``query``
    responses so a bootnode-discovered peer ranks exactly like an mDNS one; it
    never interprets them and never treats them as authoritative (a peer can
    claim any value, and the data plane authenticates identity by certificate
    pinning). A changed advertisement requires a new ``register`` — ``refresh``
    never mutates them.
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
    server_ready: NotRequired[bool]
    force_master: NotRequired[bool]
    never_master: NotRequired[bool]
    startup_time: NotRequired[float]
    sync_direction: NotRequired[str]


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

    ``endpoints`` is the peer's full advertised candidate list, relayed verbatim
    and in order (or a single-element list with the observed source endpoint
    when the peer advertised none). A requester tries the candidates, preferring
    a host/LAN one reachable from its own network, so peers behind the same NAT
    — where the public endpoint has no hairpin route — still connect locally.

    ``capacity`` is the peer's advisory service-capacity hint as relayed from
    its ``register`` (``0`` = not a seeder); ``reachable`` is derived from
    ``bool(endpoints)``. Neither is authoritative (ADR-0030).

    The election-advertisement fields are relayed verbatim from the peer's
    ``register`` (defaults when it advertised none): ``server_ready`` (it is
    currently serving as master), ``force_master``/``never_master`` (operator
    pins), ``startup_time`` (unix seconds, ``0.0`` = unknown) and
    ``sync_direction``. They feed the shared election algorithm exactly like
    the mDNS TXT values; none of them is authenticated.
    """

    cid: str
    endpoints: list[Endpoint]
    cert_fp: str
    bucket: str
    version: str
    capacity: int
    reachable: bool
    server_ready: bool
    force_master: bool
    never_master: bool
    startup_time: float
    sync_direction: str
    group: NotRequired[str]


class BootResponse(TypedDict):
    """Server reply to query: random sample of peers (or a uniform refusal)."""

    protocol_version: Literal["boot/1"]
    type: Literal["response"]
    peers: list[BootPeer]
    count: int
    ttl: int
    error: NotRequired[BootError]
    retry_after: NotRequired[int]


# Client→server frames, dispatched on ``type``. ``BootResponse``/``BootAck``/
# ``BootPeer`` are server→client and deliberately excluded from the request
# union: they are never validated on the input path.
BootFrame = BootRegister | BootRefresh | BootLeave | BootQuery

_REGISTER_REQUIRED = frozenset({"protocol_version", "type", "cid", "bucket", "cert_fp", "version"})
_REGISTER_OPTIONAL = frozenset(
    {
        "group",
        "bucket_token",
        "connected",
        "capacity",
        "endpoints",
        "server_ready",
        "force_master",
        "never_master",
        "startup_time",
        "sync_direction",
    }
)
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
    {
        "cid",
        "endpoints",
        "cert_fp",
        "bucket",
        "version",
        "capacity",
        "reachable",
        "server_ready",
        "force_master",
        "never_master",
        "startup_time",
        "sync_direction",
    }
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


def _envelope_ok(
    value: object, frame_type: str, required: frozenset[str], optional: frozenset[str]
) -> bool:
    """Validate the common frame envelope shared by every validator.

    Combines the exact-key check (:func:`_is_object`) with the mandatory
    ``protocol_version``/``type`` match, so each ``validate_boot_*`` only states
    its window of required/optional keys instead of repeating the prologue.
    """
    if not isinstance(value, Mapping) or not _is_object(value, required, optional):
        return False
    return value["protocol_version"] == PROTOCOL_VERSION_BOOT and value["type"] == frame_type


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


def _optional_int(
    value: Mapping, clean: dict, key: str, *, minimum: int = 0, maximum: int | None = None
) -> bool:
    """Copy an optional bounded integer field; return False when it is malformed."""
    if key not in value or value[key] is None:
        return True
    if not _is_int(value[key], minimum=minimum, maximum=maximum):
        return False
    clean[key] = value[key]
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
    """Copy the optional advisory ``connected`` count (see :func:`_optional_int`)."""
    return _optional_int(value, clean, "connected")


def _is_startup_time(value: object) -> bool:
    """True for a finite, non-negative unix timestamp (bools are rejected)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= _MAX_STARTUP_TIME
    )


def _is_sync_direction(value: object) -> bool:
    """True for a canonical sync-direction token (SSOT: ``protocol.pairing``)."""
    return isinstance(value, str) and value in _SYNC_DIRECTIONS


def _optional_flag(value: Mapping, clean: dict, key: str) -> bool:
    """Copy an optional boolean flag; return False when it is malformed.

    Explicit ``null`` is rejected, like the bootnode's pydantic models (a
    ``bool`` field has no ``None`` variant): a client either advertises the flag
    or omits the key, in which case the documented default applies.
    """
    if key not in value:
        return True
    item = value[key]
    if not isinstance(item, bool):
        return False
    clean[key] = item
    return True


def _read_election_advert(value: Mapping, clean: dict, *, optional: bool) -> bool:
    """Validate and copy the election advertisement (register / query peer).

    The five keys are the same values the mDNS TXT record carries; ``optional``
    controls the register side (absent key → documented default) versus the
    ``peers[]`` side (every key is required, the bootnode always relays them).
    Returns False on any malformed value so the caller rejects the whole frame.
    """
    for key in ("server_ready", "force_master", "never_master"):
        if key not in value:
            if optional:
                clean[key] = False
                continue
            return False
        if not _optional_flag(value, clean, key):
            return False
    if "startup_time" not in value:
        if not optional:
            return False
        clean["startup_time"] = 0.0
    else:
        startup_time = value["startup_time"]
        if not _is_startup_time(startup_time):
            return False
        clean["startup_time"] = float(startup_time)
    if "sync_direction" not in value:
        if not optional:
            return False
        clean["sync_direction"] = SYNC_DIRECTION_BIDIRECTIONAL
    elif not _is_sync_direction(value["sync_direction"]):
        return False
    else:
        clean["sync_direction"] = value["sync_direction"]
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
    endpoints = value["endpoints"]
    cert_fp = value["cert_fp"]
    bucket = value["bucket"]
    version = value["version"]
    if (
        not is_valid_cid(cid)
        or not isinstance(endpoints, list)
        or not 1 <= len(endpoints) <= _MAX_ENDPOINTS
        or not _is_str(cert_fp, max_len=_MAX_CERT_FP_LEN)
        or not is_valid_bucket_name(bucket)
        or not _is_str(version, max_len=_MAX_VERSION_LEN)
        or not _is_capacity(value["capacity"])
        or not isinstance(value["reachable"], bool)
    ):
        return None
    clean_endpoints: list[Endpoint] = []
    for item in endpoints:
        clean_endpoint = _validate_endpoint(item)
        if clean_endpoint is None:
            return None
        clean_endpoints.append(clean_endpoint)
    clean = BootPeer(
        cid=cid,
        endpoints=clean_endpoints,
        cert_fp=cert_fp,
        bucket=bucket,
        version=version,
        capacity=value["capacity"],
        reachable=value["reachable"],
    )
    if not _read_election_advert(value, clean, optional=False):
        return None
    if not _optional_str(value, clean, "group", _MAX_GROUP_LEN):
        return None
    return clean


def validate_boot_register(value: object) -> BootRegister | None:
    """Strictly validate a ``register`` frame."""
    if not _envelope_ok(value, "register", _REGISTER_REQUIRED, _REGISTER_OPTIONAL):
        return None
    # ``capacity`` (default 0) and ``endpoints`` (default []) are optional on the
    # wire: the first STUN register has no known public endpoint yet, and a
    # non-seeder declares no capacity. The election advertisement is optional as
    # well (defaults: not serving, no pin, unknown startup, bidirectional) and,
    # like capacity/endpoints, a changed value requires a new ``register``:
    # ``refresh`` never mutates it. Explicit ``null`` is still rejected, like the
    # bootnode's pydantic models.
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
        and _read_election_advert(value, clean, optional=True)
    ):
        return None
    return clean


def validate_boot_refresh(value: object) -> BootRefresh | None:
    """Strictly validate a ``refresh`` frame."""
    if not _envelope_ok(value, "refresh", _REFRESH_REQUIRED, _REFRESH_OPTIONAL):
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
    if not _envelope_ok(value, "leave", _LEAVE_REQUIRED, _LEAVE_OPTIONAL):
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
    if not _envelope_ok(value, "query", _QUERY_REQUIRED, _QUERY_OPTIONAL):
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
    if not _optional_int(value, clean, "limit", minimum=_MIN_QUERY_LIMIT, maximum=_MAX_QUERY_LIMIT):
        return None
    return clean


def validate_boot_ack(value: object) -> BootAck | None:
    """Strictly validate an ``ack`` frame (server→client)."""
    if not _envelope_ok(value, "ack", _ACK_REQUIRED, _ACK_OPTIONAL):
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
    if not _optional_int(value, clean, "retry_after", minimum=1):
        return None
    return clean


def validate_boot_response(value: object) -> BootResponse | None:
    """Strictly validate a ``response`` frame (server→client)."""
    if not _envelope_ok(value, "response", _RESPONSE_REQUIRED, _RESPONSE_OPTIONAL):
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
    if error is not None and error not in _BOOT_ERRORS:
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
    if not _optional_int(value, clean, "retry_after", minimum=1):
        return None
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
