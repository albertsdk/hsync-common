"""Tests for hsync_common.compression."""

import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import zstandard as zstd

from hsync_common.compression import (
    COMPRESSION_LEVEL,
    COMPRESSION_LEVEL_FAST,
    MIN_SIZE_FOR_COMPRESSION,
    MIN_SIZE_FOR_P2P,
    MIN_SIZE_FOR_UPLOAD,
    PRECOMPRESSED_EXTENSIONS,
    compress_data,
    compress_file,
    compress_file_to_file,
    compression_level,
    decompress_data,
    decompress_stream,
    should_compress,
)


class TestConstants:
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
        """Newly added extensions must be present."""
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
    def test_upload_threshold_greater_than_base(self):
        assert MIN_SIZE_FOR_UPLOAD > MIN_SIZE_FOR_COMPRESSION

    def test_p2p_threshold_greater_than_upload(self):
        assert MIN_SIZE_FOR_P2P > MIN_SIZE_FOR_UPLOAD

    def test_upload_below_threshold_skipped(self):
        assert should_compress("file.txt", MIN_SIZE_FOR_UPLOAD - 1, transfer_type="upload") is False

    def test_upload_above_threshold_compressed(self):
        assert should_compress("file.txt", MIN_SIZE_FOR_UPLOAD + 1, transfer_type="upload") is True

    def test_upload_at_threshold_compressed(self):
        assert should_compress("file.txt", MIN_SIZE_FOR_UPLOAD, transfer_type="upload") is True

    def test_p2p_below_threshold_skipped(self):
        assert should_compress("file.txt", MIN_SIZE_FOR_P2P - 1, is_p2p=True) is False

    def test_p2p_above_threshold_compressed(self):
        assert should_compress("file.txt", MIN_SIZE_FOR_P2P + 1, is_p2p=True) is True

    def test_p2p_at_threshold_compressed(self):
        assert should_compress("file.txt", MIN_SIZE_FOR_P2P, is_p2p=True) is True

    def test_p2p_overrides_transfer_type(self):
        # File above upload threshold but below LAN threshold: LAN wins, skip.
        size = MIN_SIZE_FOR_UPLOAD + 1
        assert size < MIN_SIZE_FOR_P2P
        assert should_compress("file.txt", size, transfer_type="upload", is_p2p=True) is False

    def test_precompressed_extension_skipped_in_upload(self):
        assert (
            should_compress("photo.jpg", MIN_SIZE_FOR_UPLOAD * 10, transfer_type="upload") is False
        )

    def test_precompressed_extension_skipped_in_p2p(self):
        assert should_compress("photo.jpg", MIN_SIZE_FOR_P2P * 10, is_p2p=True) is False


class TestCompressionLevel:
    def test_download_uses_default_level(self):
        assert compression_level() == COMPRESSION_LEVEL
        assert compression_level("download") == COMPRESSION_LEVEL

    def test_upload_uses_fast_level(self):
        assert compression_level("upload") == COMPRESSION_LEVEL_FAST

    def test_p2p_uses_fast_level(self):
        assert compression_level(is_p2p=True) == COMPRESSION_LEVEL_FAST

    def test_p2p_overrides_transfer_type(self):
        # Same precedence as should_compress: LAN wins over transfer_type.
        assert compression_level("download", is_p2p=True) == COMPRESSION_LEVEL_FAST

    def test_constants_relationship(self):
        assert COMPRESSION_LEVEL == 3
        assert COMPRESSION_LEVEL_FAST == 1
        assert COMPRESSION_LEVEL_FAST < COMPRESSION_LEVEL

    def test_compress_data_honours_level(self):
        """Both levels produce intact frames; the keyword is not ignored."""
        data = bytes(range(256)) * 40
        fast = compress_data(data, level=COMPRESSION_LEVEL_FAST)
        default = compress_data(data, level=COMPRESSION_LEVEL)
        assert decompress_data(fast) == data
        assert decompress_data(default) == data
        # The no-keyword call must stay pinned to the download-side SSOT level.
        assert compress_data(data) == default

    def test_compress_file_to_file_honours_level(self, tmp_path):
        """The streaming compressor accepts the direction-aware level too."""
        src = tmp_path / "data.bin"
        original = bytes(range(256)) * 40
        src.write_bytes(original)
        dst_fast = tmp_path / "out-fast.zst"
        dst_default = tmp_path / "out-default.zst"

        compress_file_to_file(str(src), str(dst_fast), level=COMPRESSION_LEVEL_FAST)
        compress_file_to_file(str(src), str(dst_default), level=COMPRESSION_LEVEL)

        assert decompress_data(dst_fast.read_bytes()) == original
        assert decompress_data(dst_default.read_bytes()) == original


class TestCompressFileToFile:
    """Tests for the streaming file compressor (upload path)."""

    def test_roundtrip(self, tmp_path):
        """The compressed output decompresses to the exact source content."""
        src = tmp_path / "data.bin"
        original = b"hello hsync " * 100_000
        src.write_bytes(original)
        dst = tmp_path / "data.bin.zst"

        size = compress_file_to_file(str(src), str(dst))

        assert size == dst.stat().st_size
        assert decompress_data(dst.read_bytes()) == original

    def test_output_smaller_than_input_for_compressible_content(self, tmp_path):
        src = tmp_path / "data.txt"
        src.write_bytes(b"a" * 1_000_000)
        dst = tmp_path / "data.txt.zst"

        size = compress_file_to_file(str(src), str(dst))

        assert 0 < size < src.stat().st_size

    def test_overwrites_existing_output(self, tmp_path):
        src = tmp_path / "data.bin"
        original = b"new content " * 50_000
        src.write_bytes(original)
        dst = tmp_path / "out.zst"
        dst.write_bytes(b"stale previous frame content" * 1000)

        compress_file_to_file(str(src), str(dst))

        assert decompress_data(dst.read_bytes()) == original

    def test_empty_source_produces_valid_empty_frame(self, tmp_path):
        src = tmp_path / "empty.bin"
        src.write_bytes(b"")
        dst = tmp_path / "empty.zst"

        size = compress_file_to_file(str(src), str(dst))

        assert size > 0  # a valid zstd frame still carries framing bytes
        assert decompress_data(dst.read_bytes()) == b""

    def test_read_size_does_not_change_output_content(self, tmp_path):
        """Any read chunk size yields a frame decompressing to the source."""
        src = tmp_path / "data.bin"
        original = b"chunked read " * 20_000
        src.write_bytes(original)

        out_a = tmp_path / "a.zst"
        out_b = tmp_path / "b.zst"
        compress_file_to_file(str(src), str(out_a), read_size=64 * 1024)
        compress_file_to_file(str(src), str(out_b), read_size=1024 * 1024)

        assert decompress_data(out_a.read_bytes()) == original
        assert decompress_data(out_b.read_bytes()) == original


class TestThreadSafety:
    """Concurrent use must be byte-exact and must never crash the process.

    Regression for the 6000-file LAN stress failure: a single shared
    ``ZstdCompressor``/``ZstdDecompressor`` used concurrently from multiple
    threads corrupted decompressed streams ("Unknown frame descriptor",
    "Data corrupted") and could segfault the whole process — one-shot
    ``compress()`` included. ``hsync_common.compression`` now keeps
    per-thread instances; these tests pin that contract.
    """

    THREADS = 8
    ITERS = 30
    PAYLOAD_SIZE = 512 * 1024

    @staticmethod
    def _payload(tag: int) -> bytes:
        # Semi-compressible content, unique per payload so a mixed-up or
        # partially-consumed frame cannot pass by accident.
        return bytes([tag]) * 1024 + os.urandom(TestThreadSafety.PAYLOAD_SIZE - 1024) + bytes([tag])

    def _run_concurrently(self, fn) -> list[object]:
        """Run *fn(worker_index, iteration_index)* on all threads, synchronized.

        A barrier maximizes the overlap window between threads; exceptions
        are captured (never raised inside the workers) so a *clean* failure
        is reported instead of relying on a crash to fail the test.
        """
        barrier = threading.Barrier(self.THREADS)
        problems: list[object] = []

        def worker(index: int) -> None:
            barrier.wait()
            for i in range(self.ITERS):
                try:
                    fn(index, i)
                except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                    problems.append(exc)

        with ThreadPoolExecutor(max_workers=self.THREADS) as pool:
            list(pool.map(worker, range(self.THREADS)))
        return problems

    def test_concurrent_one_shot_roundtrip(self):
        payloads = [self._payload(k) for k in range(self.THREADS * self.ITERS)]
        compressed = [compress_data(p) for p in payloads]

        def fn(worker: int, i: int) -> None:
            idx = worker * self.ITERS + i
            assert decompress_data(compressed[idx]) == payloads[idx]

        problems = self._run_concurrently(fn)
        assert not problems, f"concurrent one-shot decompression failed: {problems[:3]}"

    def test_concurrent_decompress_stream(self):
        payloads = [self._payload(k) for k in range(self.THREADS * self.ITERS)]
        frames = [compress_data(p) for p in payloads]

        def fn(worker: int, i: int) -> None:
            idx = worker * self.ITERS + i
            chunks = decompress_stream(
                io.BytesIO(frames[idx]), len(payloads[idx]), read_size=64 * 1024
            )
            assert b"".join(chunks) == payloads[idx]

        problems = self._run_concurrently(fn)
        assert not problems, f"concurrent stream decompression failed: {problems[:3]}"

    def test_concurrent_compress_one_shot_roundtrip(self):
        def fn(worker: int, i: int) -> None:
            payload = self._payload(worker * self.ITERS + i)
            assert decompress_data(compress_data(payload)) == payload

        problems = self._run_concurrently(fn)
        assert not problems, f"concurrent one-shot compression failed: {problems[:3]}"

    def test_concurrent_compress_round_trip_stream(self):
        def fn(worker: int, i: int) -> None:
            payload = self._payload(worker * self.ITERS + i)
            chunks = decompress_stream(
                io.BytesIO(compress_data(payload)), len(payload), read_size=64 * 1024
            )
            assert b"".join(chunks) == payload

        problems = self._run_concurrently(fn)
        assert not problems, f"concurrent compress+stream-decompress failed: {problems[:3]}"
