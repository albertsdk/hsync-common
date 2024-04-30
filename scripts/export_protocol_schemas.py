#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Export the WebSocket and LAN/TXT JSON Schemas to the shared protocol contract.

This is the only supported way to update the committed snapshots
(``hsync_common.protocol.WS_SCHEMA_PATH`` and ``LAN_TXT_SCHEMA_PATH``). The
matching drift-check test (`tests/test_protocol_schemas.py`) fails whenever the
schemas rebuilt from the Python source of truth diverge from the committed
files, so run this script after any handshake/model change.

Usage:
    poetry run python scripts/export_protocol_schemas.py
"""

from __future__ import annotations

from hsync_common.protocol import (
    LAN_TXT_SCHEMA_PATH,
    WS_SCHEMA_PATH,
    dump_contract,
)
from hsync_common.protocol.schemas import build_lan_txt_schema, build_ws_schema


def main() -> None:
    """Regenerate and write the canonical WS and LAN/TXT schema snapshots."""
    for path, schema in (
        (WS_SCHEMA_PATH, build_ws_schema()),
        (LAN_TXT_SCHEMA_PATH, build_lan_txt_schema()),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_contract(schema), encoding="utf-8")
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
