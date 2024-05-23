"""Tests for hsync_common.compression."""

import io

import pytest
import zstandard as zstd

from hsync_common.compression import (
    COMPRESSION_LEVEL,
    CONTENT_ENCODING_ZSTD,
    MIN_SIZE_FOR_COMPRESSION,
    MIN_SIZE_FOR_DOWNLOAD,
    MIN_SIZE_FOR_LAN,
    MIN_SIZE_FOR_UPLOAD,
    PRECOMPRESSED_EXTENSIONS,
    compress_data,
    compress_file,
    decompress_data,
    decompress_stream,
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


class TestDecompressMaxOutputSize:
    """Anti decompression-bomb cap for wire-supplied payloads."""

    def test_within_cap_roundtrips(self):
        data = b"A" * 50_000
        assert decompress_data(compress_data(data), max_output_size=60_000) == data

    def test_exact_cap_roundtrips(self):
        data = b"B" * 10_000
        assert decompress_data(compress_data(data), max_output_size=10_000) == data

    def test_over_cap_raises(self):
        data = b"C" * 100_000
        with pytest.raises(zstd.ZstdError):
            decompress_data(compress_data(data), max_output_size=1_000)

    def test_cap_on_frame_without_content_size(self):
        # Frames produced by a streaming compressor carry no embedded content
        # size: the capped streaming fallback must enforce the limit anyway.
        compressor = zstd.ZstdCompressor()
        buf = io.BytesIO()
        with compressor.stream_writer(buf, closefd=False) as writer:
            writer.write(b"D" * 50_000)
        frame = buf.getvalue()
        assert decompress_data(frame, max_output_size=60_000) == b"D" * 50_000
        with pytest.raises(zstd.ZstdError):
            decompress_data(frame, max_output_size=1_000)

    def test_malformed_input_raises(self):
        with pytest.raises(zstd.ZstdError):
            decompress_data(b"not a zstd frame", max_output_size=1_000)

    def test_no_cap_still_supported(self):
        data = b"legacy path"
        assert decompress_data(compress_data(data)) == data


class TestDecompressStream:
    def test_roundtrip_within_cap(self):
        data = b"E" * 100_000
        chunks = list(decompress_stream(io.BytesIO(compress_data(data)), 100_000))
        assert b"".join(chunks) == data

    def test_small_read_size(self):
        data = b"F" * 10_000
        chunks = list(decompress_stream(io.BytesIO(compress_data(data)), 10_000, read_size=512))
        assert b"".join(chunks) == data
        assert all(len(c) <= 512 for c in chunks)

    def test_over_cap_raises_mid_stream(self):
        data = b"G" * 100_000
        stream = decompress_stream(io.BytesIO(compress_data(data)), 1_000, read_size=256)
        with pytest.raises(zstd.ZstdError):
            b"".join(stream)

    def test_frame_without_content_size(self):
        compressor = zstd.ZstdCompressor()
        buf = io.BytesIO()
        with compressor.stream_writer(buf, closefd=False) as writer:
            writer.write(b"H" * 5_000)
        frame = buf.getvalue()
        assert b"".join(decompress_stream(io.BytesIO(frame), 5_000)) == b"H" * 5_000
        with pytest.raises(zstd.ZstdError):
            b"".join(decompress_stream(io.BytesIO(frame), 100))

    def test_empty_stream(self):
        assert list(decompress_stream(io.BytesIO(compress_data(b"")), 10)) == []

    def test_negative_cap_rejected(self):
        with pytest.raises(ValueError):
            list(decompress_stream(io.BytesIO(b""), -1))


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


class TestShouldCompressContextual:
    def test_download_alias_matches_base_threshold(self):
        assert MIN_SIZE_FOR_DOWNLOAD == MIN_SIZE_FOR_COMPRESSION

    def test_upload_threshold_greater_than_download(self):
        assert MIN_SIZE_FOR_UPLOAD > MIN_SIZE_FOR_DOWNLOAD

    def test_lan_threshold_greater_than_upload(self):
        assert MIN_SIZE_FOR_LAN > MIN_SIZE_FOR_UPLOAD

    def test_upload_below_threshold_skipped(self):
        assert should_compress("file.txt", MIN_SIZE_FOR_UPLOAD - 1, transfer_type="upload") is False

    def test_upload_above_threshold_compressed(self):
        assert should_compress("file.txt", MIN_SIZE_FOR_UPLOAD + 1, transfer_type="upload") is True

    def test_upload_at_threshold_compressed(self):
        assert should_compress("file.txt", MIN_SIZE_FOR_UPLOAD, transfer_type="upload") is True

    def test_lan_below_threshold_skipped(self):
        assert should_compress("file.txt", MIN_SIZE_FOR_LAN - 1, is_lan=True) is False

    def test_lan_above_threshold_compressed(self):
        assert should_compress("file.txt", MIN_SIZE_FOR_LAN + 1, is_lan=True) is True

    def test_lan_at_threshold_compressed(self):
        assert should_compress("file.txt", MIN_SIZE_FOR_LAN, is_lan=True) is True

    def test_lan_overrides_transfer_type(self):
        # File above upload threshold but below LAN threshold: LAN wins, skip.
        size = MIN_SIZE_FOR_UPLOAD + 1
        assert size < MIN_SIZE_FOR_LAN
        assert should_compress("file.txt", size, transfer_type="upload", is_lan=True) is False

    def test_precompressed_extension_skipped_in_upload(self):
        assert (
            should_compress("photo.jpg", MIN_SIZE_FOR_UPLOAD * 10, transfer_type="upload") is False
        )

    def test_precompressed_extension_skipped_in_lan(self):
        assert should_compress("photo.jpg", MIN_SIZE_FOR_LAN * 10, is_lan=True) is False
