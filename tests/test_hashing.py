# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for hsync_common.hashing."""

import asyncio
from hashlib import sha256

from hsync_common.constants import (
    CHUNK_SIZE_LARGE,
    CHUNK_SIZE_MEDIUM,
    CHUNK_SIZE_SMALL,
    FILE_SIZE_MEDIUM,
    FILE_SIZE_SMALL,
)
from hsync_common.hashing import (
    adaptive_chunk_size,
    compute_sha256,
    compute_sha256_async,
    is_sha256_hex,
)


class TestIsSha256Hex:
    def test_valid(self):
        assert is_sha256_hex("a" * 64) is True
        assert is_sha256_hex("0123456789abcdef" * 4) is True
        assert is_sha256_hex("A" * 64) is True

    def test_invalid(self):
        assert is_sha256_hex("") is False
        assert is_sha256_hex("a" * 63) is False
        assert is_sha256_hex("a" * 65) is False
        assert is_sha256_hex("g" * 64) is False
        # Non-ASCII would crash hmac.compare_digest: must be rejected up-front.
        assert is_sha256_hex("é" * 64) is False
        assert is_sha256_hex(None) is False
        assert is_sha256_hex(123) is False


class TestAdaptiveChunkSize:
    def test_none(self):
        assert adaptive_chunk_size(None) == CHUNK_SIZE_MEDIUM

    def test_small(self):
        assert adaptive_chunk_size(FILE_SIZE_SMALL - 1) == CHUNK_SIZE_SMALL

    def test_medium(self):
        assert adaptive_chunk_size(FILE_SIZE_SMALL) == CHUNK_SIZE_MEDIUM
        assert adaptive_chunk_size(FILE_SIZE_MEDIUM - 1) == CHUNK_SIZE_MEDIUM

    def test_large(self):
        assert adaptive_chunk_size(FILE_SIZE_MEDIUM) == CHUNK_SIZE_LARGE

    def test_sub_megabyte_files_avoid_many_python_iterations(self):
        """The sub-1MB tier must amortise the per-iteration Python overhead.

        Each download iteration pays a frame read, the throttle wrapper, one
        ``hash.update`` call and a write. Measured on the HTTPS apply path with
        an incompressible 200 KiB payload, an 8 KiB chunk made the file pay 26
        iterations and 5.5 ms CPU/file, while a 256 KiB chunk needs one
        iteration and 4.3 ms/file. Guard the intent so a future "tidy" shrink of
        the tier fails loudly here instead of silently regressing the read loop.
        """
        chunk = adaptive_chunk_size(FILE_SIZE_SMALL - 1)
        assert chunk >= 256 * 1024
        assert (FILE_SIZE_SMALL - 1) // chunk <= 4


class TestComputeSha256:
    def test_matches_hashlib(self, tmp_path):
        data = b"hello hsync" * 5000
        f = tmp_path / "blob.bin"
        f.write_bytes(data)
        assert compute_sha256(str(f)) == sha256(data).hexdigest()

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        assert compute_sha256(str(f)) == sha256(b"").hexdigest()

    def test_async_matches_sync(self, tmp_path):
        data = b"async hsync payload" * 1234
        f = tmp_path / "blob.bin"
        f.write_bytes(data)
        result = asyncio.run(compute_sha256_async(str(f)))
        assert result == sha256(data).hexdigest()
