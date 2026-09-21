#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Export the WebSocket/p2p JSON Schemas and golden fixtures to the protocol contract.

This is the only supported way to update the committed snapshots
(``hsync_common.protocol.WS_SCHEMA_PATH``, ``P2P_TXT_SCHEMA_PATH``,
``P2P_WSS_SCHEMA_PATH``, ``P2P_SOURCES_SCHEMA_PATH`` and the ``FIXTURES_DIR``
golden fixtures). The matching drift-check tests
(`tests/test_protocol_schemas.py`, `tests/test_protocol_fixtures.py`) fail
whenever what is rebuilt from the Python source of truth diverges from the
committed files, so run this script after any handshake/model change.

Usage:
    poetry run python scripts/export_protocol_schemas.py
"""

from __future__ import annotations

from pathlib import Path

from hsync_common.protocol import (
    FIXTURES_DIR,
    P2P_SOURCES_SCHEMA_PATH,
    P2P_TXT_SCHEMA_PATH,
    P2P_WSS_SCHEMA_PATH,
    WS_SCHEMA_PATH,
    dump_contract,
)
from hsync_common.protocol.fixtures import build_fixtures
from hsync_common.protocol.schemas import (
    build_p2p_sources_schema,
    build_p2p_txt_schema,
    build_p2p_wss_schema,
    build_ws_schema,
)


def export_schemas() -> list[Path]:
    """Write the canonical WS/p2p JSON Schemas; return the written paths."""
    written: list[Path] = []
    for path, schema in (
        (WS_SCHEMA_PATH, build_ws_schema()),
        (P2P_TXT_SCHEMA_PATH, build_p2p_txt_schema()),
        (P2P_WSS_SCHEMA_PATH, build_p2p_wss_schema()),
        (P2P_SOURCES_SCHEMA_PATH, build_p2p_sources_schema()),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_contract(schema), encoding="utf-8")
        written.append(path)
    return written


def export_fixtures() -> list[Path]:
    """Write the canonical golden fixtures; return the written paths."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, fixture in build_fixtures().items():
        path = FIXTURES_DIR / f"{name}.json"
        path.write_text(dump_contract(fixture), encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    """Regenerate and write the canonical WS/p2p schemas and golden fixtures."""
    for path in (*export_schemas(), *export_fixtures()):
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
