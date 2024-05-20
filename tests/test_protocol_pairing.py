# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for the canonical LAN security policy (P1 §5).

These verify the single source of truth in ``hsync_common.protocol.pairing``:
the TOFU pin classification and the LAN-key write policy. Both are pure, so the
Python client and (later) the Android client can share one provably consistent
trust decision instead of each re-implementing it.
"""

from hsync_common.protocol.pairing import (
    SYNC_DIRECTION_DOWNLOAD_ONLY,
    SYNC_DIRECTION_UPLOAD_ONLY,
    PinDecision,
    evaluate_pin,
    is_write_direction,
    lan_write_requires_key,
    normalize_fingerprint,
    requires_pairing_confirmation,
)


class TestNormalizeFingerprint:
    def test_blank_and_none_are_none(self):
        assert normalize_fingerprint(None) is None
        assert normalize_fingerprint("") is None
        assert normalize_fingerprint("   ") is None

    def test_lowercases_and_strips_separators(self):
        assert normalize_fingerprint("AA:BB:CC") == "aabbcc"
        assert normalize_fingerprint("  Aa Bb ") == "aabb"

    def test_colon_and_plain_forms_are_equal(self):
        assert normalize_fingerprint("DE:AD:BE:EF") == normalize_fingerprint("deadbeef")


class TestEvaluatePin:
    def test_no_observed_fingerprint_is_no_fingerprint(self):
        assert evaluate_pin("abc", None) is PinDecision.no_fingerprint
        assert evaluate_pin(None, "") is PinDecision.no_fingerprint

    def test_first_sighting_is_trusted(self):
        assert evaluate_pin(None, "abc123") is PinDecision.trusted

    def test_same_fingerprint_matches_case_insensitively(self):
        assert evaluate_pin("ABC123", "abc123") is PinDecision.matched
        assert evaluate_pin("aa:bb", "AABB") is PinDecision.matched

    def test_different_fingerprint_is_changed(self):
        assert evaluate_pin("abc123", "def456") is PinDecision.changed


class TestRequiresPairingConfirmation:
    def test_first_sighting_needs_confirmation_under_strict_pairing(self):
        assert requires_pairing_confirmation(PinDecision.trusted, require_pairing=True) is True

    def test_first_sighting_is_auto_trusted_without_strict_pairing(self):
        assert requires_pairing_confirmation(PinDecision.trusted, require_pairing=False) is False

    def test_other_decisions_never_need_pairing(self):
        for decision in (
            PinDecision.matched,
            PinDecision.changed,
            PinDecision.no_fingerprint,
        ):
            assert requires_pairing_confirmation(decision, require_pairing=True) is False


class TestWritePolicy:
    def test_bidirectional_and_upload_only_are_writes(self):
        assert is_write_direction("bidirectional") is True
        assert is_write_direction(SYNC_DIRECTION_UPLOAD_ONLY) is True

    def test_download_only_is_not_a_write(self):
        assert is_write_direction(SYNC_DIRECTION_DOWNLOAD_ONLY) is False

    def test_key_required_only_when_non_interactive_and_writing(self):
        assert lan_write_requires_key("bidirectional", interactive=False) is True
        assert lan_write_requires_key(SYNC_DIRECTION_UPLOAD_ONLY, interactive=False) is True

    def test_interactive_never_requires_key(self):
        assert lan_write_requires_key("bidirectional", interactive=True) is False

    def test_download_only_never_requires_key(self):
        assert lan_write_requires_key(SYNC_DIRECTION_DOWNLOAD_ONLY, interactive=False) is False
