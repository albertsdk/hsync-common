# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Run every L1 benchmark and write one versioned results file.

Mirrors ``hsync-bootnode/bench_result.txt``: a single committed file that
records the baseline of one machine so two revisions can be compared
(``git diff bench_result.txt``). The file is a comparison artefact, not an SLA:
each section is the raw stdout of one ``bench_*.py`` script plus its exit code,
so a failed scenario is visible instead of being silently missing.

Each script still runs standalone (``--count``/``--json-out``); this runner only
chains them in a fixed order with a shared sample count.

Usage:
    cd hsync-common && .venv/bin/python bench/run_all.py [--count N] [--out FILE]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

_BENCH_DIR = Path(__file__).resolve().parent
_SCRIPTS = (
    "bench_hashing",
    "bench_compression",
    "bench_delta",
    "bench_ignore",
    "bench_models",
    "bench_path_validation",
    "bench_stores",
)
_DEFAULT_OUT = _BENCH_DIR.parent / "bench_result.txt"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=2000)
    parser.add_argument(
        "--out",
        default=str(_DEFAULT_OUT),
        help="Results file to write (default: <repo root>/bench_result.txt).",
    )
    args = parser.parse_args()

    sections: list[str] = [
        f"hsync-common L1 benchmark suite — count={args.count}",
        f"python {sys.version.split()[0]} — {sys.platform}",
        f"generated {time.strftime('%Y-%m-%d %H:%M:%S')} by bench/run_all.py",
        "comparative figures (this machine, warm page cache), not SLAs",
        "",
    ]
    failed: list[str] = []
    for script in _SCRIPTS:
        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(_BENCH_DIR / f"{script}.py"), "--count", str(args.count)],
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed = time.perf_counter() - start
        sections.append(f"=== {script} (exit={proc.returncode}, {elapsed:.1f}s) ===")
        sections.append(proc.stdout.rstrip("\n") or "(no stdout)")
        if proc.returncode != 0:
            sections.append("--- stderr ---")
            sections.append(proc.stderr.rstrip("\n") or "(no stderr)")
            failed.append(script)
        sections.append("")
        print(f"{script}: exit={proc.returncode} ({elapsed:.1f}s)")

    Path(args.out).write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    if failed:
        print(f"FAILED scenarios: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
