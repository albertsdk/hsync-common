#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Regenerate the protocol contract and mirror the golden fixtures into Android.

One command that (1) rebuilds the WS/LAN schemas and golden fixtures from the
Python source of truth (delegating to ``export_protocol_schemas``) and (2) copies
the fixtures verbatim into the Android test resources
(``hsync_common.protocol.ANDROID_FIXTURES_DIR``), pruning any stale file so the
two trees stay byte-identical. The cross-language parity test
(`tests/test_protocol_fixtures.py::TestAndroidFixtureParity`) asserts exactly
this, so run this after any handshake/model change instead of copying by hand.

With ``--check`` it writes nothing and instead verifies that the committed
schemas, fixtures and Android mirror match the source of truth, exiting non-zero
on any drift (suitable for CI / pre-commit gating).

Usage:
    poetry run python scripts/sync_android_fixtures.py            # regenerate + copy
    poetry run python scripts/sync_android_fixtures.py --check    # verify only
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Make the sibling exporter importable when run as a plain file from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from export_protocol_schemas import export_fixtures, export_schemas

from hsync_common.protocol import (
    ANDROID_FIXTURES_DIR,
    FIXTURES_DIR,
    LAN_TXT_SCHEMA_PATH,
    LAN_WSS_SCHEMA_PATH,
    WS_SCHEMA_PATH,
    dump_contract,
)
from hsync_common.protocol.fixtures import build_fixtures
from hsync_common.protocol.schemas import (
    build_lan_txt_schema,
    build_lan_wss_schema,
    build_ws_schema,
)

# .../hsync-android/app — stable marker that the Android checkout is present.
_ANDROID_APP_DIR = ANDROID_FIXTURES_DIR.parents[4]

_REGEN_HINT = "Regenerate with: poetry run python scripts/sync_android_fixtures.py"


def sync_android_fixtures() -> tuple[list[Path], list[Path]]:
    """Mirror the committed golden fixtures into the Android test resources.

    Copies the canonical ``FIXTURES_DIR`` set verbatim and prunes any stale
    JSON so the Android resources remain byte-identical to the Python source.
    Returns ``(copied, removed)`` paths.
    """
    ANDROID_FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    canonical = {p.name for p in FIXTURES_DIR.glob("*.json")}

    copied: list[Path] = []
    for name in sorted(canonical):
        dest = ANDROID_FIXTURES_DIR / name
        shutil.copyfile(FIXTURES_DIR / name, dest)
        copied.append(dest)

    removed: list[Path] = []
    for stale in sorted(ANDROID_FIXTURES_DIR.glob("*.json")):
        if stale.name not in canonical:
            stale.unlink()
            removed.append(stale)

    return copied, removed


def _diff_file(path: Path, expected: str) -> list[str]:
    """Report whether ``path`` is missing or diverges from ``expected`` bytes."""
    if not path.is_file():
        return [f"missing {path}"]
    if path.read_text(encoding="utf-8") != expected:
        return [f"drift   {path}"]
    return []


def _diff_set(directory: Path, expected: set[str], label: str) -> list[str]:
    """Report orphan/missing ``*.json`` stems in ``directory`` vs ``expected``."""
    actual = {p.stem for p in directory.glob("*.json")}
    problems: list[str] = []
    if orphan := actual - expected:
        problems.append(f"orphan  {label} in {directory}: {sorted(orphan)}")
    if missing := expected - actual:
        problems.append(f"missing {label} in {directory}: {sorted(missing)}")
    return problems


def check_drift() -> list[str]:
    """Return human-readable drift problems; empty when everything is in sync.

    Verifies, without writing anything, that the committed WS/LAN schemas, the
    golden fixtures and the Android mirror match what would be regenerated from
    the Python source of truth.
    """
    problems: list[str] = []
    for path, schema in (
        (WS_SCHEMA_PATH, build_ws_schema()),
        (LAN_TXT_SCHEMA_PATH, build_lan_txt_schema()),
        (LAN_WSS_SCHEMA_PATH, build_lan_wss_schema()),
    ):
        problems += _diff_file(path, dump_contract(schema))

    fixtures = build_fixtures()
    for name, fixture in fixtures.items():
        problems += _diff_file(FIXTURES_DIR / f"{name}.json", dump_contract(fixture))
    problems += _diff_set(FIXTURES_DIR, set(fixtures), "fixtures")

    if _ANDROID_APP_DIR.is_dir():
        for name, fixture in fixtures.items():
            problems += _diff_file(ANDROID_FIXTURES_DIR / f"{name}.json", dump_contract(fixture))
        problems += _diff_set(ANDROID_FIXTURES_DIR, set(fixtures), "Android fixtures")

    return problems


def _run_check() -> int:
    """Verify the committed contract is in sync; exit non-zero on drift."""
    problems = check_drift()
    if problems:
        print("Protocol contract drift detected:")
        for problem in problems:
            print(f"  {problem}")
        print(f"\n{_REGEN_HINT}")
        return 1
    print("Protocol contract in sync (schemas + fixtures + Android mirror).")
    return 0


def _run_sync() -> int:
    """Regenerate the contract and sync fixtures into Android."""
    for path in (*export_schemas(), *export_fixtures()):
        print(f"Wrote {path}")

    if not _ANDROID_APP_DIR.is_dir():
        print(f"Android checkout not found at {_ANDROID_APP_DIR}; skipped fixture copy.")
        return 0

    copied, removed = sync_android_fixtures()
    for path in removed:
        print(f"Removed stale {path}")
    for path in copied:
        print(f"Copied {path}")
    print(f"Synced {len(copied)} fixtures into {ANDROID_FIXTURES_DIR}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Regenerate + sync, or verify drift with ``--check``."""
    parser = argparse.ArgumentParser(description="Sync protocol fixtures into Android.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed schemas/fixtures/Android mirror without writing",
    )
    args = parser.parse_args(argv)
    return _run_check() if args.check else _run_sync()


if __name__ == "__main__":
    raise SystemExit(main())
