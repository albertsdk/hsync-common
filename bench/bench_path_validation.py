# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso.

"""L1 — wire-path validation micro-benchmark (pure, no sockets).

Measures the security gate that every inbound event/listing/transfer path
must pass before touching the filesystem (see :mod:`hsync_common.path_validation`):

* ``validate_remote_relpath`` &mdash; pure-string lexical validation (NFC normalisation,
  control-char / backslash / reserved-name / per-component length guards). This
  is O(path-length) with **no** syscall &mdash; expected to be sub-microsecond;
* ``resolve_within`` &mdash; the confining ``Path.resolve()`` that dereferences
  symlinks and checks ``relative_to(base)``: syscall-bound on the hit path and
  the path where a traversal attempt is actually rejected;
* ``wire_relpaths`` &mdash; the event-payload extractor that pulls every
  ``filepath``/``path`` key present (two-key smuggle gate).

Two path classes are measured:

* **valid** &mdash; a bucket-relative path with a real file on disk, so the
  ``exists()``/``resolve()`` syscalls succeed (confinement hit);
* **escape** &mdash; ``../`` traversal that the gate must reject; ``resolve()``
  still runs (the syscall happens before the containment check), so this measures
  the rejection cost as seen by a hostile peer.

The hit/escape split is what the LAN P2P and server relays pay on every inbound
listing entry and every delta base lookup: validating a hostile path must not be
cheaper (or slower) than a valid one, because the cost floor is the
``resolve()`` syscall itself.

Usage:
    cd hsync-common && .venv/bin/python bench/bench_path_validation.py [--count N] [--json-out FILE]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

# Allow ``from common import ...`` when run from the bench/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402  (import after sys.path tweak)
    BenchResult,
    add_json_out,
    maybe_write_json,
    measure,
    print_table,
)

from hsync_common.path_validation import (  # noqa: E402
    resolve_within,
    validate_remote_relpath,
    wire_relpaths,
)


def _build_fixtures(count: int) -> tuple[str, str, list[str], list[dict]]:
    """Return ``(base_dir, base_str, relpaths, payloads)`` for ``count`` iterations.

    A real temp dir with ``count`` files is created so ``resolve_within`` pays
    the genuine ``exists()``/``resolve()`` syscall on the hit path. The escape
    paths intentionally point *outside* ``base_dir`` &mdash; they are rejected
    after the syscall, never created on disk.
    """
    tmp = tempfile.mkdtemp(prefix="hsync_pv_")
    valid_rels: list[str] = []
    payloads: list[dict] = []
    for index in range(count):
        rel = f"dir_{index % 64}/file_{index:06d}.dat"
        Path(tmp, rel).parent.mkdir(parents=True, exist_ok=True)
        Path(tmp, rel).write_bytes(b"x" * 64)
        valid_rels.append(rel)
        payloads.append({"filepath": rel, "path": rel})
    return tmp, str(tmp), valid_rels, payloads


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=2000, help="iterations per scenario")
    add_json_out(parser)
    args = parser.parse_args()

    base_dir, base_str, relpaths, payloads = _build_fixtures(args.count)
    try:
        n = args.count

        # Hit-path: valid relpath that exists + resolves inside base.
        # ``relpaths`` cycled so the OS page cache is warm by sample time.
        hit_rel = relpaths[0]
        escape_rel = "../../../../etc/passwd"
        payload = payloads[0]

        # Warmup (outside timing): touch the syscall path once.
        for _ in range(64):
            validate_remote_relpath(hit_rel)
            resolve_within(base_str, hit_rel)
            validate_remote_relpath(escape_rel)
            resolve_within(base_str, escape_rel)
            wire_relpaths(payload)

        results: list[BenchResult] = []

        # 1. Pure lexing (no syscall) — the always-run guard.
        results.append(
            measure(
                "validate_remote_relpath(valid)",
                lambda: validate_remote_relpath(hit_rel),
                count=n,
            )
        )
        results.append(
            measure(
                "validate_remote_relpath(escape)",
                lambda: validate_remote_relpath(escape_rel),
                count=n,
            )
        )

        # 2. Confining resolve() — syscall-bound; the real wall-clock cost.
        results.append(
            measure(
                "resolve_within(valid)",
                lambda: resolve_within(base_str, hit_rel),
                count=n,
            )
        )
        results.append(
            measure(
                "resolve_within(escape)",
                lambda: resolve_within(base_str, escape_rel),
                count=n,
            )
        )

        # 3. Payload extraction (dict lookups only, no syscall).
        results.append(
            measure(
                "wire_relpaths(2-key)",
                lambda: wire_relpaths(payload),
                count=n,
            )
        )

        print_table(results)
        maybe_write_json(args.json_out, results)
    finally:
        import shutil

        shutil.rmtree(base_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
