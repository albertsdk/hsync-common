# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Shared measurement core for the L1 micro-benchmarks (stdlib only).

Methodology mirrors ``hsync-bootnode/bench/common.py``: one :class:`BenchResult`
per measured operation, warmup executed outside the timed samples, per-call
``time.perf_counter`` latency, and an optional ``--json-out`` dump.

This module **never imports** ``hsync_common``: the benchmark harness must stay
usable even if the library internals are rewritten, and these helpers are not
part of the shipped package (consumers: the ``bench/bench_*.py`` scripts only).

Determinism: fixtures are derived from a seeded :class:`random.Random`, so a
given seed reproduces the same payloads on the same interpreter. Timings are
comparative (this machine, warm OS page cache), never production SLAs.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

__all__ = [
    "PAYLOAD_KINDS",
    "BenchResult",
    "add_json_out",
    "make_payload",
    "maybe_write_json",
    "measure",
    "measure_async",
    "percentile",
    "print_table",
    "pseudorandom_bytes",
    "scaled_warmup",
    "size_label",
    "text_payload",
    "write_bytes",
]

# Payload shapes shared by the compression/delta benchmarks.
PAYLOAD_KINDS = ("text", "binary", "incompressible")

# One repetitive ASCII line: high, stable zstd compression ratio.
_TEXT_LINE = b"hsync common benchmark payload line %08d - compressible source text\n"

# Translating to the low nibble keeps 4 bits of entropy per byte: zstd finds
# structure without finding redundancy, i.e. a semi-compressible "binary" file.
_LOW_NIBBLE_TABLE = bytes(value & 0x0F for value in range(256))


def text_payload(size: int) -> bytes:
    """Return ``size`` bytes of deterministic, highly compressible text."""
    repeats = size // len(_TEXT_LINE) + 1
    return b"".join(_TEXT_LINE % index for index in range(repeats))[:size]


def pseudorandom_bytes(size: int, seed: int = 0) -> bytes:
    """Return ``size`` effectively incompressible bytes (seeded, reproducible)."""
    return random.Random(seed).randbytes(size)


def make_payload(size: int, kind: str = "text", seed: int = 0) -> bytes:
    """Build a deterministic payload of exactly ``size`` bytes.

    Args:
        size: Payload size in bytes.
        kind: One of :data:`PAYLOAD_KINDS`.
        seed: Seed for the semi/incompressible shapes (ignored by ``text``).

    Raises:
        ValueError: If ``kind`` is not a known payload shape.
    """
    if kind == "text":
        return text_payload(size)
    if kind == "binary":
        return pseudorandom_bytes(size, seed).translate(_LOW_NIBBLE_TABLE)
    if kind == "incompressible":
        return pseudorandom_bytes(size, seed)
    raise ValueError(f"unknown payload kind {kind!r}; expected one of {PAYLOAD_KINDS}")


def write_bytes(directory: str | Path, name: str, data: bytes) -> str:
    """Write ``data`` to ``directory/name`` and return the path as a string."""
    path = Path(directory) / name
    path.write_bytes(data)
    return str(path)


def scaled_warmup(count: int, cap: int = 200) -> int:
    """Warmup iterations for one scenario, capped and proportional to ``count``.

    A 16 MB hash or a 10 MB compression costs 3-4 orders of magnitude more than
    a validation helper: a flat 200-iteration warmup would multiply the runtime
    of every heavy scenario. ``count // 10`` (bounded by ``cap`` and at least 1)
    keeps the warmup a small, constant fraction of the measured run.
    """
    return max(1, min(cap, count // 10))


def size_label(size: int) -> str:
    """Compact binary-unit label for scenario names (``1MB``, ``512KB``).

    Derived from the size actually used, so a scenario name never drifts from
    the parameters it describes.
    """
    if size and size % (1024 * 1024) == 0:
        return f"{size // (1024 * 1024)}MB"
    return f"{size // 1024}KB"


class BenchResult:
    """One measured operation: name, sample count and latency stats (ms)."""

    def __init__(self, name: str, samples: Sequence[float], count: int) -> None:
        lat_ms = [sample * 1000.0 for sample in samples]
        self.name = name
        self.count = count
        self.total_s = sum(samples)
        self.ops = count / self.total_s if self.total_s > 0 else 0.0
        self.p50 = statistics.median(lat_ms) if lat_ms else 0.0
        self.p99 = percentile(lat_ms, 99.0)
        self.mean = statistics.fmean(lat_ms) if lat_ms else 0.0

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "count": self.count,
            "total_s": round(self.total_s, 4),
            "ops_per_s": round(self.ops, 1),
            "mean_ms": round(self.mean, 4),
            "p50_ms": round(self.p50, 4),
            "p99_ms": round(self.p99, 4),
        }


def percentile(data: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile: ``rank = ceil(pct/100 * n) - 1``."""
    if not data:
        return 0.0
    ordered = sorted(data)
    rank = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * pct / 100.0) - 1))
    return ordered[rank]


def measure(
    name: str,
    func: Callable[[], None],
    *,
    count: int,
    warmup: int | None = None,
) -> BenchResult:
    """Run ``func`` ``count`` times (after ``warmup``) and time each call."""
    if warmup is None:
        warmup = scaled_warmup(count)
    for _ in range(warmup):
        func()
    samples: list[float] = []
    for _ in range(count):
        start = time.perf_counter()
        func()
        samples.append(time.perf_counter() - start)
    return BenchResult(name, samples, count)


async def measure_async(
    name: str,
    func: Callable[[], Awaitable[None]],
    *,
    count: int,
    warmup: int | None = None,
) -> BenchResult:
    """Await ``func`` ``count`` times (after ``warmup``) on one running loop.

    Production awaits the async helpers (``compute_sha256_async``) on a live
    event loop, so the loop is created once per scenario: its setup cost is
    never part of a measured sample.
    """
    if warmup is None:
        warmup = scaled_warmup(count)
    for _ in range(warmup):
        await func()
    samples: list[float] = []
    for _ in range(count):
        start = time.perf_counter()
        await func()
        samples.append(time.perf_counter() - start)
    return BenchResult(name, samples, count)


def print_table(results: Sequence[BenchResult]) -> None:
    """Print one aligned row per measured operation."""
    header = f"{'operation':<28}{'ops/s':>12}{'mean_ms':>10}{'p50_ms':>10}{'p99_ms':>10}{'n':>8}"
    print(header)
    print("-" * len(header))
    for result in results:
        print(
            f"{result.name:<28}{result.ops:>12.1f}{result.mean:>10.4f}"
            f"{result.p50:>10.4f}{result.p99:>10.4f}{result.count:>8}"
        )


def add_json_out(parser: argparse.ArgumentParser) -> None:
    """Register the shared ``--json-out`` option on ``parser``."""
    parser.add_argument(
        "--json-out",
        default=None,
        help="Write the results as JSON to the given path (besides stdout).",
    )


def maybe_write_json(path: str | None, results: Sequence[BenchResult]) -> None:
    """Dump ``results`` as JSON when ``path`` was provided."""
    if not path:
        return
    with open(path, "w", encoding="utf-8") as handle:
        json.dump([result.as_dict() for result in results], handle, indent=2)
        handle.write("\n")
    print(f"wrote {path}")
