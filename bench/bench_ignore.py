# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""L1 — ``.hsyncignore`` matching micro-benchmark (pure, no network).

The matcher is consulted for every entry of every scan, so this benchmark
covers both shapes of that cost:

* constructing / reloading an :class:`IgnoreMatcher` (gitignore patterns are
  compiled once per reload) with and without extra user patterns;
* per-path ``matches`` / ``should_skip`` latency on a deterministic path mix
  (ordinary files kept, plus hits for the default patterns and local rules);
* a full-scan sweep: one op matches the whole path list, i.e. the cost the sync
  engine pays per bucket scan.

Methodology specifics:

* Paths are absolute and bucket-rooted, exactly as the scan passes them
  (exercising the relative-path normalisation inside ``matches``).
* The sweep asserts the number of skipped paths observed during setup, so a
  matcher that stops honouring a layer cannot be reported as faster.
* The process-wide active matcher is installed for the ``should_skip`` rows and
  cleared in a ``finally`` (clean exit; no cross-scenario state).

Usage:
    cd hsync-common && .venv/bin/python bench/bench_ignore.py [--count N] [--json-out FILE]
"""

from __future__ import annotations

import argparse
import tempfile
from os.path import join

from common import (
    BenchResult,
    add_json_out,
    maybe_write_json,
    measure,
    print_table,
)

from hsync_common.constants import HSYNCIGNORE_FILENAME
from hsync_common.ignore import IgnoreMatcher, set_active_matcher, should_skip

# Realistic bucket-local rules: directory, extension and anchored patterns.
_IGNORE_RULES = """\
# build artifacts
build/
dist/
out/
*.o
*.a
*.so
# logs and dumps
logs/
*.log
*.trace
core
# virtualenvs and caches
.venv/
venv/
__pycache__/
*.py[cod]
.cache/
.cargo/
thumbnails/
# editor and backup files
*.bak
*.orig
*.rej
*~
# archives produced locally
*.tar
*.tar.gz
*.zip
# local secrets and data
secrets.json
*.sqlite3
data/tmp/
tmp/
# anchored root-only file
/bucket-manifest.txt
"""

_EXTRA_PATTERN_COUNT = 200
_PATH_COUNT = 5000


def _extra_patterns(count: int) -> list[str]:
    """Deterministic extra patterns (never matching the generated paths)."""
    return [f"*.generated-{index}" for index in range(count)] + [
        f"generated-{index}/" for index in range(count // 2)
    ]


def _make_paths(root: str, count: int) -> list[tuple[str, bool]]:
    """Deterministic mix of kept paths and pattern hits (period 5 per category)."""
    paths: list[tuple[str, bool]] = []
    for index in range(count):
        prefix = "/".join(f"dir{index % 7}_{level}" for level in range(index % 4))
        category = index % 5
        if category == 0:
            rel, is_dir = f"{prefix}/module-{index}.py", False
        elif category == 1:
            rel, is_dir = f"{prefix}/build/object-{index}.o", False
        elif category == 2:
            rel, is_dir = f"{prefix}/logs", True
        elif category == 3:
            rel, is_dir = f"{prefix}/artifact-{index}.tmp", False
        else:
            rel, is_dir = f"{prefix}/report-{index}.txt", False
        paths.append((join(root, rel), is_dir))
    return paths


def _write_ignore_file(root: str) -> None:
    with open(join(root, HSYNCIGNORE_FILENAME), "w", encoding="utf-8") as handle:
        handle.write(_IGNORE_RULES)


def _bench_construction(root: str, extra: list[str] | None, count: int) -> BenchResult:
    """Time matcher construction (pattern compile + ``.hsyncignore`` read)."""

    def op() -> None:
        matcher = IgnoreMatcher(root, extra)
        assert matcher.bucket_root

    return measure(f"matcher_ctor(extra={len(extra or [])})", op, count=count)


def _bench_matches(
    matcher: IgnoreMatcher, paths: list[tuple[str, bool]], count: int
) -> BenchResult:
    """Per-path ``matches`` latency, rotating over the path mix."""
    state = {"i": 0}

    def op() -> None:
        path, is_dir = paths[state["i"] % len(paths)]
        state["i"] += 1
        assert isinstance(matcher.matches(path, is_dir=is_dir), bool)

    return measure("matches(single path)", op, count=count)


def _bench_should_skip(paths: list[tuple[str, bool]], count: int) -> BenchResult:
    """Per-path ``should_skip`` latency through the active-matcher singleton."""
    state = {"i": 0}

    def op() -> None:
        path, is_dir = paths[state["i"] % len(paths)]
        state["i"] += 1
        assert isinstance(should_skip(path, is_dir=is_dir), bool)

    return measure("should_skip(single path)", op, count=count)


def _bench_sweep(
    matcher: IgnoreMatcher, paths: list[tuple[str, bool]], count: int, label: str
) -> BenchResult:
    """One op = match every generated path (the per-scan cost)."""
    expected = sum(1 for path, is_dir in paths if matcher.matches(path, is_dir=is_dir))
    assert 0 < expected < len(paths), expected

    def op() -> None:
        skipped = 0
        for path, is_dir in paths:
            skipped += matcher.matches(path, is_dir=is_dir)
        assert skipped == expected, skipped

    return measure(label, op, count=count)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=2000)
    add_json_out(parser)
    args = parser.parse_args()

    count = args.count
    with tempfile.TemporaryDirectory(prefix="hsync-common-bench-") as root:
        _write_ignore_file(root)
        matcher = IgnoreMatcher(root)
        paths = _make_paths(root, _PATH_COUNT)
        results = [
            _bench_construction(root, None, min(count, 200)),
            _bench_construction(root, _extra_patterns(_EXTRA_PATTERN_COUNT), min(count, 100)),
            _bench_matches(matcher, paths, count),
        ]
        set_active_matcher(matcher)
        try:
            results.append(_bench_should_skip(paths, count))
            results.append(
                _bench_sweep(matcher, paths, min(count, 200), f"sweep({len(paths)} paths,bucket)")
            )
            # Fallback matcher (bucket_root=""): built-in default patterns only,
            # the shape used by the server where no .hsyncignore is installed.
            results.append(
                _bench_sweep(
                    IgnoreMatcher(""), paths, min(count, 200), f"sweep({len(paths)} paths,defaults)"
                )
            )
        finally:
            set_active_matcher(None)

    print(f"ignore-matching micro-benchmark (ops={count}, {_PATH_COUNT} paths/bucket)")
    print_table(results)
    maybe_write_json(args.json_out, results)


if __name__ == "__main__":
    main()
