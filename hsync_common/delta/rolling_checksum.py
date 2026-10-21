# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
rsync-style rolling-checksum engine (weak Adler32 + strong SHA-256).

The sender scans the *new* file with a sliding window of ``block_size`` bytes:
the weak Adler32 checksum is updated in O(1) per 1-byte shift and only selects
candidate base blocks; the strong SHA-256 of the window confirms the match and
filters Adler32 collisions. Consecutive unmatched bytes are coalesced into a
single ``data`` op so the op list stays compact.

Rolling formula (initialized from :func:`zlib.adler32`): with ``a``/``b`` the
Adler32 halves of the current window, sliding out ``x_out`` and in ``x_in``
gives ``a' = a - x_out + x_in`` and ``b' = b - n*x_out + a' - 1`` (all mod
65521). The ``-1`` term is required because ``zlib.adler32`` seeds ``a`` at 1;
dropping it would drift from :func:`zlib.adler32` on every step (covered by
the parity tests against fresh ``zlib.adler32`` windows).

Memory profile: :func:`find_matches_file` mmaps the new file instead of
loading it, so peak memory stays bounded regardless of file size (the OS
pages the mapping). :func:`find_matches` accumulates the literal payload in
RAM (capped by the caller via ``DELTA_MAX_LITERAL_SIZE``);
:func:`find_matches_to_sink` / :func:`find_matches_file_to_sink` stream the
literal bytes to a seekable binary sink (e.g. a temp file) instead, so the
sender's peak stays O(block_size) plus the op list.

The partial tail signature (last base block shorter than ``block_size``) is
computed by :func:`compute_signatures` for completeness but is *never matched*
by the sliding window (the window is always exactly ``block_size`` wide), so
the corresponding bytes in the new file are emitted as literal data — the same
behaviour as rsync.
"""

from __future__ import annotations

import mmap
import os
import zlib
from hashlib import sha256
from typing import BinaryIO

from hsync_common.exceptions import HSyncError
from hsync_common.models.delta import OP_TYPE_COPY, BlockSignature, DeltaOp

__all__ = [
    "ADLER32_MOD",
    "APPLY_BUFFER_SIZE",
    "DeltaError",
    "adler32_roll",
    "apply_delta",
    "build_signature_index",
    "compute_signatures",
    "find_matches",
    "find_matches_file",
    "find_matches_file_to_sink",
    "find_matches_to_sink",
    "signatures_for_data",
]

# Adler32 modulus: largest prime < 2**16.
ADLER32_MOD = 65521

# Read/write buffer used by apply_delta when streaming copy ops.
APPLY_BUFFER_SIZE = 64 * 1024


def _block_byte_penalty(block_size: int) -> list[int]:
    """Precompute ``(block_size * byte) % ADLER32_MOD`` for every byte value.

    The rolling update needs ``(n * byte_out) % MOD`` per missed byte. Computing
    ``(block_size * byte_out) % MOD`` inline pays one big-int modulo per byte
    (``block_size * byte_out`` reaches ~66M for the 256KB tier). A 256-entry
    table turns it into a list lookup with zero divisions in the hot loop.
    """
    mod = ADLER32_MOD
    n_mod = block_size % mod
    return [(n_mod * value) % mod for value in range(256)]


class DeltaError(HSyncError):
    """Raised when a delta computation or reconstruction cannot proceed."""

    error_code = "HSYNC-DELTA-0001"
    default_message = "Delta transfer operation failed"


def _require_positive_block_size(block_size: int) -> None:
    """Raise :class:`DeltaError` when *block_size* is not strictly positive."""
    if block_size <= 0:
        raise DeltaError(
            "block_size must be positive",
            details={"block_size": block_size},
        )


def adler32_roll(
    prev_a: int,
    prev_b: int,
    window_size: int,
    byte_out: int,
    byte_in: int,
) -> tuple[int, int, int]:
    """Roll an Adler32 window forward by one byte in O(1).

    Args:
        prev_a: ``a`` half (low 16 bits) of the previous window's Adler32.
        prev_b: ``b`` half (high 16 bits) of the previous window's Adler32.
        window_size: Window width in bytes (n).
        byte_out: Byte leaving the window.
        byte_in: Byte entering the window.

    Returns:
        ``(adler32, new_a, new_b)`` for the shifted window; the combined value
        equals ``zlib.adler32`` of the new window.
    """
    new_a = (prev_a - byte_out + byte_in) % ADLER32_MOD
    new_b = (prev_b - window_size * byte_out + new_a - 1) % ADLER32_MOD
    return ((new_b << 16) | new_a), new_a, new_b


def _signature_for_chunk(chunk: bytes | memoryview, index: int, offset: int) -> BlockSignature:
    """Build the weak+strong signature of one base-file chunk.

    *chunk* accepts any bytes-like object: :func:`signatures_for_data` passes a
    zero-copy :class:`memoryview` slice, so both digest computations run
    directly on the source buffer without materialising an intermediate copy.
    """
    return BlockSignature(
        index=index,
        offset=offset,
        length=len(chunk),
        weak=zlib.adler32(chunk),
        strong=sha256(chunk).hexdigest(),
    )


def compute_signatures(filepath: str, block_size: int) -> list[BlockSignature]:
    """Compute per-block signatures of the base file.

    Every block gets a weak Adler32 and a strong SHA-256; the final partial
    block (``length < block_size``) is included with its real length. The file
    is streamed chunk-by-chunk so memory stays bounded for large bases.
    """
    _require_positive_block_size(block_size)
    signatures: list[BlockSignature] = []
    sig_for_chunk = _signature_for_chunk  # bind locally: hot loop, one lookup saved per block
    with open(filepath, "rb") as f:
        read = f.read
        index = 0
        offset = 0
        while chunk := read(block_size):
            signatures.append(sig_for_chunk(chunk, index, offset))
            index += 1
            offset += len(chunk)
    return signatures


def signatures_for_data(data: bytes, block_size: int) -> list[BlockSignature]:
    """Compute per-block signatures of an in-memory *data* buffer.

    Twin of :func:`compute_signatures` for callers that already hold the base
    bytes (fixture builders, tests). Both delegate the per-chunk weak+strong
    computation to the same helper, so the two paths cannot drift.

    Args:
        data: The base payload to signature.
        block_size: Block width in bytes (must be positive).

    Returns:
        One :class:`BlockSignature` per block; the final partial block
        (``length < block_size``) is included with its real length.

    Raises:
        DeltaError: When ``block_size`` is not positive.

    Consumers: ``hsync-common`` (``protocol.fixtures`` delta fixtures) and
    the shared delta test suite.
    """
    _require_positive_block_size(block_size)
    signatures: list[BlockSignature] = []
    sig_for_chunk = _signature_for_chunk  # hot loop: avoid a global lookup per block
    view = memoryview(data)  # zero-copy: slice views are hashed without copying bytes
    index = 0
    offset = 0
    n = len(data)
    while offset < n:
        chunk = view[offset : offset + block_size]
        signatures.append(sig_for_chunk(chunk, index, offset))
        index += 1
        offset += len(chunk)
    return signatures


def build_signature_index(
    signatures: list[BlockSignature] | tuple[BlockSignature, ...],
    block_size: int,
) -> dict[int, list[tuple[int, str]]]:
    """Index full-size signatures by weak checksum for O(1) candidate lookup.

    The partial tail signature is excluded: the sliding window is always
    ``block_size`` wide and can never match it (rsync semantics).
    """
    table: dict[int, list[tuple[int, str]]] = {}
    for sig in signatures:
        if sig.length < block_size:
            continue
        key = sig.weak
        lst = table.get(key)
        if lst is None:
            table[key] = [(sig.offset, sig.strong)]
        else:
            lst.append((sig.offset, sig.strong))
    return table


def _find_matches(
    new_data: bytes | bytearray | memoryview | mmap.mmap,
    signatures: list[BlockSignature] | tuple[BlockSignature, ...],
    block_size: int,
    literal_sink: BinaryIO | None,
) -> tuple[list[DeltaOp], bytes]:
    """Core matcher; buffer the literals (sink None) or stream them to a sink."""
    _require_positive_block_size(block_size)
    table = build_signature_index(signatures, block_size)
    table_get = table.get  # bind locally: O(1) lookup, one attribute resolution saved per window
    strong_hash = sha256  # bind locally: called once per candidate window (hot loop)
    # Per-byte penalty table: (block_size * byte_out) % MOD without a division
    # in the hot loop (the product reaches ~66M on the 256KB tier).
    byte_penalty = _block_byte_penalty(block_size)
    mod = ADLER32_MOD

    ops: list[DeltaOp] = []
    literal_data = bytearray()
    # Offsets are absolute in the literal source: the sink's start position
    # (0 for a fresh temp file) or the buffer length. The sink path never
    # materialises the payload in a Python bytes/bytearray.
    literal_len = literal_sink.tell() if literal_sink is not None else 0
    # Start of the open literal run *in the new file*. The run is materialised
    # in one slice copy when it ends (a match or EOF) instead of appending one
    # byte at a time (bytearray.append(int) is ~25-30 ns/byte): on the
    # changed-block scenarios that is a consistent ~8% (1 MB @50% changed:
    # 142.5 ms -> 130.5 ms), and it scales with the literal payload.
    literal_src_start: int | None = None
    view = memoryview(new_data)  # zero-copy: window slices are hashed without copying bytes
    n = len(view)
    pos = 0
    roll_a: int | None = None
    roll_b: int | None = None

    while pos + block_size <= n:
        if roll_a is None or roll_b is None:
            weak = zlib.adler32(view[pos : pos + block_size])
            roll_a = weak & 0xFFFF
            roll_b = (weak >> 16) & 0xFFFF
        else:
            # adler32_roll inlined: a Python call per unmatched byte is ~25% of
            # this loop (measured 156 ns vs 119 ns per roll). Keep in sync with
            # adler32_roll (reference implementation, parity-tested in
            # tests/test_delta.py against fresh zlib.adler32 windows; any drift
            # here breaks the committed delta fixtures and apply tests).
            # No % here: new_a stays in [-255, 2*MOD) so one conditional
            # add/sub suffices, and the (n * byte_out) % MOD term comes from
            # the precomputed table (one list lookup instead of a division).
            byte_out = view[pos - 1]
            new_a = roll_a - byte_out + view[pos + block_size - 1]
            if new_a < 0:
                new_a += mod
            elif new_a >= mod:
                new_a -= mod
            roll_a = new_a
            # b_tmp in [-MOD, 2*MOD): one conditional correction, no division.
            b_tmp = roll_b - byte_penalty[byte_out] + new_a - 1
            if b_tmp < 0:
                b_tmp += mod
            elif b_tmp >= mod:
                b_tmp -= mod
            roll_b = b_tmp
            weak = (roll_b << 16) | roll_a

        matched = False
        candidates = table_get(weak)
        if candidates:
            strong = strong_hash(view[pos : pos + block_size]).hexdigest()
            for base_offset, expected_strong in candidates:
                if strong == expected_strong:
                    if literal_src_start is not None:
                        # The data offset is the literal length *before* the
                        # append: ops and the literal source stay in sync.
                        run = view[literal_src_start:pos]
                        data_offset = literal_len
                        if literal_sink is None:
                            literal_data += run
                        else:
                            literal_sink.write(run)
                        literal_len += len(run)
                        ops.append(DeltaOp.data(data_offset, pos - literal_src_start))
                        literal_src_start = None
                    ops.append(DeltaOp.copy(base_offset, block_size))
                    pos += block_size
                    roll_a = roll_b = None  # force a fresh window after a jump
                    matched = True
                    break

        if not matched:
            if literal_src_start is None:
                literal_src_start = pos
            pos += 1

    # Remaining tail bytes (pos + block_size > n) can never match a window: they
    # extend the open run (or open one) and are coalesced in a single slice.
    if literal_src_start is None and pos < n:
        literal_src_start = pos
    if literal_src_start is not None:
        run = view[literal_src_start:n]
        data_offset = literal_len
        if literal_sink is None:
            literal_data += run
        else:
            literal_sink.write(run)
        literal_len += len(run)
        ops.append(DeltaOp.data(data_offset, n - literal_src_start))

    if literal_sink is not None:
        return ops, b""
    return ops, bytes(literal_data)


def find_matches(
    new_data: bytes | bytearray | memoryview | mmap.mmap,
    signatures: list[BlockSignature] | tuple[BlockSignature, ...],
    block_size: int,
) -> tuple[list[DeltaOp], bytes]:
    """Match *new_data* against the base signatures; return (ops, literals).

    Consecutive unmatched bytes are coalesced into one ``data`` op referencing
    the shared literal buffer via ``data_offset``. The partial tail signature
    is ignored (see module docstring).
    """
    return _find_matches(new_data, signatures, block_size, None)


def find_matches_to_sink(
    new_data: bytes | bytearray | memoryview | mmap.mmap,
    signatures: list[BlockSignature] | tuple[BlockSignature, ...],
    block_size: int,
    literal_sink: BinaryIO,
) -> list[DeltaOp]:
    """Like :func:`find_matches`, but stream the literals to *literal_sink*.

    ``literal_sink`` must be a seekable binary stream positioned where the
    literal payload starts (normally a fresh temp file at offset 0). The
    returned data ops keep referencing ``literal_sink`` offsets, so the caller
    can hand that file to ``apply_delta`` without a Python bytes copy.
    """
    ops, _ = _find_matches(new_data, signatures, block_size, literal_sink)
    return ops


def find_matches_file(
    new_path: str,
    signatures: list[BlockSignature] | tuple[BlockSignature, ...],
    block_size: int,
) -> tuple[list[DeltaOp], bytes]:
    """mmap-backed :func:`find_matches` for large new files (bounded RAM)."""
    size = os.path.getsize(new_path)
    if size == 0:
        return [], b""
    with open(new_path, "rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            return _find_matches(mm, signatures, block_size, None)


def find_matches_file_to_sink(
    new_path: str,
    signatures: list[BlockSignature] | tuple[BlockSignature, ...],
    block_size: int,
    literal_sink: BinaryIO,
) -> list[DeltaOp]:
    """mmap-backed :func:`find_matches_to_sink` for large new files."""
    size = os.path.getsize(new_path)
    if size == 0:
        return []
    with open(new_path, "rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            ops, _ = _find_matches(mm, signatures, block_size, literal_sink)
            return ops


def _read_literal(
    literal_data: bytes | bytearray | memoryview | BinaryIO, offset: int, length: int
) -> bytes:
    """Read *length* literal bytes at *offset* from a buffer or a binary stream."""
    if isinstance(literal_data, bytes | bytearray | memoryview):
        return bytes(literal_data[offset : offset + length])
    literal_data.seek(offset)
    return literal_data.read(length)


def apply_delta(
    base_path: str,
    ops: list[DeltaOp] | tuple[DeltaOp, ...],
    literal_data: bytes | bytearray | memoryview | BinaryIO,
    output_path: str,
) -> int:
    """Rebuild the new file from base copy ops + literal data ops.

    Copy ops are streamed through a bounded buffer; ``literal_data`` may be an
    in-memory buffer or a seekable binary stream (e.g. a temp file) so large
    payloads never need to be resident in RAM. Returns the number of bytes
    written; the caller verifies the whole-file SHA-256 afterwards.
    """
    if os.path.realpath(base_path) == os.path.realpath(output_path):
        raise DeltaError(
            "Base file and output path must be different — same path would "
            "truncate the base before it can be read",
            details={"base_path": base_path, "output_path": output_path},
        )
    written = 0
    with open(base_path, "rb") as base_file, open(output_path, "wb") as out_file:
        for op in ops:
            if op.type == OP_TYPE_COPY:
                base_file.seek(op.offset)
                remaining = op.length
                while remaining > 0:
                    chunk = base_file.read(min(APPLY_BUFFER_SIZE, remaining))
                    if not chunk:
                        raise DeltaError(
                            "Base file ended before copy op was satisfied",
                            details={"offset": op.offset, "length": op.length},
                        )
                    out_file.write(chunk)
                    written += len(chunk)
                    remaining -= len(chunk)
            else:
                data = _read_literal(literal_data, op.data_offset, op.length)
                if len(data) != op.length:
                    raise DeltaError(
                        "Literal payload ended before data op was satisfied",
                        details={"data_offset": op.data_offset, "length": op.length},
                    )
                out_file.write(data)
                written += len(data)
    return written
