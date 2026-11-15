# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for the TLS trust policy SSOT (``hsync_common.protocol.tls_trust``).

The decision is pure so the Python client, the desktop subprocess contract and
the Android mirror share one provably consistent rule set (validated against the
shared ``p2p-rendezvous-trust-scenarios`` fixture).
"""

import pytest

from hsync_common.protocol.tls_trust import (
    DEFAULT_SELF_SIGNED_POLICY,
    PINNING_POLICIES,
    TrustAction,
    TrustPolicy,
    ensure_pinning_policy,
    evaluate_tls_trust,
    resolve_auto_policy,
    resolve_self_signed_policy,
    resolve_trust_policy,
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


class TestResolveTrustPolicy:
    """The flag/env precedence shared by every pinned transport."""

    @pytest.mark.parametrize(
        ("policy", "fingerprints", "tofu", "verify_ssl", "env_default", "expected"),
        [
            # --insecure wins over every other signal.
            ("strict", (_FP_A,), True, False, "accept-new", TrustPolicy.none),
            # An explicit pin beats TOFU and the flag/env value.
            ("ask", (_FP_A,), True, True, "accept-new", TrustPolicy.strict),
            # TOFU beats the flag/env value.
            ("strict", (), True, True, "ask", TrustPolicy.accept_new),
            # The flag beats the env default.
            ("strict", (), False, True, "accept-new", TrustPolicy.strict),
            # The env default applies when the flag is absent.
            (None, (), False, True, "accept-new", TrustPolicy.accept_new),
            # Nothing selects a policy: the transport fallback wins.
            (None, (), False, True, None, TrustPolicy.ask),
        ],
    )
    def test_precedence(self, policy, fingerprints, tofu, verify_ssl, env_default, expected):
        assert (
            resolve_trust_policy(policy, fingerprints, tofu, verify_ssl, env_default=env_default)
            is expected
        )

    def test_fallback_is_transport_specific(self):
        assert resolve_trust_policy(None, (), False, True) is TrustPolicy.ask
        assert (
            resolve_trust_policy(None, (), False, True, fallback=TrustPolicy.chain)
            is TrustPolicy.chain
        )

    def test_unknown_policy_name_is_rejected(self):
        # Silently falling back would disable an operator's explicit request.
        with pytest.raises(ValueError):
            resolve_trust_policy("bogus", (), False, True)
        with pytest.raises(ValueError):
            resolve_trust_policy(None, (), False, True, env_default="bogus")


def test_default_self_signed_policy_is_ask():
    assert DEFAULT_SELF_SIGNED_POLICY is TrustPolicy.ask
    assert DEFAULT_SELF_SIGNED_POLICY in PINNING_POLICIES


class TestResolveAutoPolicy:
    """The ``auto`` meta-policy resolves as pin > chain > TOFU."""

    def test_non_auto_policies_pass_through(self):
        for policy in (
            TrustPolicy.chain,
            TrustPolicy.ask,
            TrustPolicy.accept_new,
            TrustPolicy.strict,
            TrustPolicy.none,
        ):
            assert resolve_auto_policy(policy, None, chain_trusted=True) is policy

    def test_stored_pin_wins_over_chain(self):
        assert (
            resolve_auto_policy(TrustPolicy.auto, _FP_A, chain_trusted=True) is TrustPolicy.strict
        )

    def test_stored_malformed_pin_still_wins(self):
        # Fail closed: a present-but-malformed pin must not silently fall back to
        # chain/TOFU; ``evaluate_tls_trust(strict, ...)`` refuses it.
        assert (
            resolve_auto_policy(TrustPolicy.auto, "nope", chain_trusted=True) is TrustPolicy.strict
        )

    def test_chain_when_ca_validated(self):
        assert resolve_auto_policy(TrustPolicy.auto, None, chain_trusted=True) is TrustPolicy.chain

    def test_tofu_when_no_chain(self):
        assert (
            resolve_auto_policy(TrustPolicy.auto, None, chain_trusted=False)
            is TrustPolicy.accept_new
        )

    def test_self_signed_transport_pins_or_refuses(self):
        # The rendezvous/P2P transports pass chain_trusted=False.
        unknown = resolve_auto_policy(TrustPolicy.auto, None, chain_trusted=False)
        known = resolve_auto_policy(TrustPolicy.auto, _FP_A, chain_trusted=False)
        assert evaluate_tls_trust(unknown, None, _FP_A) is TrustAction.pin_and_proceed
        assert evaluate_tls_trust(known, _FP_A, _FP_A) is TrustAction.proceed
        assert evaluate_tls_trust(known, _FP_A, _FP_B) is TrustAction.refuse


def test_evaluate_tls_trust_rejects_unresolved_auto():
    # ``auto`` must be resolved first; silently proceeding would skip the
    # strongest available check.
    with pytest.raises(ValueError):
        evaluate_tls_trust(TrustPolicy.auto, None, _FP_A)


@pytest.mark.parametrize(
    "policy",
    [TrustPolicy.auto, TrustPolicy.ask, TrustPolicy.accept_new, TrustPolicy.strict],
)
def test_ensure_pinning_policy_accepts_pinning_policies(policy):
    assert ensure_pinning_policy(policy) is policy


@pytest.mark.parametrize("policy", [TrustPolicy.chain, TrustPolicy.none])
def test_ensure_pinning_policy_rejects_non_pinning_policies(policy):
    with pytest.raises(ValueError):
        ensure_pinning_policy(policy)


def test_resolve_self_signed_policy_defaults_to_ask():
    assert resolve_self_signed_policy(None) is TrustPolicy.ask


def test_resolve_self_signed_policy_precedence():
    assert resolve_self_signed_policy("strict", env_default="accept-new") is TrustPolicy.strict
    assert resolve_self_signed_policy(None, env_default="accept-new") is TrustPolicy.accept_new


@pytest.mark.parametrize("value", ["chain", "none", "bogus"])
def test_resolve_self_signed_policy_rejects_non_pinning_values(value):
    with pytest.raises(ValueError):
        resolve_self_signed_policy(value)
