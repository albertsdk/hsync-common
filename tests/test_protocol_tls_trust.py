# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for the TLS trust policy SSOT (``hsync_common.protocol.tls_trust``).

The decision is pure so the Python client, the desktop subprocess contract and
the Android mirror share one provably consistent rule set (validated against the
shared ``p2p-bootnode-trust-scenarios`` fixture).
"""

import pytest

from hsync_common.protocol.tls_trust import (
    TrustAction,
    TrustPolicy,
    evaluate_tls_trust,
)

_FP_A = "a" * 64
_FP_B = "b" * 64


class TestEvaluateTlsTrust:
    @pytest.mark.parametrize(
        ("policy", "stored", "observed", "expected"),
        [
            # ask: prompt on unknown, proceed on match, refuse on change
            (TrustPolicy.ask, None, _FP_A, TrustAction.prompt),
            (TrustPolicy.ask, _FP_A, _FP_A, TrustAction.proceed),
            (TrustPolicy.ask, _FP_A, _FP_B, TrustAction.refuse),
            # accept_new (TOFU): pin silently on unknown, refuse on change
            (TrustPolicy.accept_new, None, _FP_A, TrustAction.pin_and_proceed),
            (TrustPolicy.accept_new, _FP_A, _FP_A, TrustAction.proceed),
            (TrustPolicy.accept_new, _FP_A, _FP_B, TrustAction.refuse),
            # strict: require an explicit pin, refuse unknown or changed
            (TrustPolicy.strict, None, _FP_A, TrustAction.refuse),
            (TrustPolicy.strict, _FP_A, _FP_A, TrustAction.proceed),
            (TrustPolicy.strict, _FP_A, _FP_B, TrustAction.refuse),
            # none: no verification at all
            (TrustPolicy.none, None, _FP_A, TrustAction.proceed),
            (TrustPolicy.none, _FP_A, _FP_B, TrustAction.proceed),
            (TrustPolicy.none, _FP_A, None, TrustAction.proceed),
            # chain: standard CA validation, no pinning — always proceed
            (TrustPolicy.chain, None, _FP_A, TrustAction.proceed),
            (TrustPolicy.chain, _FP_A, _FP_B, TrustAction.proceed),
            (TrustPolicy.chain, _FP_A, None, TrustAction.proceed),
        ],
    )
    def test_policy_matrix(self, policy, stored, observed, expected):
        assert evaluate_tls_trust(policy, stored, observed) is expected

    def test_fingerprint_formats_are_normalised(self):
        # Colon/space-separated and bare hex compare equal on both sides.
        colon_separated = ":".join(["AA"] * 32)
        assert evaluate_tls_trust(TrustPolicy.ask, _FP_A, colon_separated) is (TrustAction.proceed)

    @pytest.mark.parametrize(
        "policy",
        [TrustPolicy.ask, TrustPolicy.accept_new, TrustPolicy.strict],
    )
    def test_missing_observed_is_never_trusted(self, policy):
        assert evaluate_tls_trust(policy, None, None) is TrustAction.refuse
        assert evaluate_tls_trust(policy, _FP_A, "") is TrustAction.refuse

    @pytest.mark.parametrize(
        "policy",
        [TrustPolicy.ask, TrustPolicy.accept_new, TrustPolicy.strict],
    )
    def test_malformed_observed_is_never_trusted(self, policy):
        # A non-64-hex value is not a fingerprint: refuse (matches the mirror).
        for malformed in ("not-a-fingerprint", "abcdef", "sha256:zz", "a" * 63):
            assert evaluate_tls_trust(policy, None, malformed) is TrustAction.refuse
            assert evaluate_tls_trust(policy, _FP_A, malformed) is TrustAction.refuse
