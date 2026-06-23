# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Versioned wire-protocol contract, shared across every HSYNC component.

This package is the single source of truth for the on-the-wire contract.
The REST surface is captured as a committed OpenAPI snapshot exported
from the FastAPI server; both the server (drift check) and any client
tooling read it from here instead of re-deriving payload shapes by hand.

The snapshot is serialized through :func:`dump_openapi` so the exporter and
the drift-check test always agree byte-for-byte; never hand-edit the JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Root of the protocol contract directory (this package), resolved from the
# installed/editable location so consumers locate it without relative guessing.
PROTOCOL_DIR = Path(__file__).resolve().parent

# Canonical location of the committed REST OpenAPI snapshot.
REST_OPENAPI_PATH = PROTOCOL_DIR / "rest" / "openapi.json"

# Canonical locations of the committed WebSocket and LAN/TXT JSON Schemas
# (generated from hsync_common.protocol.schemas; never hand-edit them).
WS_SCHEMA_PATH = PROTOCOL_DIR / "ws" / "ws-schema.json"
LAN_TXT_SCHEMA_PATH = PROTOCOL_DIR / "lan" / "txt-schema.json"

# Canonical directory of the committed golden protocol fixtures (generated from
# hsync_common.protocol.fixtures; consumed as cross-language test inputs).
FIXTURES_DIR = PROTOCOL_DIR / "fixtures"

# Sibling Android test-resource mirror of FIXTURES_DIR. The Android contract
# test consumes byte-identical copies of the golden fixtures; resolved from the
# monorepo root (FIXTURES_DIR.parents[3]). Single source of truth for both the
# sync script and the cross-language parity test.
ANDROID_FIXTURES_DIR = (
    FIXTURES_DIR.parents[3]
    / "hsync-android"
    / "app"
    / "src"
    / "test"
    / "resources"
    / "protocol"
    / "fixtures"
)


def dump_contract(schema: dict[str, Any]) -> str:
    """Serialize a contract document to its canonical on-disk representation.

    Keys are sorted and the output is indented so every committed snapshot is
    diff-friendly and the exporter/drift-check produce identical bytes.
    """
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def load_contract(path: Path) -> dict[str, Any]:
    """Load a committed contract snapshot from ``path``."""
    return json.loads(path.read_text(encoding="utf-8"))


def dump_openapi(schema: dict[str, Any]) -> str:
    """Serialize an OpenAPI schema to its canonical on-disk representation."""
    return dump_contract(schema)


def load_openapi() -> dict[str, Any]:
    """Load the committed REST OpenAPI contract snapshot."""
    return load_contract(REST_OPENAPI_PATH)


# Public surface of the protocol package. ``load_openapi`` is the read-side twin
# of ``dump_openapi`` and is exported for external tooling even though the
# in-repo drift check only needs the dump side.
__all__ = [
    "PROTOCOL_DIR",
    "REST_OPENAPI_PATH",
    "WS_SCHEMA_PATH",
    "LAN_TXT_SCHEMA_PATH",
    "FIXTURES_DIR",
    "ANDROID_FIXTURES_DIR",
    "dump_contract",
    "load_contract",
    "dump_openapi",
    "load_openapi",
]
