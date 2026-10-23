# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Delta-transfer (rsync-style) wire models for HSYNC.

These dataclasses/TypedDicts describe the payloads exchanged by the delta
endpoints — block signatures of the base file, the ordered copy/data
operations that rebuild the new file, and the multipart metadata of a delta
apply request. They are the single source of truth mirrored by the Kotlin
implementation; the shapes must stay byte-compatible across platforms.

Integrity model: the weak checksum (Adler32, 32-bit) only *selects* candidate
blocks; correctness is guaranteed by the per-block strong checksum (SHA-256)
and by the final whole-file SHA-256 verification after reconstruction.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, NotRequired, TypedDict, TypeGuard

from hsync_common.constants import DELTA_MAX_OPS, DELTA_MAX_SIGNATURES
from hsync_common.hashing import is_sha256_hex

__all__ = [
    "OP_TYPE_COPY",
    "OP_TYPE_DATA",
    "BlockSignature",
    "BlockSignatureDict",
    "DeltaApplyMetadata",
    "DeltaApplyMetadataDict",
    "DeltaDownloadDict",
    "DeltaDownloadInstructionsDict",
    "DeltaInstructions",
    "DeltaInstructionsDict",
    "DeltaOp",
    "DeltaOpDict",
    "DeltaSignaturesDict",
    "delta_download_payload",
    "delta_signatures_payload",
    "parse_op_payload",
    "sanitize_block_signature",
    "sanitize_delta_op",
    "validate_op_bounds",
]

OP_TYPE_COPY = "copy"
OP_TYPE_DATA = "data"

_OpType = Literal["copy", "data"]

# Adler32 is a 32-bit unsigned value.
_ADLER32_MAX = 0xFFFFFFFF


class BlockSignatureDict(TypedDict):
    """Serialized signature of one base-file block."""

    index: int  # block index (0-based)
    offset: int  # byte offset of the block in the base file
    length: int  # block length (last block may be < block_size)
    weak: int  # Adler32 rolling checksum (32-bit unsigned)
    strong: str  # SHA-256 hex of the block


class DeltaOpDict(TypedDict):
    """Serialized delta operation.

    ``copy`` reads ``length`` bytes from the base file at ``offset``;
    ``data`` reads ``length`` bytes from the literal payload at
    ``data_offset``. ``offset`` and ``data_offset`` are mutually exclusive
    on the wire and always emitted (one of them is 0/ignored by the other
    kind) so the shape stays flat and schema-friendly.
    """

    type: str  # "copy" | "data"
    offset: int  # copy: byte offset in the base file (0 for data ops)
    length: int  # number of bytes this op contributes to the new file
    data_offset: int  # data: byte offset in the literal payload (0 for copy ops)


class DeltaInstructionsDict(TypedDict):
    """Serialized delta instructions (sender → receiver)."""

    new_sha256: str  # expected SHA-256 of the reconstructed file
    new_size: int  # expected size of the reconstructed file (ops coverage check)
    block_size: int  # block size used for signature/matching
    ops: list[DeltaOpDict]  # ordered operations
    base_sha256: NotRequired[str]  # upload only: SHA-256 of the base file


class DeltaDownloadInstructionsDict(TypedDict):
    """Instruction block inside a download-delta response.

    Reduced on purpose: the content hash and the block size are response-level
    fields, so only the coverage size and the ordered ops travel here.
    """

    new_size: int  # expected size of the reconstructed file (ops coverage check)
    ops: list[DeltaOpDict]  # ordered operations


class DeltaDownloadDict(TypedDict):
    """Response of a successful download-delta (server and P2P master)."""

    delta: Literal[True]
    block_size: int
    new_sha256: str
    instructions: DeltaDownloadInstructionsDict
    data_url: str  # single-use URL serving the literal payload
    data_size: int  # literal payload bytes (before any transfer encoding)
    compressed: bool  # payload is a single zstd frame


class DeltaSignaturesDict(TypedDict):
    """Response of the base-file signature listing (upload delta)."""

    block_size: int
    file_size: int
    sha256: str
    signatures: list[BlockSignatureDict]


class DeltaApplyMetadataDict(TypedDict):
    """Serialized metadata for POST /delta/apply (upload delta).

    Sent as a JSON part in multipart/form-data alongside the literal payload.
    The server uses these fields to validate the apply operation and update
    file metadata after successful reconstruction.
    """

    cid: str  # client ID (for event broadcasting and echo suppression)
    base_sha256: str  # SHA-256 of the base file (race check: 409 if changed)
    new_sha256: str  # expected SHA-256 of the reconstructed file (verification)
    new_size: int  # expected size of the reconstructed file (coverage check)
    block_size: int  # block size used for signature/matching
    compressed: bool  # whether the literal payload is zstd-compressed
    mtime: NotRequired[float]  # modification time (epoch seconds) to preserve
    permissions: NotRequired[str]  # octal permissions string (e.g., "644")
    ops: list[DeltaOpDict]  # ordered operations to rebuild the file


@dataclass(frozen=True, slots=True)
class BlockSignature:
    """Signature of a single base-file block (weak + strong checksum)."""

    index: int
    offset: int
    length: int
    weak: int
    strong: str

    def to_dict(self) -> BlockSignatureDict:
        """Serialize to the wire shape."""
        return BlockSignatureDict(
            index=self.index,
            offset=self.offset,
            length=self.length,
            weak=self.weak,
            strong=self.strong,
        )


@dataclass(frozen=True, slots=True)
class DeltaOp:
    """A single reconstruction operation (copy from base / data literal)."""

    type: _OpType
    length: int
    offset: int = 0  # copy ops: byte offset in the base file
    data_offset: int = 0  # data ops: byte offset in the literal payload

    @classmethod
    def copy(cls, offset: int, length: int) -> DeltaOp:
        """Build a copy op (bytes taken from the base file)."""
        return cls(type=OP_TYPE_COPY, offset=offset, length=length)

    @classmethod
    def data(cls, data_offset: int, length: int) -> DeltaOp:
        """Build a data op (bytes taken from the literal payload)."""
        return cls(type=OP_TYPE_DATA, data_offset=data_offset, length=length)

    def to_dict(self) -> DeltaOpDict:
        """Serialize to the wire shape."""
        return DeltaOpDict(
            type=self.type,
            offset=self.offset,
            length=self.length,
            data_offset=self.data_offset,
        )


@dataclass(frozen=True, slots=True)
class DeltaInstructions:
    """Ordered operations that rebuild the new file from base + literals."""

    new_sha256: str
    new_size: int
    block_size: int
    ops: tuple[DeltaOp, ...] = field(default_factory=tuple)
    base_sha256: str | None = None  # upload only

    def to_dict(self) -> DeltaInstructionsDict:
        """Serialize to the wire shape."""
        out = DeltaInstructionsDict(
            new_sha256=self.new_sha256,
            new_size=self.new_size,
            block_size=self.block_size,
            ops=[op.to_dict() for op in self.ops],
        )
        if self.base_sha256 is not None:
            out["base_sha256"] = self.base_sha256
        return out


@dataclass(frozen=True, slots=True)
class DeltaApplyMetadata:
    """Metadata for POST /delta/apply (upload delta).

    Sent as a JSON part in multipart/form-data alongside the literal payload.
    The server uses these fields to validate the apply operation and update
    file metadata after successful reconstruction.
    """

    cid: str
    base_sha256: str
    new_sha256: str
    new_size: int
    block_size: int
    compressed: bool
    ops: tuple[DeltaOp, ...] = field(default_factory=tuple)
    mtime: float | None = None
    permissions: str | None = None

    def to_dict(self) -> DeltaApplyMetadataDict:
        """Serialize to the wire shape."""
        out = DeltaApplyMetadataDict(
            cid=self.cid,
            base_sha256=self.base_sha256,
            new_sha256=self.new_sha256,
            new_size=self.new_size,
            block_size=self.block_size,
            compressed=self.compressed,
            ops=[op.to_dict() for op in self.ops],
        )
        if self.mtime is not None:
            out["mtime"] = self.mtime
        if self.permissions is not None:
            out["permissions"] = self.permissions
        return out


def _is_valid_non_negative_int(value: object) -> TypeGuard[int]:
    """Return True for real non-negative ints (bools are rejected)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_valid_positive_int(value: object) -> TypeGuard[int]:
    """Return True for real positive ints (bools are rejected)."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def sanitize_block_signature(value: object) -> BlockSignatureDict | None:
    """Validate an untrusted block-signature payload.

    Rejects malformed shapes (non-int fields, out-of-range weak checksum,
    non-SHA-256 strong checksum) so a hostile peer cannot crash or poison
    the matcher. Returns ``None`` when invalid.
    """
    if not isinstance(value, dict):
        return None
    index = value.get("index")
    offset = value.get("offset")
    length = value.get("length")
    weak = value.get("weak")
    strong = value.get("strong")

    if not _is_valid_non_negative_int(index):
        return None
    if not _is_valid_non_negative_int(offset):
        return None
    if not _is_valid_positive_int(length):
        return None
    if not _is_valid_non_negative_int(weak):
        return None
    if not (weak <= _ADLER32_MAX):
        return None
    if not is_sha256_hex(strong):
        return None

    return BlockSignatureDict(index=index, offset=offset, length=length, weak=weak, strong=strong)


def sanitize_delta_op(value: object) -> DeltaOpDict | None:
    """Validate an untrusted delta-op payload.

    Bounds are checked by the caller against the actual base file / literal
    payload sizes; here only the shape is enforced. Returns ``None`` when
    invalid.
    """
    if not isinstance(value, dict):
        return None
    op_type = value.get("type")
    offset = value.get("offset")
    length = value.get("length")
    data_offset = value.get("data_offset")

    if op_type not in (OP_TYPE_COPY, OP_TYPE_DATA):
        return None
    if not _is_valid_non_negative_int(offset):
        return None
    if not _is_valid_positive_int(length):
        return None
    if not _is_valid_non_negative_int(data_offset):
        return None

    return DeltaOpDict(type=op_type, offset=offset, length=length, data_offset=data_offset)


def _sanitize_list[T](
    value: object,
    *,
    cap: int,
    sanitize_item: Callable[[object], T | None],
) -> list[T] | None:
    """Validate a list of untrusted items, enforcing a count cap.

    Returns ``None`` when *value* is not a list, exceeds *cap* entries,
    or any item fails *sanitize_item*. Otherwise returns the cleaned list.
    """
    if not isinstance(value, list) or len(value) > cap:
        return None
    out: list[T] = []
    for item in value:
        clean = sanitize_item(item)
        if clean is None:
            return None
        out.append(clean)
    return out


def sanitize_signature_list(value: object) -> list[BlockSignatureDict] | None:
    """Validate an untrusted signature list, enforcing the wire count cap."""
    return _sanitize_list(value, cap=DELTA_MAX_SIGNATURES, sanitize_item=sanitize_block_signature)


def sanitize_op_list(value: object) -> list[DeltaOpDict] | None:
    """Validate an untrusted op list, enforcing the wire count cap."""
    return _sanitize_list(value, cap=DELTA_MAX_OPS, sanitize_item=sanitize_delta_op)


def parse_op_payload(value: object) -> list[DeltaOp] | None:
    """Validate an untrusted op list and build the executable :class:`DeltaOp` models.

    Combines :func:`sanitize_op_list` with model construction so both delta
    receivers — the client's download path (``hsync-client/delta_transfer.py``)
    and the master's delta-apply endpoint (``hsync-client/p2p_delta.py``) — decode
    the same wire shape the same way. A local re-implementation would drift
    silently, since a wrong field mapping only surfaces as a checksum mismatch
    after the rebuild.

    Bounds are still the caller's job (:func:`validate_op_bounds`): this function
    only enforces the wire shape and the count cap.

    Consumers: ``hsync-client`` (delta download and P2P delta apply).
    """
    clean = sanitize_op_list(value)
    if clean is None:
        return None
    return [
        DeltaOp(
            type=op["type"],
            offset=op["offset"],
            length=op["length"],
            data_offset=op["data_offset"],
        )
        for op in clean
    ]


def validate_op_bounds(
    ops: Sequence[DeltaOp],
    *,
    base_size: int,
    literal_size: int,
    new_size: int,
) -> str | None:
    """Validate op bounds and coverage against the real base/literal sizes.

    ``sanitize_delta_op`` only enforces the wire shape: an op may still point
    past the end of the base file, past the literal payload, or leave the
    reconstructed length different from the advertised ``new_size``. Both the
    server's delta-apply endpoint and the P2P master run this check before
    touching the filesystem, so the rejection reasons are one shared vocabulary
    (returned verbatim in the 422 detail).

    Returns ``None`` when every op is in bounds and the lengths add up, or one
    of ``copy_op_out_of_bounds`` / ``data_op_out_of_bounds`` /
    ``unknown_op_type`` / ``ops_coverage_mismatch``.
    """
    total = 0
    for op in ops:
        if op.type == OP_TYPE_COPY:
            if op.offset + op.length > base_size:
                return "copy_op_out_of_bounds"
        elif op.type == OP_TYPE_DATA:
            if op.data_offset + op.length > literal_size:
                return "data_op_out_of_bounds"
        else:
            return "unknown_op_type"
        total += op.length
    if total != new_size:
        return "ops_coverage_mismatch"
    return None


def delta_signatures_payload(
    *,
    block_size: int,
    file_size: int,
    sha256: str,
    signatures: Sequence[BlockSignature | BlockSignatureDict],
) -> DeltaSignaturesDict:
    """Build the base-file signature listing response body.

    Accepts both the model and its wire form because the server caches
    serialized signatures while the P2P master computes models; the envelope
    lives here so the REST and P2P responses stay byte-identical.

    Consumers: ``hsync-server`` (delta signatures GET), ``hsync-client``
    (``p2p_delta``), shared fixtures/tests.
    """
    return DeltaSignaturesDict(
        block_size=block_size,
        file_size=file_size,
        sha256=sha256,
        signatures=[
            dict(signature) if isinstance(signature, dict) else signature.to_dict()
            for signature in signatures
        ],
    )


def delta_download_payload(
    *,
    block_size: int,
    new_sha256: str,
    new_size: int,
    ops: Sequence[DeltaOp],
    data_url: str,
    data_size: int,
    compressed: bool,
) -> DeltaDownloadDict:
    """Build the download-delta response body (instructions + token URL).

    Consumers: ``hsync-server`` (delta signatures POST), ``hsync-client``
    (``p2p_delta``), shared fixtures/tests.
    """
    return DeltaDownloadDict(
        delta=True,
        block_size=block_size,
        new_sha256=new_sha256,
        instructions=DeltaDownloadInstructionsDict(
            new_size=new_size,
            ops=[op.to_dict() for op in ops],
        ),
        data_url=data_url,
        data_size=data_size,
        compressed=compressed,
    )
