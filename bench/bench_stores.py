# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""L1 — causal SQLite store micro-benchmark (pure, no sync sockets).

Measures the SQLite-backed sync state stores (see :mod:`hsync_common.models`
— ADR-0025 ``state DB``):

* ``SyncStateStore`` — the path&rarr;file-version map used by client (per-dir)
  and server (per-bucket); exercises ``record``, ``get`` (dict hit), ``retain``,
  then ``save``/``load`` round-trip through SQLite WAL.
* ``TombstoneStore`` — the causal deletion marker map; exercises
  ``record`` + ``merge`` (the untrusted-payload path that validates + decides
  adopt/discard on every entry).

The measured ops **assert correctness** inside the timed region (round-trip row
count, dominant clock wins on merge, retain drops the right suffix) so a
short-circuiting or incorrectly-typed store cannot be reported as fast.

Store lifecycle: one ``TemporaryDirectory`` per run, a fresh ``state DB``
opened in WAL, ``folder_id`` constant for isolation; cleanup is via the temp
dir finaliser (clean exit), matching the delta benchmark methodology.

Usage:
    cd hsync-common && .venv/bin/python bench/bench_stores.py [--count N] [--json-out FILE]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BenchResult,
    add_json_out,
    maybe_write_json,
    measure,
    print_table,
)

from hsync_common.models.tombstone import TombstoneEntry  # noqa: E402
from hsync_common.models.tombstone_store import TombstoneStore  # noqa: E402
from hsync_common.models.version_store import SyncStateStore  # noqa: E402


def _cid(seed: int) -> str:
    """Deterministic 21-char alphanumeric client ID (``CID_PATTERN``-compliant)."""
    return f"TestClient{seed:011d}"


def _build_version_store(db_path: str, folder_id: str, count: int) -> SyncStateStore:
    store = SyncStateStore(db_path=db_path, folder_id=folder_id)
    for index in range(count):
        store.record(
            f"file_{index:06d}.dat",
            base_hash=f"{index:064x}",
            version_id=f"v{index:08x}",
            origin_cid=_cid(index % 8),
            timestamp=1_000_000 + index,
            vclock={_cid(index % 8): index + 1},
        )
    store.save()
    return store


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000, help="entries per store")
    add_json_out(parser)
    args = parser.parse_args()

    results: list[BenchResult] = []

    with tempfile.TemporaryDirectory(prefix="hsync_stores_") as tmp:
        db = str(Path(tmp, "state DB"))
        folder_id = "folder_00000000"
        n = args.count

        # ---- SyncStateStore: in-memory mutations (dict-backed) ----
        vs = _build_version_store(db, folder_id, n)

        def vs_record() -> None:
            # Overwrite an existing + insert a fresh one.
            vs.record(
                "file_000001.dat",
                base_hash="ab" * 32,
                version_id="x",
                origin_cid=_cid(9),
                timestamp=2_000_000,
                vclock={_cid(9): 1},
            )
            vs.record(
                f"fresh_{n:06d}.dat",
                base_hash="cd" * 32,
                version_id="y",
                origin_cid=_cid(9),
                timestamp=2_000_001,
                vclock={_cid(9): 1},
            )

        def vs_get() -> None:
            # Hot read path: dict lookup, the per-entry cost server pays on listing.
            assert vs.get("file_000000.dat") is not None
            assert vs.get("missing.dat") is None

        def vs_retain() -> None:
            # Keep first 10% then drop the rest — assertion: drop == len(store) - keep.
            total = len(vs)
            keep = [f"file_{i:06d}.dat" for i in range(0, total // 10)]
            dropped = vs.retain(keep)
            assert dropped == total - len(keep), f"{dropped} != {total} - {len(keep)}"

        results.append(measure("SyncStateStore.record", vs_record, count=n))
        results.append(measure("SyncStateStore.get", vs_get, count=n))
        results.append(measure("SyncStateStore.retain", vs_retain, count=50))

        # ---- SyncStateStore: SQLite round-trip ----
        def vs_save_load() -> None:
            vs.save()
            reloaded = SyncStateStore(db_path=db, folder_id=folder_id)
            reloaded.load()
            assert len(reloaded) == len(vs)

        results.append(measure("SyncStateStore.save+load", vs_save_load, count=30))

        # ---- TombstoneStore: in-memory merge (untrusted-payload path) ----
        cid_a = _cid(0)
        cid_b = _cid(1)
        ts = TombstoneStore(db_path=db, folder_id="folder_tomb")
        # Seed with one entry from peer A (clock ticked by A to {A: 1}).
        ts.record(
            relpath="ghost.dat",
            sha256sum="aa" * 32,
            origin_cid=cid_a,
            timestamp=1_000_000,
        )
        ts.save()
        stored_key = "b8e230df6da6a8dd02473293989545d9ee908676c022e43be287f3ef2ac7ff24"  # sha256 of "ghost.dat"

        merge_counter = {"tick": 4}

        def ts_merge() -> None:
            # Each call sends peer B's clock one tick ahead of the stored one,
            # so the merge always adopts and the measured cost stays constant
            # across the warmup + timed iterations (unlike a fixed clock, which
            # would only adopt once and then report a spurious 0-change merge).
            merge_counter["tick"] += 1
            tick = merge_counter["tick"]
            payload: dict[str, TombstoneEntry] = {
                stored_key: {
                    "sha256": "bb" * 32,
                    "version_id": "t00000002",
                    "origin_cid": cid_b,
                    "ts": 1_000_000 + tick,
                    "vclock": {cid_a: 1, cid_b: tick},
                }
            }
            changed = ts.merge(payload)
            # B's clock strictly dominates the stored one -> adopt, exactly 1 change.
            assert changed == 1, f"expected 1, got {changed}"
            assert ts.get("ghost.dat")["origin_cid"] == cid_b

        results.append(measure("TombstoneStore.merge(dominant)", ts_merge, count=n))

        print_table(results)
        maybe_write_json(args.json_out, results)


if __name__ == "__main__":
    main()
