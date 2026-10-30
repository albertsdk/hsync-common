# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""``rdv/1`` rendezvous-protocol mirror for the client (SSOT = ``hsync-rendezvous``).

The canonical specification and the canonical golden fixtures live in the
``hsync-rendezvous`` repository (``protocol-spec/rdv-1.md`` and ``fixtures/``);
this module is a *mirror* of that contract for the consumers that live in this
monorepo — today the ``hsync-client`` rdv rendezvous and the
shared fixtures/drift tests. The daemon keeps its own frame models and never
imports this mirror (the fixtures are the cross-language contract), but its
Python v1 does reuse a small set of generic ``hsync-common`` utilities
(``ssl_utils``, ``CID_PATTERN``, ``is_valid_bucket_name``) — see ADR-0033. A
drift test (``tests/test_protocol_rendezvous.py``) compares the mirrored fixtures
against the canonical ``hsync-rendezvous/fixtures/`` bytes so the two copies
cannot diverge silently.

Like the rest of the protocol package this mirror is dependency-free: TypedDicts
describe the wire shape and strict ``validate_*`` helpers reject unknown or
malformed fields without partially accepting them (the same strictness the
rendezvous's ``extra="forbid"`` models provide).

Besides the advisory ``capacity`` hint, ``register`` and ``peers[]`` carry the
**election advertisement** (``server_ready``/``prefer_master``/``never_master``/
``startup_time``/``sync_direction``) — the same values the mDNS TXT record
carries, relayed verbatim by the rendezvous so both rendezvous plans feed the one
shared election algorithm in :mod:`hsync_common.protocol.p2p`. The rendezvous never
interprets them and they are not authenticated (the data plane authenticates
identity by certificate pinning); the vocabulary is the canonical sync-direction
set from :mod:`hsync_common.protocol.pairing`.

The **data relay** frames (``relay_listen``/``relay_ping``/``relay_connect``/
``relay_attach`` and the ``relay_*`` replies) carry the peers' TLS bytes through
the node, so two peers that no inbound NAT mapping reaches can still run the
``p2p/1`` data plane. The relayed stream is opaque: the node never sees content,
names or credentials, and the peers keep authenticating each other by
certificate pinning.

Consumers: ``hsync-client`` (rendezvous register/refresh/query and the data relay),
shared fixtures/tests.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Literal, NotRequired, TypedDict

from hsync_common.endpoint import is_valid_endpoint_host
from hsync_common.models.event import CID_PATTERN, is_valid_cid
from hsync_common.path_validation import is_valid_bucket_name
from hsync_common.protocol.p2p import SYNC_DIRECTION_BIDIRECTIONAL
from hsync_common.protocol.pairing import (
    SYNC_DIRECTION_DOWNLOAD_ONLY,
    SYNC_DIRECTION_UPLOAD_ONLY,
    parse_fingerprint,
)
from hsync_common.protocol.rdv_tokens import (
    BUCKET_TOKEN_LEN,
    constant_time_equals,
    derive_bucket_token,
    is_valid_bucket_token,
    verify_bucket_token,
)

__all__ = [
    "RDV_ALPN",
    "BUCKET_TOKEN_LEN",
    "CAPACITY_MAX",
    "CID_PATTERN",
    "PROTOCOL_VERSION_RDV",
    "RELAY_ID_LEN",
    "RdvAck",
    "RdvError",
    "RdvFrame",
    "RdvLeave",
    "RdvPeer",
    "RdvQuery",
    "RdvRefresh",
    "RdvRegister",
    "RdvRelayAttach",
    "RdvRelayConnect",
    "RdvRelayError",
    "RdvRelayIncoming",
    "RdvRelayListen",
    "RdvRelayListening",
    "RdvRelayOk",
    "RdvRelayPing",
    "RdvResponse",
    "BucketProto",
    "Endpoint",
    "ObservedEndpoint",
    "constant_time_equals",
    "derive_bucket_token",
    "is_valid_bucket_token",
    "validate_rdv_ack",
    "validate_rdv_frame",
    "validate_rdv_relay_attach",
    "validate_rdv_relay_connect",
    "validate_rdv_relay_error",
    "validate_rdv_relay_incoming",
    "validate_rdv_relay_listen",
    "validate_rdv_relay_listening",
    "validate_rdv_relay_ok",
    "validate_rdv_relay_ping",
    "validate_rdv_response",
    "verify_bucket_token",
]

# Per-channel protocol version. Bump the suffix on any breaking change to the
# rendezvous channel's wire shape; peers then hard-fail instead of drifting.
PROTOCOL_VERSION_RDV: Literal["rdv/1"] = "rdv/1"

# QUIC ALPN offered by the rendezvous's TLS handshake.
RDV_ALPN = "hsync-rdv/1"

# hex(32 bytes) = 64 chars. Absent = open bucket. The token grammar and the
# derivation live in ``protocol/rdv_tokens.py`` (shared with the rendezvous).
BucketProto = Literal["tcp", "udp"]

# Uniform refusal codes on a ``response``/``relay_error`` frame: ``token_required``
# (authorization, no bucket-existence oracle), ``rate_limited`` (per-source/
# per-(IP,bucket) limit; ``retry_after`` = limiter refill), ``overloaded`` (the
# node is at its host-derived capacity ceiling; ``retry_after`` is advisory
# backpressure, not a client abuse signal) and ``relay_unavailable`` (no data
# relay: disabled on this node, no listener for the target CID, or the acceptor
# did not attach in time). Mirrors ``hsync_rendezvous.protocol.RdvError``.
RdvError = Literal["token_required", "rate_limited", "overloaded", "relay_unavailable"]
_RDV_ERRORS = ("token_required", "rate_limited", "overloaded", "relay_unavailable")

# Data-relay session identifier: hex(16 bytes) = 32 characters, chosen randomly
# by the node per pairing. It is only meaningful to the two paired peers, so a
# guess that does not match a live pending session attaches to nothing.
RELAY_ID_LEN = 32
_RELAY_ID_PATTERN = f"^[0-9a-f]{{{RELAY_ID_LEN}}}$"

# Advisory service-capacity hint domain (``0..32``; ``0`` = not a peer-download
# seeder). Mirrors the authenticated ``serve_slots`` range (1..32); the rendezvous
# relays the value in ``query`` responses but never treats it as authoritative
# (ADR-0030) — the authoritative value stays on the authenticated WSS handshake.
CAPACITY_MAX = 32

# Canonical sync-direction vocabulary (SSOT: :mod:`hsync_common.protocol.p2p`
# and :mod:`hsync_common.protocol.pairing`). The election advertisement on
# ``rdv/1`` reuses the same values as the mDNS TXT record, so both rendezvous
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

# Wire bounds, mirrored from the rendezvous models. Bucket names are bounded by
# ``is_valid_bucket_name`` (``MAX_BUCKET_NAME_LENGTH``), not by a length here.
_MAX_GROUP_LEN = 128
_MAX_CERT_FP_LEN = 256
_MAX_VERSION_LEN = 64
_MAX_ENDPOINTS = 16
_MIN_QUERY_LIMIT = 1
_MAX_QUERY_LIMIT = 50
_MIN_TTL = 1
_MAX_TTL = 3600


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


class RdvRegister(TypedDict):
    """Client announces presence in a bucket (first contact).

    ``capacity`` is the advisory service-capacity hint: the number of
    concurrent peer-download reads the peer declares it can serve right now
    (``0`` = not a seeder). The rendezvous relays it in ``query`` responses; the
    authoritative value is the authenticated ``serve_slots`` (ADR-0030).

    ``server_ready``/``prefer_master``/``never_master``/``startup_time``/
    ``sync_direction`` are the **election advertisement**, the same values the
    mDNS TXT record carries. The rendezvous relays them verbatim in ``query``
    responses so a rendezvous-discovered peer ranks exactly like an mDNS one; it
    never interprets them and never treats them as authoritative (a peer can
    claim any value, and the data plane authenticates identity by certificate
    pinning). A changed advertisement requires a new ``register`` — ``refresh``
    never mutates them.
    """

    protocol_version: Literal["rdv/1"]
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
    prefer_master: NotRequired[bool]
    never_master: NotRequired[bool]
    startup_time: NotRequired[float]
    sync_direction: NotRequired[str]


class RdvRefresh(TypedDict):
    """Client renews its TTL (and/or connected count)."""

    protocol_version: Literal["rdv/1"]
    type: Literal["refresh"]
    cid: str
    bucket: str
    group: NotRequired[str]
    bucket_token: NotRequired[str]
    connected: NotRequired[int]


class RdvLeave(TypedDict):
    """Client announces departure."""

    protocol_version: Literal["rdv/1"]
    type: Literal["leave"]
    cid: str
    bucket: str
    bucket_token: NotRequired[str]


class RdvQuery(TypedDict):
    """Client asks for a random sample of peers. Only generic — no file targeting."""

    protocol_version: Literal["rdv/1"]
    type: Literal["query"]
    bucket: str
    group: NotRequired[str]
    bucket_token: NotRequired[str]
    limit: NotRequired[int]


class RdvAck(TypedDict):
    """Server reply to register/refresh: STUN-echo observed endpoint + TTL."""

    protocol_version: Literal["rdv/1"]
    type: Literal["ack"]
    observed_endpoint: ObservedEndpoint
    ttl: int
    server_time: str
    retry_after: NotRequired[int]


class RdvPeer(TypedDict):
    """A single advertised peer in a RdvResponse.

    ``endpoints`` is the peer's advertised candidate list, relayed in order and
    capped by the node (at most 4 entries; a register that advertised none is
    relayed as a single-element list with the observed source endpoint). A
    requester tries the candidates, preferring a host/LAN one reachable from its
    own network, so peers behind the same NAT — where the public endpoint has no
    hairpin route — still connect locally.

    ``capacity`` is the peer's advisory service-capacity hint as relayed from
    its ``register`` (``0`` = not a seeder); ``reachable`` is derived from
    ``bool(endpoints)``. Neither is authoritative (ADR-0030).

    The election-advertisement fields are relayed verbatim from the peer's
    ``register`` (defaults when it advertised none): ``server_ready`` (it is
    currently serving as master), ``prefer_master``/``never_master`` (operator
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
    connected: NotRequired[int]
    reachable: bool
    server_ready: bool
    prefer_master: bool
    never_master: bool
    startup_time: float
    sync_direction: str
    group: NotRequired[str]


class RdvResponse(TypedDict):
    """Server reply to query: random sample of peers (or a uniform refusal)."""

    protocol_version: Literal["rdv/1"]
    type: Literal["response"]
    peers: list[RdvPeer]
    count: int
    ttl: int
    error: NotRequired[RdvError]
    retry_after: NotRequired[int]


class RdvRelayListen(TypedDict):
    """A serving peer asks the node to open a data relay (``relay_listen``).

    The stream carrying this frame becomes the **control** stream of one
    listener: the node answers ``relay_listening`` and then pushes one
    ``relay_incoming`` per requester, while the peer may answer with
    ``relay_ping`` lines. Registration is accepted only from the current owner
    of the ``(cid, bucket, group)`` rendezvous record, so a peer cannot open a
    relay in someone else's name.
    """

    protocol_version: Literal["rdv/1"]
    type: Literal["relay_listen"]
    cid: str
    bucket: str
    group: NotRequired[str]
    bucket_token: NotRequired[str]


class RdvRelayPing(TypedDict):
    """Keepalive on a listener's control stream (``relay_ping``, no reply)."""

    protocol_version: Literal["rdv/1"]
    type: Literal["relay_ping"]
    cid: str
    bucket: str


class RdvRelayConnect(TypedDict):
    """A requester asks to be paired with a listening peer (``relay_connect``).

    Sent on a **fresh** stream. The node answers ``relay_ok`` — after which the
    rest of the stream is opaque TLS — or ``relay_error`` and a close.
    """

    protocol_version: Literal["rdv/1"]
    type: Literal["relay_connect"]
    cid: str
    bucket: str
    target_cid: str
    group: NotRequired[str]
    bucket_token: NotRequired[str]


class RdvRelayAttach(TypedDict):
    """A listener attaches the stream that carries one relayed session.

    Sent as the first (and only framed) line of a fresh stream; every following
    byte is opaque TLS in both directions. ``cid``/``bucket`` must match the
    listener that was told about ``relay_id``.
    """

    protocol_version: Literal["rdv/1"]
    type: Literal["relay_attach"]
    cid: str
    bucket: str
    relay_id: str
    bucket_token: NotRequired[str]


class RdvRelayListening(TypedDict):
    """Server→listener: the relay listener is registered (``relay_listening``)."""

    protocol_version: Literal["rdv/1"]
    type: Literal["relay_listening"]
    ttl: int


class RdvRelayIncoming(TypedDict):
    """Server→listener: a requester wants a session (``relay_incoming``).

    ``cid`` is the requester's CID, so the listener can bound per-peer
    concurrency; ``expires_in`` is the seconds left to attach the session.
    """

    protocol_version: Literal["rdv/1"]
    type: Literal["relay_incoming"]
    relay_id: str
    cid: str
    expires_in: int


class RdvRelayOk(TypedDict):
    """Server→requester: the pairing exists and the stream is now opaque.

    Written before any relayed byte, so a requester that buffers pipelined input
    stays framed.
    """

    protocol_version: Literal["rdv/1"]
    type: Literal["relay_ok"]
    relay_id: str


class RdvRelayError(TypedDict):
    """Server→client: the relay request was refused (``relay_error``)."""

    protocol_version: Literal["rdv/1"]
    type: Literal["relay_error"]
    error: RdvError
    retry_after: NotRequired[int]


# Client→server frames, dispatched on ``type``. ``RdvResponse``/``RdvAck``/
# ``RdvPeer`` and the ``relay_*`` server replies are server→client and
# deliberately excluded from the request union: they are never validated on the
# input path.
RdvFrame = (
    RdvRegister
    | RdvRefresh
    | RdvLeave
    | RdvQuery
    | RdvRelayListen
    | RdvRelayPing
    | RdvRelayConnect
    | RdvRelayAttach
)

_REGISTER_REQUIRED = frozenset({"protocol_version", "type", "cid", "bucket", "cert_fp", "version"})
_REGISTER_OPTIONAL = frozenset(
    {
        "group",
        "bucket_token",
        "connected",
        "capacity",
        "endpoints",
        "server_ready",
        "prefer_master",
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
_RELAY_LISTEN_REQUIRED = frozenset({"protocol_version", "type", "cid", "bucket"})
_RELAY_LISTEN_OPTIONAL = frozenset({"group", "bucket_token"})
_RELAY_PING_REQUIRED = frozenset({"protocol_version", "type", "cid", "bucket"})
_RELAY_CONNECT_REQUIRED = frozenset({"protocol_version", "type", "cid", "bucket", "target_cid"})
_RELAY_CONNECT_OPTIONAL = frozenset({"group", "bucket_token"})
_RELAY_ATTACH_REQUIRED = frozenset({"protocol_version", "type", "cid", "bucket", "relay_id"})
_RELAY_ATTACH_OPTIONAL = frozenset({"bucket_token"})
_RELAY_LISTENING_REQUIRED = frozenset({"protocol_version", "type", "ttl"})
_RELAY_INCOMING_REQUIRED = frozenset({"protocol_version", "type", "relay_id", "cid", "expires_in"})
_RELAY_OK_REQUIRED = frozenset({"protocol_version", "type", "relay_id"})
_RELAY_ERROR_REQUIRED = frozenset({"protocol_version", "type", "error"})
_RELAY_ERROR_OPTIONAL = frozenset({"retry_after"})
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
        "prefer_master",
        "never_master",
        "startup_time",
        "sync_direction",
    }
)
_PEER_OPTIONAL = frozenset({"group", "connected"})
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
    ``protocol_version``/``type`` match, so each ``validate_rdv_*`` only states
    its window of required/optional keys instead of repeating the prologue.
    """
    if not isinstance(value, Mapping) or not _is_object(value, required, optional):
        return False
    return value["protocol_version"] == PROTOCOL_VERSION_RDV and value["type"] == frame_type


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

    Explicit ``null`` is rejected, like the rendezvous's pydantic models (a
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
    ``peers[]`` side (every key is required, the rendezvous always relays them).
    Returns False on any malformed value so the caller rejects the whole frame.
    """
    for key in ("server_ready", "prefer_master", "never_master"):
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


def _is_relay_id(value: object) -> bool:
    """True for a canonical relay session id (32 lowercase hex characters)."""
    return (
        isinstance(value, str)
        and len(value) == RELAY_ID_LEN
        and all(char in "0123456789abcdef" for char in value)
    )


def _validate_endpoint(value: object) -> Endpoint | None:
    if not _is_object(value, _ENDPOINT_KEYS, frozenset()):
        return None
    proto = value["proto"]
    host = value["host"]
    port = value["port"]
    if (
        proto not in ("tcp", "udp")
        or not _is_str(host, max_len=255)
        or not is_valid_endpoint_host(host)
        or not _is_port(port)
    ):
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


def _validate_peer(value: object) -> RdvPeer | None:
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
        or parse_fingerprint(cert_fp) is None
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
    clean = RdvPeer(
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
    if not _optional_connected(value, clean):
        return None
    return clean


def validate_rdv_register(value: object) -> RdvRegister | None:
    """Strictly validate a ``register`` frame."""
    if not _envelope_ok(value, "register", _REGISTER_REQUIRED, _REGISTER_OPTIONAL):
        return None
    # ``capacity`` (default 0) and ``endpoints`` (default []) are optional on the
    # wire: the first STUN register has no known public endpoint yet, and a
    # non-seeder declares no capacity. The election advertisement is optional as
    # well (defaults: not serving, no pin, unknown startup, bidirectional) and,
    # like capacity/endpoints, a changed value requires a new ``register``:
    # ``refresh`` never mutates it. Explicit ``null`` is still rejected, like the
    # rendezvous's pydantic models.
    capacity = value.get("capacity", 0)
    endpoints = value.get("endpoints", [])
    if (
        not is_valid_cid(value["cid"])
        or not is_valid_bucket_name(value["bucket"])
        or not _is_str(value["cert_fp"], max_len=_MAX_CERT_FP_LEN)
        or parse_fingerprint(value["cert_fp"]) is None
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
    clean = RdvRegister(
        protocol_version=PROTOCOL_VERSION_RDV,
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


def validate_rdv_refresh(value: object) -> RdvRefresh | None:
    """Strictly validate a ``refresh`` frame."""
    if not _envelope_ok(value, "refresh", _REFRESH_REQUIRED, _REFRESH_OPTIONAL):
        return None
    if not is_valid_cid(value["cid"]) or not is_valid_bucket_name(value["bucket"]):
        return None
    clean = RdvRefresh(
        protocol_version=PROTOCOL_VERSION_RDV,
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


def validate_rdv_leave(value: object) -> RdvLeave | None:
    """Strictly validate a ``leave`` frame."""
    if not _envelope_ok(value, "leave", _LEAVE_REQUIRED, _LEAVE_OPTIONAL):
        return None
    if not is_valid_cid(value["cid"]) or not is_valid_bucket_name(value["bucket"]):
        return None
    clean = RdvLeave(
        protocol_version=PROTOCOL_VERSION_RDV,
        type="leave",
        cid=value["cid"],
        bucket=value["bucket"],
    )
    if not _optional_token(value, clean):
        return None
    return clean


def validate_rdv_query(value: object) -> RdvQuery | None:
    """Strictly validate a ``query`` frame."""
    if not _envelope_ok(value, "query", _QUERY_REQUIRED, _QUERY_OPTIONAL):
        return None
    if not is_valid_bucket_name(value["bucket"]):
        return None
    clean = RdvQuery(
        protocol_version=PROTOCOL_VERSION_RDV,
        type="query",
        bucket=value["bucket"],
    )
    if not (_optional_str(value, clean, "group", _MAX_GROUP_LEN) and _optional_token(value, clean)):
        return None
    if not _optional_int(value, clean, "limit", minimum=_MIN_QUERY_LIMIT, maximum=_MAX_QUERY_LIMIT):
        return None
    return clean


def validate_rdv_relay_listen(value: object) -> RdvRelayListen | None:
    """Strictly validate a ``relay_listen`` frame."""
    if not _envelope_ok(value, "relay_listen", _RELAY_LISTEN_REQUIRED, _RELAY_LISTEN_OPTIONAL):
        return None
    if not is_valid_cid(value["cid"]) or not is_valid_bucket_name(value["bucket"]):
        return None
    clean = RdvRelayListen(
        protocol_version=PROTOCOL_VERSION_RDV,
        type="relay_listen",
        cid=value["cid"],
        bucket=value["bucket"],
    )
    if not (_optional_str(value, clean, "group", _MAX_GROUP_LEN) and _optional_token(value, clean)):
        return None
    return clean


def validate_rdv_relay_ping(value: object) -> RdvRelayPing | None:
    """Strictly validate a ``relay_ping`` frame."""
    if not _envelope_ok(value, "relay_ping", _RELAY_PING_REQUIRED, frozenset()):
        return None
    if not is_valid_cid(value["cid"]) or not is_valid_bucket_name(value["bucket"]):
        return None
    return RdvRelayPing(
        protocol_version=PROTOCOL_VERSION_RDV,
        type="relay_ping",
        cid=value["cid"],
        bucket=value["bucket"],
    )


def validate_rdv_relay_connect(value: object) -> RdvRelayConnect | None:
    """Strictly validate a ``relay_connect`` frame."""
    if not _envelope_ok(value, "relay_connect", _RELAY_CONNECT_REQUIRED, _RELAY_CONNECT_OPTIONAL):
        return None
    if (
        not is_valid_cid(value["cid"])
        or not is_valid_cid(value["target_cid"])
        or not is_valid_bucket_name(value["bucket"])
    ):
        return None
    clean = RdvRelayConnect(
        protocol_version=PROTOCOL_VERSION_RDV,
        type="relay_connect",
        cid=value["cid"],
        bucket=value["bucket"],
        target_cid=value["target_cid"],
    )
    if not (_optional_str(value, clean, "group", _MAX_GROUP_LEN) and _optional_token(value, clean)):
        return None
    return clean


def validate_rdv_relay_attach(value: object) -> RdvRelayAttach | None:
    """Strictly validate a ``relay_attach`` frame."""
    if not _envelope_ok(value, "relay_attach", _RELAY_ATTACH_REQUIRED, _RELAY_ATTACH_OPTIONAL):
        return None
    if (
        not is_valid_cid(value["cid"])
        or not is_valid_bucket_name(value["bucket"])
        or not _is_relay_id(value["relay_id"])
    ):
        return None
    clean = RdvRelayAttach(
        protocol_version=PROTOCOL_VERSION_RDV,
        type="relay_attach",
        cid=value["cid"],
        bucket=value["bucket"],
        relay_id=value["relay_id"],
    )
    if not _optional_token(value, clean):
        return None
    return clean


def validate_rdv_relay_listening(value: object) -> RdvRelayListening | None:
    """Strictly validate a ``relay_listening`` frame (server→client)."""
    if not _envelope_ok(value, "relay_listening", _RELAY_LISTENING_REQUIRED, frozenset()):
        return None
    if not _is_int(value["ttl"], minimum=_MIN_TTL, maximum=_MAX_TTL):
        return None
    return RdvRelayListening(
        protocol_version=PROTOCOL_VERSION_RDV,
        type="relay_listening",
        ttl=value["ttl"],
    )


def validate_rdv_relay_incoming(value: object) -> RdvRelayIncoming | None:
    """Strictly validate a ``relay_incoming`` frame (server→client)."""
    if not _envelope_ok(value, "relay_incoming", _RELAY_INCOMING_REQUIRED, frozenset()):
        return None
    if (
        not _is_relay_id(value["relay_id"])
        or not is_valid_cid(value["cid"])
        or not _is_int(value["expires_in"], minimum=1, maximum=_MAX_TTL)
    ):
        return None
    return RdvRelayIncoming(
        protocol_version=PROTOCOL_VERSION_RDV,
        type="relay_incoming",
        relay_id=value["relay_id"],
        cid=value["cid"],
        expires_in=value["expires_in"],
    )


def validate_rdv_relay_ok(value: object) -> RdvRelayOk | None:
    """Strictly validate a ``relay_ok`` frame (server→client)."""
    if not _envelope_ok(value, "relay_ok", _RELAY_OK_REQUIRED, frozenset()):
        return None
    if not _is_relay_id(value["relay_id"]):
        return None
    return RdvRelayOk(
        protocol_version=PROTOCOL_VERSION_RDV,
        type="relay_ok",
        relay_id=value["relay_id"],
    )


def validate_rdv_relay_error(value: object) -> RdvRelayError | None:
    """Strictly validate a ``relay_error`` frame (server→client)."""
    if not _envelope_ok(value, "relay_error", _RELAY_ERROR_REQUIRED, _RELAY_ERROR_OPTIONAL):
        return None
    error = value["error"]
    if error not in _RDV_ERRORS:
        return None
    clean = RdvRelayError(
        protocol_version=PROTOCOL_VERSION_RDV,
        type="relay_error",
        error=error,
    )
    if not _optional_int(value, clean, "retry_after", minimum=1):
        return None
    return clean


def validate_rdv_ack(value: object) -> RdvAck | None:
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
    clean = RdvAck(
        protocol_version=PROTOCOL_VERSION_RDV,
        type="ack",
        observed_endpoint=observed,
        ttl=value["ttl"],
        server_time=value["server_time"],
    )
    if not _optional_int(value, clean, "retry_after", minimum=1):
        return None
    return clean


def validate_rdv_response(value: object) -> RdvResponse | None:
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
    clean_peers: list[RdvPeer] = []
    for item in peers:
        clean_peer = _validate_peer(item)
        if clean_peer is None:
            return None
        clean_peers.append(clean_peer)
    if value["count"] != len(clean_peers):
        return None
    error = value.get("error")
    if error is not None and error not in _RDV_ERRORS:
        return None
    clean = RdvResponse(
        protocol_version=PROTOCOL_VERSION_RDV,
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


def validate_rdv_frame(value: object) -> RdvFrame | None:
    """Dispatch on ``type`` and strictly validate one client→server frame."""
    if not isinstance(value, Mapping):
        return None
    frame_type = value.get("type")
    if frame_type == "register":
        return validate_rdv_register(value)
    if frame_type == "refresh":
        return validate_rdv_refresh(value)
    if frame_type == "leave":
        return validate_rdv_leave(value)
    if frame_type == "query":
        return validate_rdv_query(value)
    if frame_type == "relay_listen":
        return validate_rdv_relay_listen(value)
    if frame_type == "relay_ping":
        return validate_rdv_relay_ping(value)
    if frame_type == "relay_connect":
        return validate_rdv_relay_connect(value)
    if frame_type == "relay_attach":
        return validate_rdv_relay_attach(value)
    return None
