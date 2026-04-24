# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""L1 — hashing micro-benchmark (pure, no sockets, deterministic).

Measures the checksum path every consumer uses on every scanned file:

* ``compute_sha256`` / ``compute_sha256_async`` at the 64KB/1MB/16MB sizes that
  bracket the ``adaptive_chunk_size`` tiers used in production scans;
* ``is_sha256_hex`` — the wire-facing digest-shape gate run before every
  ``hmac.compare_digest`` on a peer-supplied checksum;
* ``adaptive_chunk_size`` — the per-file tier dispatch.

Methodology specifics:

* Fixtures are written to a temp directory that is removed at exit (clean start
  and clean exit); payloads are deterministic (:func:`common.make_payload`).
* Each measured digest is asserted against the digest computed during setup, so
  a silently truncated read can never masquerade as a fast hash.
* The OS page cache is warm on purpose: the benchmark compares implementations
  and chunk sizes on the same machine, it does not model cold-disk I/O.
* Only the async scenarios use a running event loop (as production does); the
  loop is created once per scenario and never inside the timed region.

Usage:
    cd hsync-common && .venv/bin/python bench/bench_hashing.py [--count N] [--json-out FILE]
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile

from common import (
    BenchResult,
    add_json_out,
    make_payload,
    maybe_write_json,
    measure,
    measure_async,
    print_table,
    write_bytes,
)

from hsync_common.hashing import (
    adaptive_chunk_size,
    compute_sha256,
    compute_sha256_async,
    is_sha256_hex,
)

# Size label → bytes. 1MB is the FILE_SIZE_SMALL boundary and 16MB sits inside
# the medium tier, so the sweep crosses one tier edge with a realistic heavy case.
_SIZES: tuple[tuple[str, int], ...] = (
    ("64KB", 64 * 1024),
    ("1MB", 1024 * 1024),
    ("16MB", 16 * 1024 * 1024),
)

# Sample caps: a 16MB read+hash costs ~50ms, micro ops a few hundred ns.
_SYNC_CAPS = {"64KB": 2000, "1MB": 1000, "16MB": 200}
_ASYNC_CAPS = {"64KB": 500, "1MB": 200, "16MB": 50}


def _bench_micro(count: int) -> list[BenchResult]:
    """Timing of the two pure per-file helpers (no I/O)."""
    digests = [f"{index:064x}" for index in range(64)]
    sizes = [
        None,
        0,
        8 * 1024,
        512 * 1024,
        1024 * 1024,
        4 * 1024 * 1024,
        100 * 1024 * 1024,
        1 << 40,
    ]
    digest_state = {"i": 0}
    size_state = {"i": 0}

    def op_is_sha256_hex() -> None:
        value = digests[digest_state["i"] % len(digests)]
        digest_state["i"] += 1
        assert is_sha256_hex(value), value

    def op_adaptive_chunk_size() -> None:
        size = sizes[size_state["i"] % len(sizes)]
        size_state["i"] += 1
        assert adaptive_chunk_size(size) > 0

    return [
        measure("is_sha256_hex", op_is_sha256_hex, count=count),
        measure("adaptive_chunk_size", op_adaptive_chunk_size, count=count),
    ]


def _bench_sha256(workdir: str, label: str, size: int, count: int) -> BenchResult:
    """Time ``compute_sha256`` on a warm-cache file of ``size`` bytes."""
    path = write_bytes(workdir, f"sync-{label}.bin", make_payload(size, "binary", seed=size))
    expected = compute_sha256(path)

    def op() -> None:
        digest = compute_sha256(path)
        assert digest == expected, digest

    return measure(f"sha256({label})", op, count=count)


async def _bench_sha256_async(workdir: str, label: str, size: int, count: int) -> BenchResult:
    """Time ``compute_sha256_async`` on one running loop."""
    path = write_bytes(workdir, f"async-{label}.bin", make_payload(size, "binary", seed=size + 1))
    expected = await compute_sha256_async(path)

    async def op() -> None:
        digest = await compute_sha256_async(path)
        assert digest == expected, digest

    return await measure_async(f"sha256_async({label})", op, count=count)


async def _bench_async_all(workdir: str, count: int) -> list[BenchResult]:
    return [
        await _bench_sha256_async(workdir, label, size, min(count, _ASYNC_CAPS[label]))
        for label, size in _SIZES
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=2000)
    add_json_out(parser)
    args = parser.parse_args()

    count = args.count
    with tempfile.TemporaryDirectory(prefix="hsync-common-bench-") as tmp:
        results = _bench_micro(count)
        for label, size in _SIZES:
            results.append(_bench_sha256(tmp, label, size, min(count, _SYNC_CAPS[label])))
        results.extend(asyncio.run(_bench_async_all(tmp, count)))

    print(f"hashing micro-benchmark (ops={count}, warm page cache)")
    print_table(results)
    maybe_write_json(args.json_out, results)


if __name__ == "__main__":
    main()
