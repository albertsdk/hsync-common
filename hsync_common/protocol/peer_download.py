# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Strict wire models for LAN peer-assisted downloads (ADR-0028).

The batch sources REST payloads and inventory WebSocket frames cross an
untrusted LAN boundary. This module is their Python single source of truth:
TypedDicts describe the wire shape, builders emit canonical payloads, and
validators reject malformed objects without partially accepting them.

Consumers: ``hsync-client`` (LAN master, inventory publisher and source
resolver), the Android protocol mirror, generated JSON Schemas/fixtures, and
the shared protocol contract tests.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from ipaddress import ip_address
from typing import Literal, NotRequired, TypedDict, TypeGuard
from urllib.parse import urlsplit

from hsync_common.constants import WS_MAX_MESSAGE_BYTES
from hsync_common.hashing import is_lower_sha256_hex
from hsync_common.models.event import is_valid_cid
from hsync_common.path_validation import is_valid_bucket_name, validate_remote_relpath
from hsync_common.text import compact_json_bytes

__all__ = [
    "P2P_INVENTORY_ACK_REASON_MAX_LENGTH",
    "P2P_INVENTORY_MAX_ENTRIES",
    "P2P_INVENTORY_MAX_FRAME_BYTES",
    "P2P_SERVE_SLOTS_MAX",
    "P2P_SERVE_SLOTS_MIN",
    "P2P_SOURCES_MAX_BODY_BYTES",
    "P2P_SOURCES_MAX_CANDIDATES",
    "P2P_SOURCES_MAX_FILES",
    "P2P_WIRE_INT_MAX",
    "P2PInventoryAckFrame",
    "P2PInventoryAckStatus",
    "P2PInventoryDeleteEntry",
    "P2PInventoryEntry",
    "P2PInventoryFrame",
    "P2PInventoryMode",
    "P2PInventoryUpsertEntry",
    "P2PSourceCandidate",
    "P2PSourceFile",
    "P2PSourcesRequest",
    "P2PSourcesResponse",
    "P2PSourcesResponseFile",
    "build_p2p_inventory_ack",
    "build_p2p_inventory_frame",
    "build_p2p_sources_request",
    "build_p2p_sources_response",
    "is_valid_serve_slots",
    "validate_p2p_inventory_ack",
    "validate_p2p_inventory_frame",
    "validate_p2p_sources_request",
    "validate_p2p_sources_response",
]

# REST and WSS payloads share the existing 2 MiB metadata ceiling. Consumers
# must enforce these limits on raw encoded bytes before JSON decoding; the
# validators also ensure that the canonical compact representation fits.
P2P_SOURCES_MAX_BODY_BYTES = WS_MAX_MESSAGE_BYTES
P2P_INVENTORY_MAX_FRAME_BYTES = WS_MAX_MESSAGE_BYTES

P2P_SOURCES_MAX_FILES = 500
P2P_SOURCES_MAX_CANDIDATES = 8
P2P_INVENTORY_MAX_ENTRIES = 500

# Concurrent response bodies a seeder accepts for one requester. The value is
# advertised by the seeder on the authenticated LAN WebSocket session, echoed by
# the master in a source candidate, and used by the requester as its per-seeder
# admission limit: the bound is part of the contract, not a local guess.
P2P_SERVE_SLOTS_MIN = 1
P2P_SERVE_SLOTS_MAX = 32
P2P_WIRE_INT_MAX = (1 << 63) - 1
P2P_INVENTORY_ACK_REASON_MAX_LENGTH = 64

type P2PInventoryMode = Literal["snapshot", "delta"]
type P2PInventoryAckStatus = Literal["ok", "resync", "rejected"]

_SOURCE_FILE_KEYS = frozenset({"path", "sha256"})
_SOURCES_REQUEST_KEYS = frozenset({"cid", "files"})
_SOURCE_CANDIDATE_KEYS = frozenset({"cid", "download_url", "cert_fp", "compression", "serve_slots"})
_SOURCES_RESPONSE_FILE_KEYS = frozenset({"path", "sha256", "sources"})
_SOURCES_RESPONSE_KEYS = frozenset({"files"})
_INVENTORY_FRAME_KEYS = frozenset({"type", "gen", "seq", "mode", "more", "entries"})
_INVENTORY_UPSERT_KEYS = frozenset({"path", "sha256", "size"})
_INVENTORY_DELETE_KEYS = frozenset({"path", "deleted"})
_INVENTORY_ACK_KEYS = frozenset({"type", "gen", "seq", "status"})
_INVENTORY_REJECTED_ACK_KEYS = _INVENTORY_ACK_KEYS | {"reason"}
_ACK_REASON_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class P2PSourceFile(TypedDict):
    """One content identity requested from the LAN master."""

    path: str
    sha256: str


class P2PSourcesRequest(TypedDict):
    """Requester -> master body for ``POST .../files/sources``."""

    cid: str
    files: list[P2PSourceFile]


class P2PSourceCandidate(TypedDict):
    """One exact-hash seeder endpoint returned by the master.

    ``serve_slots`` is the seeder's advertised concurrent-read capacity. The
    requester treats it as its own admission limit for that CID, so it does not
    have to discover the limit by provoking ``503`` responses.
    """

    cid: str
    download_url: str
    cert_fp: str
    compression: bool
    serve_slots: int


class P2PSourcesResponseFile(TypedDict):
    """Candidates for one requested ``(path, sha256)`` identity."""

    path: str
    sha256: str
    sources: list[P2PSourceCandidate]


class P2PSourcesResponse(TypedDict):
    """Master -> requester batch source lookup response."""

    files: list[P2PSourcesResponseFile]


class P2PInventoryUpsertEntry(TypedDict):
    """Regular file currently available from a seeder."""

    path: str
    sha256: str
    size: int


class P2PInventoryDeleteEntry(TypedDict):
    """Delta operation removing one path from a seeder inventory."""

    path: str
    deleted: Literal[True]


type P2PInventoryEntry = P2PInventoryUpsertEntry | P2PInventoryDeleteEntry


class P2PInventoryFrame(TypedDict):
    """Seeder -> master inventory snapshot chunk or atomic delta."""

    type: Literal["inventory"]
    gen: int
    seq: int
    mode: P2PInventoryMode
    more: bool
    entries: list[P2PInventoryEntry]


class P2PInventoryAckFrame(TypedDict):
    """Master -> seeder cumulative inventory acknowledgement."""

    type: Literal["inventory_ack"]
    gen: int
    seq: int
    status: P2PInventoryAckStatus
    reason: NotRequired[str]


def _is_exact_object(value: object, keys: frozenset[str]) -> TypeGuard[dict[str, object]]:
    """Return whether *value* is a dict containing exactly *keys*."""
    return isinstance(value, dict) and set(value) == keys


def _is_wire_int(value: object) -> TypeGuard[int]:
    """Accept non-boolean, non-negative signed 64-bit wire integers."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= P2P_WIRE_INT_MAX


def _is_lower_sha256(value: object) -> TypeGuard[str]:
    """Accept only the canonical lowercase SHA-256 wire representation."""
    return is_lower_sha256_hex(value)


def is_valid_serve_slots(value: object) -> TypeGuard[int]:
    """True when *value* is a wire-valid seeder slot count.

    Bounded by :data:`P2P_SERVE_SLOTS_MIN`/``_MAX``; ``bool`` is rejected even
    though it is an ``int`` subclass, because ``true``/``false`` are not slot
    counts. Consumers: ``hsync-client`` (seeder advertisement, master candidate
    build, requester admission), the Android protocol mirror, and the shared
    protocol tests.
    """
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and P2P_SERVE_SLOTS_MIN <= value <= P2P_SERVE_SLOTS_MAX
    )


def _validated_path(value: object) -> str | None:
    """Return the canonical bucket-relative path or ``None``."""
    if not isinstance(value, str):
        return None
    try:
        return validate_remote_relpath(value)
    except UnicodeError:
        # json.loads accepts escaped lone surrogates, but they are not valid
        # UTF-8 filesystem paths and must not escape as UnicodeEncodeError.
        return None


def _fits_encoded_limit(value: object, limit: int) -> bool:
    """Whether the canonical compact UTF-8 JSON representation is bounded."""
    try:
        encoded = compact_json_bytes(value)
    except (TypeError, ValueError, UnicodeError):
        return False
    return len(encoded) <= limit


def _is_download_url(value: object) -> TypeGuard[str]:
    """Validate a complete HTTPS LAN file-download endpoint."""
    if (
        not isinstance(value, str)
        or not value.startswith("https://")
        or "?" in value
        or "#" in value
        or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in value)
    ):
        return False
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except (UnicodeError, ValueError):
        return False
    if (
        parts.scheme != "https"
        or not host
        or port is None
        or not 1 <= port <= 65535
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or "%" in host
    ):
        return False
    try:
        address = ip_address(host)
    except ValueError:
        return False
    if address.version == 6 and not parts.netloc.startswith("["):
        return False

    route = parts.path.split("/")
    return (
        len(route) == 7
        and route[0] == ""
        and route[1:4] == ["api", "v1", "buckets"]
        and is_valid_bucket_name(route[4])
        and route[5:] == ["files", "download"]
    )


def _validate_source_file(value: object) -> P2PSourceFile | None:
    if not _is_exact_object(value, _SOURCE_FILE_KEYS):
        return None
    path = _validated_path(value["path"])
    digest = value["sha256"]
    if path is None or not _is_lower_sha256(digest):
        return None
    return P2PSourceFile(path=path, sha256=digest)


def _validate_source_candidate(value: object) -> P2PSourceCandidate | None:
    if not _is_exact_object(value, _SOURCE_CANDIDATE_KEYS):
        return None
    cid = value["cid"]
    download_url = value["download_url"]
    cert_fp = value["cert_fp"]
    compression = value["compression"]
    serve_slots = value["serve_slots"]
    if (
        not is_valid_cid(cid)
        or not _is_download_url(download_url)
        or not _is_lower_sha256(cert_fp)
        or not isinstance(compression, bool)
        or not is_valid_serve_slots(serve_slots)
    ):
        return None
    return P2PSourceCandidate(
        cid=cid,
        download_url=download_url,
        cert_fp=cert_fp,
        compression=compression,
        serve_slots=serve_slots,
    )


def validate_p2p_sources_request(value: object) -> P2PSourcesRequest | None:
    """Strictly validate and canonicalize a batch LAN sources request."""
    if not _is_exact_object(value, _SOURCES_REQUEST_KEYS):
        return None
    cid = value["cid"]
    files = value["files"]
    if not is_valid_cid(cid) or not isinstance(files, list):
        return None
    if not 1 <= len(files) <= P2P_SOURCES_MAX_FILES:
        return None

    clean_files: list[P2PSourceFile] = []
    seen_paths: set[str] = set()
    for item in files:
        clean = _validate_source_file(item)
        if clean is None or clean["path"] in seen_paths:
            return None
        seen_paths.add(clean["path"])
        clean_files.append(clean)
    clean = P2PSourcesRequest(cid=cid, files=clean_files)
    return clean if _fits_encoded_limit(clean, P2P_SOURCES_MAX_BODY_BYTES) else None


def validate_p2p_sources_response(value: object) -> P2PSourcesResponse | None:
    """Strictly validate and canonicalize a batch LAN sources response."""
    if not _is_exact_object(value, _SOURCES_RESPONSE_KEYS):
        return None
    files = value["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= P2P_SOURCES_MAX_FILES:
        return None

    clean_files: list[P2PSourcesResponseFile] = []
    seen_paths: set[str] = set()
    for item in files:
        if not _is_exact_object(item, _SOURCES_RESPONSE_FILE_KEYS):
            return None
        path = _validated_path(item["path"])
        digest = item["sha256"]
        sources = item["sources"]
        if (
            path is None
            or path in seen_paths
            or not _is_lower_sha256(digest)
            or not isinstance(sources, list)
            or len(sources) > P2P_SOURCES_MAX_CANDIDATES
        ):
            return None

        clean_sources: list[P2PSourceCandidate] = []
        seen_cids: set[str] = set()
        for source in sources:
            clean_source = _validate_source_candidate(source)
            if clean_source is None or clean_source["cid"] in seen_cids:
                return None
            seen_cids.add(clean_source["cid"])
            clean_sources.append(clean_source)

        seen_paths.add(path)
        clean_files.append(P2PSourcesResponseFile(path=path, sha256=digest, sources=clean_sources))
    clean = P2PSourcesResponse(files=clean_files)
    return clean if _fits_encoded_limit(clean, P2P_SOURCES_MAX_BODY_BYTES) else None


def _validate_inventory_upsert(value: object) -> P2PInventoryUpsertEntry | None:
    if not _is_exact_object(value, _INVENTORY_UPSERT_KEYS):
        return None
    path = _validated_path(value["path"])
    digest = value["sha256"]
    size = value["size"]
    if path is None or not _is_lower_sha256(digest) or not _is_wire_int(size):
        return None
    return P2PInventoryUpsertEntry(path=path, sha256=digest, size=size)


def _validate_inventory_delete(value: object) -> P2PInventoryDeleteEntry | None:
    if not _is_exact_object(value, _INVENTORY_DELETE_KEYS):
        return None
    path = _validated_path(value["path"])
    if path is None or value["deleted"] is not True:
        return None
    return P2PInventoryDeleteEntry(path=path, deleted=True)


def validate_p2p_inventory_frame(value: object) -> P2PInventoryFrame | None:
    """Strictly validate one inventory snapshot chunk or independent delta."""
    if not _is_exact_object(value, _INVENTORY_FRAME_KEYS):
        return None
    if value["type"] != "inventory":
        return None
    gen = value["gen"]
    seq = value["seq"]
    mode = value["mode"]
    more = value["more"]
    entries = value["entries"]
    if (
        not _is_wire_int(gen)
        or not _is_wire_int(seq)
        or mode not in ("snapshot", "delta")
        or not isinstance(more, bool)
        or not isinstance(entries, list)
        or len(entries) > P2P_INVENTORY_MAX_ENTRIES
    ):
        return None
    if mode == "delta" and (more or not entries):
        return None
    if mode == "snapshot" and not entries and (more or seq != 0):
        return None

    clean_entries: list[P2PInventoryEntry] = []
    seen_paths: set[str] = set()
    for entry in entries:
        clean: P2PInventoryEntry | None
        if mode == "snapshot":
            clean = _validate_inventory_upsert(entry)
        else:
            clean = _validate_inventory_upsert(entry) or _validate_inventory_delete(entry)
        if clean is None or clean["path"] in seen_paths:
            return None
        seen_paths.add(clean["path"])
        clean_entries.append(clean)

    clean = P2PInventoryFrame(
        type="inventory",
        gen=gen,
        seq=seq,
        mode=mode,
        more=more,
        entries=clean_entries,
    )
    return clean if _fits_encoded_limit(clean, P2P_INVENTORY_MAX_FRAME_BYTES) else None


def validate_p2p_inventory_ack(value: object) -> P2PInventoryAckFrame | None:
    """Strictly validate an ``inventory_ack`` frame and its status payload."""
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    expected_keys = _INVENTORY_REJECTED_ACK_KEYS if status == "rejected" else _INVENTORY_ACK_KEYS
    if set(value) != expected_keys or value.get("type") != "inventory_ack":
        return None
    gen = value.get("gen")
    seq = value.get("seq")
    if not _is_wire_int(gen) or not _is_wire_int(seq):
        return None
    if status not in ("ok", "resync", "rejected"):
        return None

    frame = P2PInventoryAckFrame(type="inventory_ack", gen=gen, seq=seq, status=status)
    if status == "rejected":
        reason = value.get("reason")
        if not isinstance(reason, str) or not _ACK_REASON_RE.fullmatch(reason):
            return None
        frame["reason"] = reason
    return frame


def _require_valid[T](value: T | None, kind: str) -> T:
    if value is None:
        raise ValueError(f"invalid {kind}")
    return value


def build_p2p_sources_request(*, cid: str, files: Iterable[P2PSourceFile]) -> P2PSourcesRequest:
    """Build a canonical batch LAN sources request or raise ``ValueError``."""
    payload = {"cid": cid, "files": list(files)}
    return _require_valid(validate_p2p_sources_request(payload), "LAN sources request")


def build_p2p_sources_response(*, files: Iterable[P2PSourcesResponseFile]) -> P2PSourcesResponse:
    """Build a canonical batch LAN sources response or raise ``ValueError``."""
    payload = {"files": list(files)}
    return _require_valid(validate_p2p_sources_response(payload), "LAN sources response")


def build_p2p_inventory_frame(
    *,
    gen: int,
    seq: int,
    mode: P2PInventoryMode,
    more: bool,
    entries: Iterable[P2PInventoryEntry],
) -> P2PInventoryFrame:
    """Build a canonical inventory frame or raise ``ValueError``."""
    payload = {
        "type": "inventory",
        "gen": gen,
        "seq": seq,
        "mode": mode,
        "more": more,
        "entries": list(entries),
    }
    return _require_valid(validate_p2p_inventory_frame(payload), "LAN inventory frame")


def build_p2p_inventory_ack(
    *,
    gen: int,
    seq: int,
    status: P2PInventoryAckStatus,
    reason: str | None = None,
) -> P2PInventoryAckFrame:
    """Build a canonical inventory acknowledgement or raise ``ValueError``."""
    payload: dict[str, object] = {
        "type": "inventory_ack",
        "gen": gen,
        "seq": seq,
        "status": status,
    }
    if reason is not None:
        payload["reason"] = reason
    return _require_valid(validate_p2p_inventory_ack(payload), "LAN inventory acknowledgement")
