# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""L1 — compression micro-benchmark (pure, no sockets, deterministic).

Measures the Zstandard helpers on the upload/download fast paths:

* ``should_compress`` — the per-file size/extension gate evaluated during scans;
* ``compress_data`` / ``decompress_data`` on representative payload shapes
  (highly compressible text, semi-compressible binary, incompressible bytes) at
  sizes that cross the 10 KB/32 KB/100 KB thresholds and reach 10 MB;
* ``compress_file_to_file`` — the streaming production upload path;
* ``decompress_stream`` — the capped streaming reader used for HTTP response
  bodies (anti decompression-bomb).

Methodology specifics:

* Every compressed fixture is round-tripped during setup, and every measured
  decompression asserts the output length, so a fast path that silently
  produces short output cannot be reported as valid.
* ``decompress_data`` is always measured with the production-style explicit
  ``max_output_size`` (remote payloads must cap the output).
* The stream-cap guard is asserted once during setup (a cap below the payload
  size must raise ``zstd.ZstdError``), which keeps the measured rows honest.
* The compression-level A/B measures the direction-aware SSOT levels
  (``COMPRESSION_LEVEL`` vs ``COMPRESSION_LEVEL_FAST``, as
  ``compression_level()`` picks them for download vs upload/LAN).
* The library's DEBUG trace lines are suppressed (``logger.remove()``) so a
  sample reflects the production log level (INFO): loguru still builds the
  message, but no sink I/O can inflate the measured gate.
* Temp files live in a directory removed at exit (clean start, clean exit).

Usage:
    cd hsync-common && .venv/bin/python bench/bench_compression.py [--count N] [--json-out FILE]
"""

from __future__ import annotations

import argparse
import tempfile
from io import BytesIO
from pathlib import Path

import zstandard as zstd
from common import (
    BenchResult,
    add_json_out,
    make_payload,
    maybe_write_json,
    measure,
    print_table,
    write_bytes,
)
from loguru import logger

from hsync_common.compression import (
    COMPRESSION_LEVEL,
    COMPRESSION_LEVEL_FAST,
    compress_data,
    compress_file_to_file,
    decompress_data,
    decompress_stream,
    should_compress,
)

_MB = 1024 * 1024

# (label, payload kind, size, sample cap) for the compression-level A/B: the
# direction-aware SSOT levels, exactly as `compression_level()` picks them for
# download vs upload/LAN.
_LEVEL_AB_SCENARIOS: tuple[tuple[str, str, int, int], ...] = (
    ("text-1MB", "text", _MB, 200),
    ("binary-1MB", "binary", _MB, 200),
)

# label → (payload kind, size, sample cap). The 10MB text case is the heaviest
# realistic upload, so it gets a hard sample cap.
_DATA_SCENARIOS: tuple[tuple[str, str, int, int], ...] = (
    ("text-100KB", "text", 100 * 1024, 1000),
    ("text-1MB", "text", _MB, 200),
    ("binary-1MB", "binary", _MB, 200),
    ("incompressible-1MB", "incompressible", _MB, 200),
    ("text-10MB", "text", 10 * _MB, 30),
)

# label → (size, sample cap) for the streaming src→dst compressor.
_FILE_SCENARIOS: tuple[tuple[str, int, int], ...] = (
    ("1MB", _MB, 200),
    ("16MB", 16 * _MB, 20),
)


def _bench_should_compress(count: int) -> BenchResult:
    """The gate is called once per file per scan: keep it branch-covering."""
    # (filepath, size, transfer_type, is_lan) — all four threshold branches plus
    # both precompressed and compressing extensions.
    cases = [
        ("/bucket/small.txt", 9 * 1024, "download", False),
        ("/bucket/small.txt", 9 * 1024, "upload", False),
        ("/bucket/large.txt", _MB, "download", False),
        ("/bucket/large.txt", _MB, "upload", False),
        ("/bucket/large.txt", _MB, "download", True),
        ("/bucket/photo.jpg", 4 * _MB, "download", False),
        ("/bucket/archive.zip", 4 * _MB, "upload", False),
        ("/bucket/dump.sql", 256 * 1024, "upload", False),
    ]
    outcomes = {should_compress(path, size, ttype, lan) for path, size, ttype, lan in cases}
    assert outcomes == {True, False}, outcomes
    state = {"i": 0}

    def op() -> None:
        filepath, size, transfer_type, is_lan = cases[state["i"] % len(cases)]
        state["i"] += 1
        should_compress(filepath, size, transfer_type, is_lan)

    return measure("should_compress", op, count=count)


def _bench_data(label: str, kind: str, size: int, count: int) -> list[BenchResult]:
    """Time in-memory compress+decompress of one payload shape."""
    data = make_payload(size, kind, seed=size)
    compressed = compress_data(data)
    assert decompress_data(compressed, max_output_size=size) == data

    def op_compress() -> None:
        compress_data(data)

    def op_decompress() -> None:
        out = decompress_data(compressed, max_output_size=size)
        assert len(out) == size, len(out)

    return [
        measure(f"compress_data({label})", op_compress, count=count),
        measure(f"decompress_data({label})", op_decompress, count=count),
    ]


def _bench_level_ab(label: str, kind: str, size: int, count: int) -> tuple[list[BenchResult], str]:
    """A/B the direction-aware levels: CPU cost vs output size on one payload.

    Returns the two measured rows plus the one-line size comparison (printed
    after the table, not stored in the JSON: it describes the fixture, not a
    measured latency).
    """
    data = make_payload(size, kind, seed=size)
    default_frame = compress_data(data, level=COMPRESSION_LEVEL)
    fast_frame = compress_data(data, level=COMPRESSION_LEVEL_FAST)
    assert decompress_data(fast_frame, max_output_size=size) == data

    def op_default() -> None:
        compress_data(data, level=COMPRESSION_LEVEL)

    def op_fast() -> None:
        compress_data(data, level=COMPRESSION_LEVEL_FAST)

    rows = [
        measure(f"compress_lvl{COMPRESSION_LEVEL}({label})", op_default, count=count),
        measure(f"compress_lvl{COMPRESSION_LEVEL_FAST}({label})", op_fast, count=count),
    ]
    ratio = 100.0 * len(fast_frame) / len(default_frame)
    note = (
        f"  compressed size {label}: lvl{COMPRESSION_LEVEL}={len(default_frame)}B "
        f"lvl{COMPRESSION_LEVEL_FAST}={len(fast_frame)}B ({ratio:.2f}% of lvl{COMPRESSION_LEVEL})"
    )
    return rows, note


def _bench_file(workdir: str, label: str, size: int, count: int) -> BenchResult:
    """Time the streaming src→dst compressor (production upload path)."""
    src = write_bytes(workdir, f"src-{label}.bin", make_payload(size, "binary", seed=size))
    dst = str(Path(workdir) / f"dst-{label}.zst")
    expected = compress_file_to_file(src, dst)

    def op() -> None:
        written = compress_file_to_file(src, dst)
        assert written == expected, written

    return measure(f"compress_file_to_file({label})", op, count=count)


def _bench_decompress_stream(label: str, size: int, count: int) -> BenchResult:
    """Time the capped streaming reader consuming a whole compressed frame."""
    data = make_payload(size, "binary", seed=size)
    compressed = compress_data(data)

    # Cap enforcement is part of the contract (anti decompression-bomb): assert
    # it once during setup, outside the timed region.
    try:
        list(decompress_stream(BytesIO(compressed), max_output_size=size - 1))
    except zstd.ZstdError:
        pass
    else:  # pragma: no cover - fixture guard
        raise AssertionError("decompress_stream did not enforce max_output_size")

    def op() -> None:
        total = 0
        for chunk in decompress_stream(BytesIO(compressed), max_output_size=size):
            total += len(chunk)
        assert total == size, total

    return measure(f"decompress_stream({label})", op, count=count)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=2000)
    add_json_out(parser)
    args = parser.parse_args()

    # Silence the library's DEBUG trace lines: production runs at INFO, and a
    # written sink would add I/O cost to every measured should_compress call.
    logger.remove()

    count = args.count
    results = [_bench_should_compress(count)]
    level_notes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="hsync-common-bench-") as tmp:
        for label, kind, size, cap in _DATA_SCENARIOS:
            results.extend(_bench_data(label, kind, size, min(count, cap)))
        for label, kind, size, cap in _LEVEL_AB_SCENARIOS:
            rows, note = _bench_level_ab(label, kind, size, min(count, cap))
            results.extend(rows)
            level_notes.append(note)
        for label, size, cap in _FILE_SCENARIOS:
            results.append(_bench_file(tmp, label, size, min(count, cap)))
        results.append(_bench_decompress_stream("binary-1MB", _MB, min(count, 200)))

    print(f"compression micro-benchmark (ops={count}, in-memory + temp files)")
    print_table(results)
    for note in level_notes:
        print(note)
    maybe_write_json(args.json_out, results)


if __name__ == "__main__":
    main()
