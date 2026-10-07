# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for the canonical LAN security policy.

These verify the single source of truth in ``hsync_common.protocol.pairing``:
the TOFU pin classification and the LAN-key write policy. Both are pure, so the
Python client and (later) the Android client can share one provably consistent
trust decision instead of each re-implementing it.
"""

import pytest

from hsync_common.protocol.pairing import (
    SYNC_DIRECTION_DOWNLOAD_ONLY,
    SYNC_DIRECTION_UPLOAD_ONLY,
    FingerprintMismatch,
    PinDecision,
    evaluate_pin,
    fingerprint_matches,
    is_write_direction,
    normalize_fingerprint,
    p2p_write_requires_key,
    parse_fingerprint,
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
    def test_missing_observed_fingerprint_raises(self):
        # LAN transport is HTTPS-only: a master always presents a fingerprint, so
        # a missing/blank one is a contract violation rather than a decision.
        with pytest.raises(ValueError):
            evaluate_pin("abc", None)
        with pytest.raises(ValueError):
            evaluate_pin(None, "")

    def test_first_sighting_is_trusted(self):
        assert evaluate_pin(None, "abc123") is PinDecision.trusted

    def test_same_fingerprint_matches_case_insensitively(self):
        assert evaluate_pin("ABC123", "abc123") is PinDecision.matched
        assert evaluate_pin("aa:bb", "AABB") is PinDecision.matched

    def test_different_fingerprint_is_changed(self):
        assert evaluate_pin("abc123", "def456") is PinDecision.changed


_HEX64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


class TestParseFingerprint:
    def test_canonical_sha256_prefix(self):
        assert parse_fingerprint(f"sha256:{_HEX64}") == _HEX64

    def test_bare_hex(self):
        assert parse_fingerprint(_HEX64) == _HEX64

    def test_uppercase_and_colons_normalize(self):
        assert parse_fingerprint(_HEX64.upper()) == _HEX64
        assert parse_fingerprint(":".join(_HEX64[i : i + 2] for i in range(0, 64, 2))) == _HEX64

    def test_sha256_prefix_is_case_insensitive(self):
        assert parse_fingerprint(f"SHA256:{_HEX64}") == _HEX64

    def test_invalid_inputs_are_none(self):
        assert parse_fingerprint(None) is None
        assert parse_fingerprint("") is None
        assert parse_fingerprint("   ") is None
        assert parse_fingerprint("short") is None
        assert parse_fingerprint("z" * 64) is None  # non-hex
        assert parse_fingerprint("0" * 63) is None  # too short
        assert parse_fingerprint("0" * 65) is None  # too long


class TestFingerprintMatches:
    def test_matches_any_pin(self):
        assert fingerprint_matches(_HEX64, [_HEX64]) is True
        assert fingerprint_matches(_HEX64.upper(), [_HEX64]) is True

    def test_matches_one_of_several(self):
        assert fingerprint_matches(_HEX64, ["0" * 64, f"sha256:{_HEX64}"]) is True

    def test_no_match(self):
        assert fingerprint_matches(_HEX64, ["f" * 64]) is False
        assert fingerprint_matches(_HEX64, []) is False

    def test_missing_observed_never_matches(self):
        assert fingerprint_matches("", [_HEX64]) is False


def test_fingerprint_mismatch_is_an_exception():
    assert issubclass(FingerprintMismatch, Exception)


class TestRequiresPairingConfirmation:
    def test_first_sighting_needs_confirmation_under_strict_pairing(self):
        assert requires_pairing_confirmation(PinDecision.trusted, require_pairing=True) is True

    def test_first_sighting_is_auto_trusted_without_strict_pairing(self):
        assert requires_pairing_confirmation(PinDecision.trusted, require_pairing=False) is False

    def test_other_decisions_never_need_pairing(self):
        for decision in (
            PinDecision.matched,
            PinDecision.changed,
        ):
            assert requires_pairing_confirmation(decision, require_pairing=True) is False


class TestWritePolicy:
    def test_bidirectional_and_upload_only_are_writes(self):
        assert is_write_direction("bidirectional") is True
        assert is_write_direction(SYNC_DIRECTION_UPLOAD_ONLY) is True

    def test_download_only_is_not_a_write(self):
        assert is_write_direction(SYNC_DIRECTION_DOWNLOAD_ONLY) is False

    def test_key_required_by_default_when_writing(self):
        assert p2p_write_requires_key("bidirectional") is True
        assert p2p_write_requires_key(SYNC_DIRECTION_UPLOAD_ONLY) is True

    def test_explicit_opt_in_allows_no_key_write(self):
        assert (
            p2p_write_requires_key(
                "bidirectional",
                allow_unauthenticated_writes=True,
            )
            is False
        )
        assert (
            p2p_write_requires_key(
                SYNC_DIRECTION_UPLOAD_ONLY,
                allow_unauthenticated_writes=True,
            )
            is False
        )

    def test_download_only_never_requires_key(self):
        assert p2p_write_requires_key(SYNC_DIRECTION_DOWNLOAD_ONLY) is False
