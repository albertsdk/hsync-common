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

from dataclasses import asdict
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
from .lan import ElectionCandidate, elect_master
from .pairing import (
    evaluate_pin,
    lan_write_requires_key,
    requires_pairing_confirmation,
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
            permissions="644",
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
        "delta": "true",
    }


# Cross-language master-election scenarios. Each scenario lists its candidates
# and the expected winning ``cid``; the expectation is *computed* from the shared
# algorithm (never hand-written), so the committed snapshot can only encode what
# hsync_common.protocol.lan actually decides. Both the Python client tests and the
# Android parity test replay these exact inputs and must reach the same outcome.
_ELECTION_SCENARIOS: tuple[tuple[str, tuple[ElectionCandidate, ...]], ...] = (
    (
        "incumbent-server-ready-wins-over-force-master",
        (
            ElectionCandidate(cid="local", force_master=True, startup_time=10.0),
            ElectionCandidate(cid="incumbent", startup_time=200.0, server_ready=True),
        ),
    ),
    (
        "force-master-wins-over-plain-peer",
        (
            ElectionCandidate(cid="plain", startup_time=50.0),
            ElectionCandidate(cid="forced", force_master=True, startup_time=300.0),
        ),
    ),
    (
        "bidirectional-preferred-over-upload-only",
        (
            ElectionCandidate(cid="aaa", startup_time=100.0, sync_direction="upload-only"),
            ElectionCandidate(cid="bbb", startup_time=100.0),
        ),
    ),
    (
        "earliest-startup-wins",
        (
            ElectionCandidate(cid="late", startup_time=200.0),
            ElectionCandidate(cid="early", startup_time=100.0),
        ),
    ),
    (
        "lowest-cid-breaks-tie",
        (
            ElectionCandidate(cid="zzz", startup_time=100.0),
            ElectionCandidate(cid="aaa", startup_time=100.0),
        ),
    ),
    (
        "no-peer-server-ready-still-elects",
        (
            ElectionCandidate(cid="early", startup_time=100.0),
            ElectionCandidate(cid="later", startup_time=200.0),
        ),
    ),
    (
        "never-master-peer-excluded",
        (
            ElectionCandidate(cid="never", startup_time=100.0, never_master=True),
            ElectionCandidate(cid="eligible", startup_time=200.0),
        ),
    ),
    (
        "all-never-master-no-master",
        (
            ElectionCandidate(cid="a", startup_time=100.0, never_master=True),
            ElectionCandidate(cid="b", startup_time=200.0, never_master=True),
        ),
    ),
)


def _election_scenarios() -> dict[str, Any]:
    """Serialized election scenarios with expectations computed from the source."""
    return {
        "scenarios": [
            {
                "name": name,
                "candidates": [asdict(c) for c in candidates],
                "expected_master": elect_master(candidates),
            }
            for name, candidates in _ELECTION_SCENARIOS
        ]
    }


# Cross-language TOFU pin-evaluation scenarios. Each lists the stored/observed
# fingerprints and the expected :class:`PinDecision`, *computed* from the shared
# ``evaluate_pin`` (never hand-written). Inputs deliberately mix ``:``/case forms
# so the parity test also covers fingerprint normalization on both sides. LAN
# transport is HTTPS-only, so a master always presents a fingerprint; a missing
# one is a contract violation (``evaluate_pin`` raises) rather than a scenario.
_PIN_SCENARIOS: tuple[tuple[str, str | None, str], ...] = (
    ("first-sighting-is-trusted", None, "AA:BB:CC:DD"),
    ("matching-pin-ignoring-format", "aabbccdd", "AA:BB:CC:DD"),
    ("changed-pin-is-refused", "aabbccdd", "ee:ff:00:11"),
)

# Cross-language LAN write-policy scenarios. ``expected_requires_key`` is computed
# from the shared ``lan_write_requires_key`` so Python and Android agree on when
# an unattended, write-capable client must present ``HSYNC_LAN_KEY``.
_WRITE_POLICY_SCENARIOS: tuple[tuple[str, str, bool], ...] = (
    ("non-interactive-bidirectional-requires-key", "bidirectional", False),
    ("non-interactive-upload-only-requires-key", "upload-only", False),
    ("non-interactive-download-only-no-key", "download-only", False),
    ("interactive-bidirectional-no-key", "bidirectional", True),
    ("interactive-upload-only-no-key", "upload-only", True),
)

# Cross-language explicit-pairing scenarios. Each lists the stored/observed
# fingerprints and whether strict pairing is enabled; the resulting
# ``PinDecision`` and ``expected_requires_pairing`` are *computed* from the shared
# ``evaluate_pin``/``requires_pairing_confirmation`` so Python and Android agree on
# when a first-seen master must be confirmed out of band before it is trusted.
_PAIRING_SCENARIOS: tuple[tuple[str, str | None, str, bool], ...] = (
    ("first-sighting-strict-needs-pairing", None, "AA:BB:CC:DD", True),
    ("first-sighting-lax-auto-trust", None, "AA:BB:CC:DD", False),
    ("matched-never-needs-pairing", "aabbccdd", "AA:BB:CC:DD", True),
    ("changed-never-needs-pairing", "aabbccdd", "ee:ff:00:11", True),
)


def _pairing_scenarios() -> dict[str, Any]:
    """Serialized pairing scenarios with expectations computed from the source."""
    return {
        "pin_scenarios": [
            {
                "name": name,
                "stored": stored,
                "observed": observed,
                "expected_decision": evaluate_pin(stored, observed),
            }
            for name, stored, observed in _PIN_SCENARIOS
        ],
        "write_policy_scenarios": [
            {
                "name": name,
                "sync_direction": direction,
                "interactive": interactive,
                "expected_requires_key": lan_write_requires_key(direction, interactive=interactive),
            }
            for name, direction, interactive in _WRITE_POLICY_SCENARIOS
        ],
        "pairing_scenarios": [
            {
                "name": name,
                "decision": evaluate_pin(stored, observed),
                "require_pairing": require_pairing,
                "expected_requires_pairing": requires_pairing_confirmation(
                    evaluate_pin(stored, observed), require_pairing=require_pairing
                ),
            }
            for name, stored, observed, require_pairing in _PAIRING_SCENARIOS
        ],
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
        "lan-election-scenarios": _election_scenarios(),
        "lan-pairing-scenarios": _pairing_scenarios(),
    }
