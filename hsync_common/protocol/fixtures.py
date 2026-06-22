# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Golden protocol fixtures shared across every HSYNC component (P0-A, Fase 4).

These are canonical, deterministic examples of each on-the-wire message, built
*from the Python source of truth* — the handshake builders and the shared
event/file models — never hand-written. They are committed under
``protocol/fixtures/`` and consumed as cross-language test inputs: the Android
contract test asserts that its own builders/DTOs reproduce the very same bytes,
so a drift on either side fails a test instead of breaking a device in the field.

Regenerate the committed snapshots with ``scripts/export_protocol_schemas.py``;
the matching drift-check test guards them against silent divergence.
"""

from __future__ import annotations

from typing import Any

from hsync_common.models.event import Event, EventName
from hsync_common.models.file import File

from .handshake import (
    PROTOCOL_VERSION_LAN,
    Capability,
    build_ws_auth_error,
    build_ws_auth_ok,
    build_ws_auth_request,
)

__all__ = ["FIXTURE_TOKEN", "FIXTURE_APP_VERSION", "build_fixtures"]

# Deterministic placeholders used across every fixture so the committed bytes
# stay stable. The token is an obvious non-secret sample, never a real value.
FIXTURE_TOKEN = "example-api-token"
FIXTURE_APP_VERSION = "1.0.0"

# Fixed capability advertised by the sample client/server (kept minimal so the
# fixture exercises a non-empty list without coupling to the full registry).
_FIXTURE_CAPS = frozenset({Capability.compression})

# Stable timestamps for the sample file event (Unix seconds, UTC).
_FIXTURE_CTIME = 1_700_000_000
_FIXTURE_MTIME = 1_700_000_500


def _file_event() -> dict[str, Any]:
    """Serialized ``added`` file event built from the shared Event/File models."""
    event = Event(
        cid="client-1",
        localpath="/data",
        bucket="bucket-1",
        name=EventName.added,
        src=File(
            filepath="/data/docs/report.txt",
            ctime=_FIXTURE_CTIME,
            mtime=_FIXTURE_MTIME,
            size=42,
            sha256sum="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            permissions="-rw-r--r--",
        ),
    )
    return dict(event.to_dict())


def _lan_txt_record() -> dict[str, Any]:
    """Sample mDNS/TXT record: all values are strings (mDNS encoding)."""
    return {
        "cid": "client-1",
        "bucket": "bucket-1",
        "version": FIXTURE_APP_VERSION,
        "protocol": PROTOCOL_VERSION_LAN,
        "startup_time": "1700000000.5",
        "sync_direction": "bidirectional",
        "compression": "true",
    }


def build_fixtures() -> dict[str, dict[str, Any]]:
    """Build every golden fixture, keyed by its snapshot file stem.

    The keys map 1:1 to the committed ``protocol/fixtures/<key>.json`` files and
    to the resources copied into the Android contract test.
    """
    return {
        "ws-auth-request": dict(
            build_ws_auth_request(
                token=FIXTURE_TOKEN,
                app_version=FIXTURE_APP_VERSION,
                capabilities=_FIXTURE_CAPS,
            )
        ),
        "ws-auth-ok": dict(
            build_ws_auth_ok(app_version=FIXTURE_APP_VERSION, capabilities=_FIXTURE_CAPS)
        ),
        "ws-auth-error": dict(
            build_ws_auth_error(error="protocol_incompatible", client_protocol_version="ws/0")
        ),
        "ws-ping": {"type": "ping"},
        "ws-pong": {"type": "pong"},
        "ws-file-event": _file_event(),
        "lan-txt-record": _lan_txt_record(),
    }
