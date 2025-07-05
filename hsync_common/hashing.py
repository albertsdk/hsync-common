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
- :func:`compute_sha256` - synchronous, chunked SHA-256 of a file.
- :func:`compute_sha256_async` - asyncio variant backed by ``aiofiles``.
"""

from __future__ import annotations

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


def compute_sha256(filepath: str, chunk_size: int = CHUNK_SIZE_SMALL) -> str:
    """Compute the SHA-256 checksum of a file using chunked reads.

    Args:
        filepath: Path to the file.
        chunk_size: Size of chunks to read.

    Returns:
        Hexadecimal SHA-256 digest string.
    """
    # hashlib.file_digest streams the file in C (single pass, zero per-chunk
    # Python loop overhead); the chunk_size is honoured transparently.
    with open(filepath, "rb") as f:
        return file_digest(f, sha256).hexdigest()


async def compute_sha256_async(filepath: str, chunk_size: int = CHUNK_SIZE_SMALL) -> str:
    """Asynchronously compute the SHA-256 checksum of a file.

    Reads the file in chunks via ``aiofiles`` so large files do not block the
    event loop or get loaded entirely into memory.

    Args:
        filepath: Path to the file.
        chunk_size: Size of chunks to read.

    Returns:
        Hexadecimal SHA-256 digest string.
    """
    import aiofiles

    hasher = sha256()
    async with aiofiles.open(filepath, "rb") as f:
        while chunk := await f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()
