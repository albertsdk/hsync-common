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
from hashlib import sha256
from typing import Any

from hsync_common.delta import find_matches, signatures_for_data
from hsync_common.models.delta import DeltaApplyMetadata, DeltaInstructions
from hsync_common.models.event import Event, EventName
from hsync_common.models.file import File
from hsync_common.models.tombstone import TombstoneEntry, tombstone_merge_decision
from hsync_common.models.version import VersionInfo, resolve_three_way

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
        cid="TestClientX1234567890",
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
            version=VersionInfo(
                vclock={"TestClientX1234567890": 3},
                version_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
                origin_cid="TestClientX1234567890",
                ts=_FIXTURE_MTIME,
                corrected_mtime=_FIXTURE_MTIME,
            ),
        ),
    )
    return dict(event.to_dict())


def _lan_txt_record() -> dict[str, Any]:
    """Sample mDNS/TXT record: all values are strings (mDNS encoding)."""
    return {
        "cid": "TestClientX1234567890",
        "bucket": "bucket-1",
        "version": FIXTURE_APP_VERSION,
        "protocol": PROTOCOL_VERSION_LAN,
        "startup_time": "1700000000.5",
        "sync_direction": "bidirectional",
        "compression": "true",
        "delta": "true",
        "vector_clocks": "true",
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


# Deterministic delta-transfer example shared by the three delta fixtures.
# The base is 1 MB of pseudo-random bytes (fixed LCG seed) with 4 KB blocks —
# the same shape documented by the wire examples — and the edit replaces the
# whole second block with constant bytes, so the resulting ops are exactly:
# copy(block 0) + data(4096 B) + copy(blocks 2..255). Everything is computed
# by the real matching engine, never hand-written: the ops are byte-accurate
# (their total length always equals ``new_size``) and the SHA-256 digests are
# the real ones, so the Android parity test pins an actually-valid wire shape.
_DELTA_BLOCK = 4096
_DELTA_BASE_SIZE = 1024 * 1024  # 1 MB -> 256 blocks


def _delta_base_bytes() -> bytes:
    """Deterministic 1 MB pseudo-random base payload (fixed-seed LCG)."""
    state = 0xA5A5_5A5A
    out = bytearray(_DELTA_BASE_SIZE)
    for i in range(_DELTA_BASE_SIZE):
        state = (state * 1103515245 + 12345) & 0x7FFF_FFFF
        out[i] = (state >> 16) & 0xFF
    return bytes(out)


def _delta_example():
    """Compute the canonical base/new pair and its engine-produced delta.

    Returns ``(base, new, signatures, ops, literal_data)`` for the shared
    1 MB / 4 KB example.
    """
    base = _delta_base_bytes()
    new = bytearray(base)
    new[_DELTA_BLOCK : 2 * _DELTA_BLOCK] = b"\x5a" * _DELTA_BLOCK  # edit whole block 1
    signatures = signatures_for_data(base, _DELTA_BLOCK)
    ops, literal_data = find_matches(bytes(new), signatures, _DELTA_BLOCK)
    return base, bytes(new), signatures, ops, literal_data


def _delta_signatures() -> dict[str, Any]:
    """Block signatures for the canonical 1 MB / 4 KB delta example.

    Demonstrates the wire shape of a GET /delta/signatures response. Generated
    by the matching engine for the full 256-block base (no omitted blocks).
    """
    base, _, signatures, _, _ = _delta_example()
    return {
        "description": (
            "Block signatures for the canonical 1 MB base with 4 KB blocks "
            "(256 blocks), generated by the shared delta engine"
        ),
        "file_size": len(base),
        "block_size": _DELTA_BLOCK,
        "file_sha256": sha256(base).hexdigest(),
        "signatures": [s.to_dict() for s in signatures],
    }


def _delta_instructions() -> dict[str, Any]:
    """Delta instructions for rebuilding the edited file from base + literals.

    Demonstrates the wire shape of a delta response. Generated by the matching
    engine so ``sum(op.length) == new_size`` always holds: copy(block 0)
    + data(4096 literal bytes) + copy(blocks 2..255).
    """
    base, new, _, ops, literal_data = _delta_example()
    return dict(
        DeltaInstructions(
            new_sha256=sha256(new).hexdigest(),
            new_size=len(new),
            block_size=_DELTA_BLOCK,
            ops=tuple(ops),
            base_sha256=sha256(base).hexdigest(),
        ).to_dict(),
        literal_size=len(literal_data),
        description=(
            "Delta instructions to rebuild the edited 1 MB file from the base "
            "plus a 4096-byte literal block (edit inside block 1)"
        ),
    )


def _delta_apply_metadata() -> dict[str, Any]:
    """Metadata for POST /delta/apply, generated from the shared wire model.

    Demonstrates the multipart metadata part. Built from :class:`DeltaApplyMetadata`
    so the keys are exactly the model contract (no hand-added fields).
    """
    base, new, _, ops, _ = _delta_example()
    return dict(
        DeltaApplyMetadata(
            cid="TestClientX1234567890",
            base_sha256=sha256(base).hexdigest(),
            new_sha256=sha256(new).hexdigest(),
            new_size=len(new),
            block_size=_DELTA_BLOCK,
            compressed=False,
            ops=tuple(ops),
            mtime=1706457600.123456,
            permissions="644",
        ).to_dict(),
        description="Example metadata for POST /delta/apply (upload delta)",
    )


# Cross-language causal-resolution scenarios. Each lists the inputs to
# ``resolve_three_way`` — hashes, clocks and the ADR-0023 corrected mtimes —
# and the expected :class:`SyncDecision`, *computed* from the shared algorithm
# (never hand-written). Both the Python client tests and the Android parity
# test replay these exact inputs and must reach the same outcome, so a
# divergence fails a test instead of causing a split-brain.
_VC = "TestClientA1234567890"  # 21-char cid (is_valid_cid-compliant)
_VC_B = "TestClientB1234567890"
_CAUSAL_SCENARIOS: tuple[
    tuple[
        str,
        str | None,
        dict[str, int] | None,
        str | None,
        dict[str, int] | None,
        str | None,
        int,
        int,
    ],
    ...,
] = (
    # name, local_hash, local_vclock, remote_hash, remote_vclock, base_hash,
    # local_corrected_mtime, remote_corrected_mtime
    ("identical-content-in-sync", "h", {_VC: 1}, "h", {_VC: 1}, "h", 0, 0),
    ("both-absent-in-sync", None, None, None, None, "base", 0, 0),
    ("local-at-base-downloads", "base", {_VC: 1}, "remote", {_VC: 2}, "base", 0, 0),
    ("remote-at-base-uploads", "local", {_VC: 2}, "base", {_VC: 1}, "base", 0, 0),
    ("remote-dominates-downloads", "h1", {_VC: 1}, "h2", {_VC: 2}, "h0", 0, 0),
    ("local-dominates-uploads", "h2", {_VC: 2}, "h1", {_VC: 1}, "h0", 0, 0),
    # Hash-fallback tie-breaks (at least one corrected mtime unknown ⇒ 0).
    ("concurrent-local-wins-tie-break", "zzz", {_VC: 2}, "aaa", {_VC_B: 2}, "base", 0, 0),
    ("concurrent-remote-wins-tie-break", "aaa", {_VC: 2}, "zzz", {_VC_B: 2}, "base", 0, 0),
    ("no-base-no-clocks-local-wins", "zzz", None, "aaa", None, None, 0, 0),
    ("no-base-no-clocks-remote-wins", "aaa", None, "zzz", None, None, 0, 0),
    ("no-base-remote-has-clock-dominates", "h1", None, "h2", {_VC_B: 1}, None, 0, 0),
    ("no-base-local-has-clock-dominates", "h2", {_VC: 1}, "h1", None, None, 0, 0),
    ("equal-clocks-different-hashes-concurrent", "zzz", {_VC: 1}, "aaa", {_VC: 1}, "base", 0, 0),
    ("relay-dominates-no-false-conflict", "h0", {_VC: 3}, "h1", {_VC: 3, _VC_B: 1}, "h0", 0, 0),
    # Corrected-mtime tie-breaks (ADR-0023): the newer corrected mtime wins and
    # beats any hash order — the hash fallback is bypassed when both are known.
    ("corrected-mtime-local-newer-wins", "aaa", {_VC: 2}, "zzz", {_VC_B: 2}, "base", 200, 100),
    ("corrected-mtime-remote-newer-wins", "zzz", {_VC: 2}, "aaa", {_VC_B: 2}, "base", 100, 200),
    (
        "corrected-mtime-equal-falls-back-to-hash",
        "zzz",
        {_VC: 2},
        "aaa",
        {_VC_B: 2},
        "base",
        150,
        150,
    ),
    (
        "corrected-mtime-local-only-falls-back-to-hash",
        "zzz",
        {_VC: 2},
        "aaa",
        {_VC_B: 2},
        "base",
        100,
        0,
    ),
    (
        "corrected-mtime-remote-only-falls-back-to-hash",
        "aaa",
        {_VC: 2},
        "zzz",
        {_VC_B: 2},
        "base",
        0,
        100,
    ),
)


def _causal_resolution_scenarios() -> dict[str, Any]:
    """Serialized causal-resolution scenarios with expectations computed from the source."""
    return {
        "scenarios": [
            {
                "name": name,
                "local_hash": local_hash,
                "local_vclock": local_vclock,
                "remote_hash": remote_hash,
                "remote_vclock": remote_vclock,
                "base_hash": base_hash,
                "local_corrected_mtime": local_corrected,
                "remote_corrected_mtime": remote_corrected,
                "expected_decision": resolve_three_way(
                    local_hash,
                    local_vclock,
                    remote_hash,
                    remote_vclock,
                    base_hash,
                    local_corrected_mtime=local_corrected,
                    remote_corrected_mtime=remote_corrected,
                ).value,
            }
            for (
                name,
                local_hash,
                local_vclock,
                remote_hash,
                remote_vclock,
                base_hash,
                local_corrected,
                remote_corrected,
            ) in _CAUSAL_SCENARIOS
        ]
    }


# Cross-language causal tombstone-merge scenarios. Each lists a stored marker
# (or ``None``) and an incoming remote marker, with the expected decision
# (``adopt`` | ``keep``) *computed from the shared algorithm* via
# ``tombstone_merge_decision`` — never hand-written. The Android parity test
# replays these exact inputs and must reach the same outcome (ADR-0003).
_TVC = "TestClientA1234567890"
_TVC_B = "TestClientB1234567890"
_TOMB_TS = 1_700_000_000  # stable informational timestamp (never decides)


def _tomb_entry(
    sha: str,
    vclock: dict[str, int],
    version_id: str = "v1",
    origin_cid: str | None = _TVC,
) -> TombstoneEntry:
    return TombstoneEntry(
        sha256=sha, version_id=version_id, origin_cid=origin_cid, ts=_TOMB_TS, vclock=vclock
    )


_TOMBSTONE_SCENARIOS: tuple[tuple[str, TombstoneEntry | None, TombstoneEntry], ...] = (
    ("no-existing-adopts", None, _tomb_entry("aaa", {_TVC: 1})),
    (
        "existing-dominates-keeps",
        _tomb_entry("aaa", {_TVC: 2, _TVC_B: 1}),
        _tomb_entry("bbb", {_TVC: 1}),
    ),
    (
        "incoming-dominates-adopts",
        _tomb_entry("aaa", {_TVC: 1}),
        _tomb_entry("bbb", {_TVC: 2, _TVC_B: 1}),
    ),
    (
        "concurrent-incoming-wins-sha",
        _tomb_entry("aaa", {_TVC: 2}),
        _tomb_entry("zzz", {_TVC_B: 2}),
    ),
    (
        "concurrent-existing-wins-sha",
        _tomb_entry("zzz", {_TVC: 2}),
        _tomb_entry("aaa", {_TVC_B: 2}),
    ),
    (
        "equal-clock-anomaly-incoming-wins-sha",
        _tomb_entry("aaa", {_TVC: 1}),
        _tomb_entry("zzz", {_TVC: 1}, version_id="v1", origin_cid=_TVC_B),
    ),
    (
        "equal-clock-anomaly-existing-wins-sha",
        _tomb_entry("zzz", {_TVC: 1}),
        _tomb_entry("aaa", {_TVC: 1}, version_id="v1", origin_cid=_TVC_B),
    ),
)


def _causal_tombstone_scenarios() -> dict[str, Any]:
    """Serialized causal tombstone-merge scenarios with computed expectations."""
    return {
        "scenarios": [
            {
                "name": name,
                "existing": None if existing is None else dict(existing),
                "incoming": dict(incoming),
                "expected_decision": tombstone_merge_decision(existing, incoming),
            }
            for name, existing, incoming in _TOMBSTONE_SCENARIOS
        ]
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
        "causal-resolution-scenarios": _causal_resolution_scenarios(),
        "causal-tombstone-scenarios": _causal_tombstone_scenarios(),
        "delta-signatures": _delta_signatures(),
        "delta-instructions": _delta_instructions(),
        "delta-apply-metadata": _delta_apply_metadata(),
    }
