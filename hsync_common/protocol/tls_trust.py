# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""TLS trust policy (SSH ``known_hosts``-style), language-neutral.

Three transports authenticate with a certificate whose fingerprint may be pinned:
the ``rdv/1`` node (self-signed by contract), the P2P master (self-signed, mDNS),
and the sync server (built-in self-signed TLS or a reverse proxy with a public CA).
This module owns the *policy* that decides what to do with an observed fingerprint,
mirroring the SSH ``StrictHostKeyChecking`` model, plus the ``chain`` policy for the
server case where standard CA validation is the anchor:

``chain``
    Standard certificate-chain validation (public CA or ``--ca-cert`` anchor); no
    fingerprint pinning. The default for the sync server.
``ask``
    Prompt on an unknown host and pin it on acceptance; refuse a changed one.
    The default for a self-signed node (and fail-closed without a terminal).
``accept_new``
    Silently pin a first sighting (Trust-On-First-Use); refuse a changed one.
``strict``
    Require an explicit pin; refuse an unknown or changed host.
``none``
    No verification (tests/loopback only). Same as ``--insecure``.

Persistence (the known-hosts / known-peers stores) and I/O live in the consumers,
never here: :func:`evaluate_tls_trust` is pure so the Python client, the desktop
subprocess contract and the Android mirror cannot drift.

Consumers: ``hsync-client`` (rendezvous connect path, P2P master pin, server connect
path), the Android mirror (``RendezvousTrust``, validated against the shared
``p2p-rendezvous-trust-scenarios`` fixture), and the shared fixtures/parity tests.
"""

from __future__ import annotations

from enum import StrEnum

from .pairing import parse_fingerprint

__all__ = [
    "DEFAULT_SELF_SIGNED_POLICY",
    "PINNING_POLICIES",
    "TrustAction",
    "TrustPolicy",
    "ensure_pinning_policy",
    "evaluate_tls_trust",
    "resolve_self_signed_policy",
    "resolve_trust_policy",
]


class TrustPolicy(StrEnum):
    """How an observed certificate fingerprint is evaluated (SSH-like)."""

    chain = "chain"  # standard CA chain validation; no pinning (server default)
    ask = "ask"  # prompt on an unknown host, refuse a changed one
    accept_new = "accept-new"  # pin a first sighting silently, refuse a changed one
    strict = "strict"  # require an explicit pin; refuse unknown or changed
    none = "none"  # no verification (tests/loopback only)


# The default for a self-signed transport (P2P master, rendezvous): confirm an
# unknown fingerprint on a terminal and fail closed when there is no terminal.
DEFAULT_SELF_SIGNED_POLICY = TrustPolicy.ask

# Policies that actually pin a self-signed transport. ``chain``/``none`` never
# pin, so they cannot express trust for a P2P master or a rendezvous.
PINNING_POLICIES: tuple[TrustPolicy, ...] = (
    TrustPolicy.ask,
    TrustPolicy.accept_new,
    TrustPolicy.strict,
)


class TrustAction(StrEnum):
    """What the caller must do after evaluating a policy against a fingerprint."""

    proceed = "proceed"  # the host may be contacted
    pin_and_proceed = "pin-and-proceed"  # store the fingerprint, then contact the host
    prompt = "prompt"  # ask the user; store on acceptance, refuse on rejection
    refuse = "refuse"  # the host must not be contacted (unknown/strict or changed)


def evaluate_tls_trust(
    policy: TrustPolicy,
    stored_fp: str | None,
    observed_fp: str | None,
) -> TrustAction:
    """Classify an observed certificate fingerprint under *policy*.

    Args:
        policy: The active :class:`TrustPolicy`.
        stored_fp: The fingerprint already pinned for this identity, or ``None``
            when the host has never been seen.
        observed_fp: The fingerprint the host presented now. A missing/invalid
            value can never be trusted (a changed/absent fingerprint is refused
            unless the policy disables fingerprint verification entirely).

    Returns:
        The :class:`TrustAction` the caller must carry out. ``chain`` (standard CA
        validation) and ``none`` always proceed — the caller performs (or skips)
        chain validation accordingly and never pins. Otherwise an unknown host
        follows the policy and a changed fingerprint is always refused.

    Consumers: ``hsync-client`` (rendezvous/P2P/server connect paths) and the Android
    mirror, both fed by the shared ``p2p-rendezvous-trust-scenarios`` fixture.
    """
    if policy is TrustPolicy.chain or policy is TrustPolicy.none:
        return TrustAction.proceed

    # Both sides must be full SHA-256 digests: a malformed value is never trusted
    # (matching the Android mirror's ``canonicalFingerprint``).
    observed = parse_fingerprint(observed_fp)
    if observed is None:
        # No usable fingerprint to pin or compare: never trust it.
        return TrustAction.refuse

    stored = parse_fingerprint(stored_fp)
    if stored is None:
        if policy is TrustPolicy.accept_new:
            return TrustAction.pin_and_proceed
        if policy is TrustPolicy.ask:
            return TrustAction.prompt
        return TrustAction.refuse

    if observed == stored:
        return TrustAction.proceed
    return TrustAction.refuse


def resolve_trust_policy(
    policy: str | None,
    fingerprints: tuple[str, ...],
    tofu: bool,
    verify_ssl: bool,
    *,
    env_default: str | None = None,
    fallback: TrustPolicy = DEFAULT_SELF_SIGNED_POLICY,
) -> TrustPolicy:
    """Resolve the effective :class:`TrustPolicy` from CLI flags and the environment.

    One precedence for every pinned transport (rendezvous, P2P master, sync server),
    so the transports cannot drift: ``--insecure`` (``none``) > an explicit
    ``--*-fingerprint`` pin (``strict``) > ``--*-tofu`` (``accept-new``) > the
    ``--*-trust`` flag > the ``HSYNC_*_TRUST`` env default > *fallback*.

    Args:
        policy: The ``--*-trust`` flag value, if given.
        fingerprints: Explicit pins from ``--*-fingerprint``.
        tofu: Whether Trust-On-First-Use was requested.
        verify_ssl: ``False`` for ``--insecure``, which disables pinning entirely.
        env_default: Policy supplied by the environment (``HSYNC_*_TRUST``).
        fallback: Policy when neither the flag nor the env selects one:
            ``ask`` for a self-signed transport, ``chain`` for the sync server.

    Raises:
        ValueError: *policy* or *env_default* is not a :class:`TrustPolicy` member.

    Consumers: ``hsync-client`` (``server_trust.resolve_server_trust`` and
    ``main_logic._resolve_rendezvous_trust``); the Android mirror resolves defaults
    from the shared fixtures instead of this flag/env helper.
    """
    if not verify_ssl:
        return TrustPolicy.none
    if fingerprints:
        return TrustPolicy.strict
    if tofu:
        return TrustPolicy.accept_new
    explicit = policy or env_default
    return TrustPolicy(explicit) if explicit else fallback


def ensure_pinning_policy(policy: TrustPolicy) -> TrustPolicy:
    """Return *policy* when it pins a self-signed transport; raise otherwise.

    ``chain`` and ``none`` never pin, so they can never be the policy of a P2P
    master or a rendezvous: silently proceeding without a pin would disable the
    identity check entirely.

    Raises:
        ValueError: *policy* is not one of :data:`PINNING_POLICIES`.
    """
    if policy not in PINNING_POLICIES:
        allowed = ", ".join(value.value for value in PINNING_POLICIES)
        raise ValueError(
            f"policy '{policy.value}' does not pin a self-signed transport; use {allowed}"
        )
    return policy


def resolve_self_signed_policy(
    policy: str | None,
    *,
    env_default: str | None = None,
) -> TrustPolicy:
    """Resolve the policy of a self-signed transport (flag > env > default).

    One precedence for the P2P master and the rendezvous, so the two cannot drift:
    an explicit ``--*-trust`` value wins over the ``HSYNC_*_TRUST`` environment
    default, which wins over :data:`DEFAULT_SELF_SIGNED_POLICY`.

    Consumers: ``hsync-client`` (P2P master trust in ``main_logic.run_sync``).

    Raises:
        ValueError: the resolved policy does not pin (``chain``/``none``) or is
            not a :class:`TrustPolicy` member.
    """
    return ensure_pinning_policy(
        resolve_trust_policy(
            policy,
            (),
            False,
            True,
            env_default=env_default,
            fallback=DEFAULT_SELF_SIGNED_POLICY,
        )
    )
