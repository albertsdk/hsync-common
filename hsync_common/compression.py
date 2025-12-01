# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Core compression utilities for HSYNC.

This module provides shared file compression/decompression using Zstandard (zstd),
with intelligent decision-making on when compression is beneficial.

Both hsync-client and hsync-server import from this module for the base
compression functionality, and may extend it with project-specific logic.
"""

from collections.abc import Iterator
from io import BytesIO
from os.path import splitext
from typing import BinaryIO

import zstandard as zstd
from loguru import logger as log

# Compression level (1-22, default 3 is a good balance of speed/ratio)
COMPRESSION_LEVEL = 3

# Content-Encoding header value for zstd compression.
# Consumed by hsync-server (api/files/download.py) for the HTTP Content-Encoding
# response header when serving compressed file downloads.
CONTENT_ENCODING_ZSTD = "zstd"

# =============================================================================
# Compression Thresholds
# =============================================================================

# Base threshold: 10KB
# Below 10KB, compression overhead often exceeds transfer time savings.
# Above 10KB, compression benefits clearly outweigh overhead.
MIN_SIZE_FOR_COMPRESSION = 10 * 1024  # 10 KB

# Upload threshold: 32KB
# Client CPU is more precious than server CPU; only compress medium-large
# files where the benefit is clear.
MIN_SIZE_FOR_UPLOAD = 32 * 1024  # 32 KB

# LAN mode threshold: 100KB
# Local network is very fast (1Gbps+); below 100KB the compression time
# exceeds the transfer time saved.
MIN_SIZE_FOR_LAN = 100 * 1024  # 100 KB

# File extensions that are already compressed (compression won't help).
#
# NOTE: only the *last* extension is extracted by os.path.splitext, so compound
# suffixes like ".tar.gz" or ".tgz" must appear here as their final component
# (i.e. ".gz", ".bz2", ".xz" — which are already present).  Compound strings
# such as ".tar.gz" would never be matched and have been removed to avoid
# confusion.
PRECOMPRESSED_EXTENSIONS = frozenset(
    {
        # ── Archives / compressed streams ────────────────────────────────────
        ".zip",
        ".gz",
        ".gzip",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".zst",
        ".zstd",
        ".lz4",
        ".lzma",
        ".lz",  # lz = lzip
        ".br",  # Brotli
        ".cab",
        ".dmg",
        ".pkg",
        ".msi",
        ".deb",
        ".rpm",
        # ── Application packages (zip/apk/jar-based, already compressed) ─────
        ".apk",
        ".ipa",
        ".jar",
        ".war",
        ".ear",
        ".nupkg",
        ".whl",  # Python wheel (zip)
        ".snap",  # Linux Snap (squashfs)
        # ── Images ───────────────────────────────────────────────────────────
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".avif",
        ".heic",
        ".heif",
        ".jp2",
        ".j2k",
        ".jpf",
        ".jpm",
        ".jpx",
        ".tiff",
        ".tif",
        ".psd",
        ".ico",
        ".icns",
        ".raw",
        ".cr2",
        ".nef",
        ".arw",
        ".dng",
        ".orf",
        ".rw2",
        # ── Audio ────────────────────────────────────────────────────────────
        ".mp3",
        ".aac",
        ".ogg",
        ".opus",
        ".flac",
        ".m4a",
        ".wma",
        ".alac",
        # ── Video ────────────────────────────────────────────────────────────
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".m4v",
        ".mpeg",
        ".mpg",
        ".3gp",
        ".m2ts",
        ".mts",
        ".vob",
        ".ogv",
        # ── Documents (compressed internally by their container format) ───────
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".odt",
        ".ods",
        ".odp",
        ".epub",
        ".pages",
        ".numbers",
        ".keynote",
        ".xps",
        ".cbz",
        ".cbr",
        # ── Fonts ────────────────────────────────────────────────────────────
        ".woff",
        ".woff2",
        ".eot",
        ".ttc",
        # ── Other ────────────────────────────────────────────────────────────
        ".sqlite",
        ".db",
    }
)

# Create reusable compressor/decompressor for efficiency
_compressor = zstd.ZstdCompressor(level=COMPRESSION_LEVEL)
_decompressor = zstd.ZstdDecompressor()


def should_compress(
    filepath: str,
    size: int,
    transfer_type: str = "download",
    is_lan: bool = False,
) -> bool:
    """
    Determine if a file should be compressed before transfer.

    Uses different thresholds based on transfer direction and network type:
    - Download (server -> client): 10KB threshold
    - Upload (client -> server):   32KB threshold (client CPU is more precious)
    - LAN mode (P2P local):       100KB threshold (local network is very fast)

    Args:
        filepath: Path to the file.
        size: Size of the file in bytes.
        transfer_type: "download" or "upload" (default: "download").
        is_lan: True if operating in LAN P2P mode (default: False).

    Returns:
        True if file should be compressed, False otherwise.
    """
    if is_lan:
        threshold = MIN_SIZE_FOR_LAN
        context = "LAN"
    elif transfer_type == "upload":
        threshold = MIN_SIZE_FOR_UPLOAD
        context = "upload"
    else:
        threshold = MIN_SIZE_FOR_COMPRESSION
        context = "download"

    if size < threshold:
        log.debug(
            f"Skip compression ({context}): {filepath} below threshold ({size} < {threshold} bytes)"
        )
        return False

    ext = splitext(filepath)[1].lower()
    if ext in PRECOMPRESSED_EXTENSIONS:
        log.debug(f"Skip compression: {filepath} already compressed ({ext})")
        return False

    return True


def compress_data(data: bytes) -> bytes:
    """Compress data using Zstandard."""
    return _compressor.compress(data)


def decompress_data(data: bytes, max_output_size: int = 100 * 1024 * 1024) -> bytes:
    """Decompress Zstandard-compressed data.

    Args:
        data: Compressed bytes.
        max_output_size: Optional hard cap on the decompressed size in
            bytes. MUST be passed whenever *data* comes from a remote peer:
            without it a small crafted frame expands to an attacker-chosen
            size in memory (decompression bomb). Enforced via a capped
            streaming read (works for frames with or without an embedded
            content size) so memory stays bounded by the cap.

    Returns:
        The decompressed bytes.

    Raises:
        zstd.ZstdError: On malformed input or when the decompressed size
            exceeds *max_output_size*.
    """
    if max_output_size < 0:
        raise ValueError("max_output_size must be >= 0")

    with _decompressor.stream_reader(BytesIO(data)) as reader:
        out = reader.read(max_output_size + 1)
    if len(out) > max_output_size:
        raise zstd.ZstdError(f"Decompressed data exceeds max_output_size ({max_output_size} bytes)")
    return out


def decompress_stream(
    stream: BinaryIO,
    max_output_size: int,
    read_size: int = 1024 * 1024,
) -> Iterator[bytes]:
    """Yield decompressed chunks from a compressed byte stream, with a hard cap.

    Streams decompression so neither the compressed input nor the
    decompressed output is ever fully buffered in memory. MUST be used
    (with a meaningful *max_output_size*) whenever *stream* carries data
    from a remote peer (anti decompression-bomb).

    Args:
        stream: A readable binary stream of zstd-compressed data (e.g.
            ``response.raw`` of a streamed HTTP download).
        max_output_size: Hard cap on the total decompressed bytes.
        read_size: Maximum chunk size yielded at a time.

    Yields:
        Decompressed byte chunks, at most *read_size* each and at most
        *max_output_size* in total.

    Raises:
        zstd.ZstdError: On malformed input or when the decompressed size
            exceeds *max_output_size*.
        ValueError: If *max_output_size* is negative.
    """
    if max_output_size < 0:
        raise ValueError("max_output_size must be >= 0")

    produced = 0
    with _decompressor.stream_reader(stream) as reader:
        while True:
            chunk = reader.read(read_size)
            if not chunk:
                return
            produced += len(chunk)
            if produced > max_output_size:
                raise zstd.ZstdError(
                    f"Decompressed data exceeds max_output_size ({max_output_size} bytes)"
                )
            yield chunk


def compress_file(filepath: str) -> bytes:
    """Read and compress a file.

    Test-only parity oracle: this one-shot, whole-file compressor has no
    production caller. It is retained as the synchronous reference against which
    ``hsync_server.compression.async_compress_stream`` (the real streaming,
    memory-bounded implementation) is validated — see
    ``hsync-server/tests/test_compression.py``. Production code must use
    ``compress_data`` or the server's ``async_compress_stream`` instead.
    """
    with open(filepath, "rb") as f:
        return compress_data(f.read())
