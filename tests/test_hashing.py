# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

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
)


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
