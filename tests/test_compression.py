"""Tests for hsync_common.compression."""

import os
import tempfile

import pytest

from hsync_common.compression import (
    COMPRESSION_LEVEL,
    CONTENT_ENCODING_ZSTD,
    MIN_SIZE_FOR_COMPRESSION,
    PRECOMPRESSED_EXTENSIONS,
    compress_data,
    compress_file,
    decompress_data,
    should_compress,
)


class TestConstants:
    def test_compression_level_in_range(self):
        assert 1 <= COMPRESSION_LEVEL <= 22

    def test_content_encoding_value(self):
        assert CONTENT_ENCODING_ZSTD == "zstd"

    def test_min_size_positive(self):
        assert MIN_SIZE_FOR_COMPRESSION > 0

    def test_precompressed_extensions_is_frozenset(self):
        assert isinstance(PRECOMPRESSED_EXTENSIONS, frozenset)

    def test_precompressed_extensions_non_empty(self):
        assert len(PRECOMPRESSED_EXTENSIONS) > 0

    def test_common_image_extensions_in_precompressed(self):
        for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            assert ext in PRECOMPRESSED_EXTENSIONS, f"{ext} not in PRECOMPRESSED_EXTENSIONS"

    def test_common_archive_extensions_in_precompressed(self):
        for ext in (".zip", ".gz", ".7z", ".rar"):
            assert ext in PRECOMPRESSED_EXTENSIONS

    def test_common_video_extensions_in_precompressed(self):
        for ext in (".mp4", ".mkv", ".avi"):
            assert ext in PRECOMPRESSED_EXTENSIONS

    def test_text_extensions_not_in_precompressed(self):
        for ext in (".txt", ".py", ".json", ".csv", ".xml", ".log"):
            assert ext not in PRECOMPRESSED_EXTENSIONS

    def test_new_extensions_in_precompressed(self):
        """O1: newly added extensions must be present."""
        for ext in (".br", ".whl", ".snap", ".lz"):
            assert ext in PRECOMPRESSED_EXTENSIONS, f"{ext} not in PRECOMPRESSED_EXTENSIONS"

    def test_compound_extensions_not_in_set(self):
        """splitext() only returns the last extension, so compound strings like
        '.tar.gz' or '.tgz' would never match and must not appear in the set
        (they were dead code and have been removed)."""
        for dead_ext in (".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"):
            assert dead_ext not in PRECOMPRESSED_EXTENSIONS, (
                f"{dead_ext} is dead code — splitext() never returns it"
            )


class TestCompressDecompress:
    def test_roundtrip_small(self):
        data = b"Hello, HSYNC!"
        assert decompress_data(compress_data(data)) == data

    def test_roundtrip_empty(self):
        data = b""
        assert decompress_data(compress_data(data)) == data

    def test_roundtrip_large(self):
        data = b"X" * 100_000
        assert decompress_data(compress_data(data)) == data

    def test_compress_returns_bytes(self):
        assert isinstance(compress_data(b"test"), bytes)

    def test_decompress_returns_bytes(self):
        compressed = compress_data(b"test data")
        assert isinstance(decompress_data(compressed), bytes)

    def test_compressed_size_smaller_for_repetitive_data(self):
        data = b"ABCDEFGH" * 10_000
        assert len(compress_data(data)) < len(data)


class TestCompressFile:
    def test_compress_file_roundtrip(self, tmp_path):
        content = b"File content for testing compression"
        f = tmp_path / "test.txt"
        f.write_bytes(content)
        compressed = compress_file(str(f))
        assert decompress_data(compressed) == content

    def test_compress_file_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            compress_file("/nonexistent/path/file.txt")


class TestShouldCompress:
    def test_large_text_file_should_compress(self):
        assert should_compress("document.txt", MIN_SIZE_FOR_COMPRESSION + 1) is True

    def test_small_file_should_not_compress(self):
        assert should_compress("document.txt", MIN_SIZE_FOR_COMPRESSION - 1) is False

    def test_exactly_at_threshold_should_compress(self):
        # size < threshold → skip; size >= threshold → compress
        assert should_compress("document.txt", MIN_SIZE_FOR_COMPRESSION) is True

    def test_precompressed_extension_should_not_compress(self):
        for ext in (".jpg", ".zip", ".mp4", ".png"):
            assert should_compress(f"file{ext}", MIN_SIZE_FOR_COMPRESSION * 10) is False

    def test_uppercase_extension_not_compressed(self):
        assert should_compress("photo.JPG", MIN_SIZE_FOR_COMPRESSION * 10) is False

    def test_compressible_extension_above_threshold(self):
        assert should_compress("data.csv", MIN_SIZE_FOR_COMPRESSION + 1) is True

    def test_compressible_extension_below_threshold(self):
        assert should_compress("data.csv", 100) is False
