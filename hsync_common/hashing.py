# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Shared SHA-256 hashing helpers for HSYNC projects.

Provides the canonical chunked checksum routines used by the client, the
server, and the shared :class:`hsync_common.models.file.File` model:

- :func:`adaptive_chunk_size` - pick a read chunk size from a file size.
- :func:`compute_sha256` - synchronous SHA-256 of a file (C-level streaming).
- :func:`compute_sha256_async` - asyncio variant (one executor hop).
"""

from __future__ import annotations

import asyncio
import re
from hashlib import file_digest, sha256
from typing import TypeGuard

from hsync_common.constants import (
    CHUNK_SIZE_LARGE,
    CHUNK_SIZE_MEDIUM,
    CHUNK_SIZE_SMALL,
    FILE_SIZE_MEDIUM,
    FILE_SIZE_SMALL,
)

# Precompiled hex-digest shape gate: a single C-level regex pass is far cheaper
# than a pure-Python ``all()`` generator over up to 64 characters.
_SHA256_HEX_RE = re.compile(r"[0-9a-fA-F]{64}\Z")


def is_sha256_hex(value: object) -> TypeGuard[str]:
    """Return True when *value* has the shape of a SHA-256 hex digest.

    Wire-supplied checksums must pass this before being compared with
    :func:`hmac.compare_digest`, which raises ``TypeError`` on non-ASCII
    strings — an unvalidated peer-supplied checksum would otherwise turn a
    routine integrity mismatch into an unhandled 500.
    """
    return isinstance(value, str) and bool(_SHA256_HEX_RE.fullmatch(value))


def adaptive_chunk_size(file_size: int | None) -> int:
    """Pick an optimal read chunk size based on file size.

    Uses larger chunks for bigger files to improve throughput while keeping
    memory usage bounded.

    Args:
        file_size: Size of the file in bytes, or ``None`` if unknown.

    Returns:
        Chunk size in bytes (8KB to 256KB).
    """
    if file_size is None:
        return CHUNK_SIZE_MEDIUM
    if file_size >= FILE_SIZE_MEDIUM:
        return CHUNK_SIZE_LARGE
    if file_size >= FILE_SIZE_SMALL:
        return CHUNK_SIZE_MEDIUM
    return CHUNK_SIZE_SMALL


def compute_sha256(filepath: str) -> str:
    """Compute the SHA-256 checksum of a file.

    Uses :func:`hashlib.file_digest`, which streams the file in C (single
    pass, zero per-chunk Python loop overhead), so memory stays bounded for
    large files.

    Args:
        filepath: Path to the file.

    Returns:
        Hexadecimal SHA-256 digest string.
    """
    with open(filepath, "rb") as f:
        return file_digest(f, sha256).hexdigest()


async def compute_sha256_async(filepath: str) -> str:
    """Asynchronously compute the SHA-256 checksum of a file.

    The digest is the sync :func:`compute_sha256` (C-level
    :func:`hashlib.file_digest`: single pass, memory bounded by the reader
    buffer) dispatched with a single ``asyncio.to_thread`` hop, so large files
    never block the event loop.

    Replaces the previous ``aiofiles`` implementation, which read the file in
    ``CHUNK_SIZE_SMALL`` (8 KB) chunks and paid one executor round-trip per
    chunk: ~81 ms for a 16 MB file against ~11 ms here (7.2x, measured by the
    L1 hashing benchmark), with the same bounded-memory profile.

    Args:
        filepath: Path to the file.

    Returns:
        Hexadecimal SHA-256 digest string.
    """
    return await asyncio.to_thread(compute_sha256, filepath)
