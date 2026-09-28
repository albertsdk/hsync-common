# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Bootnode TLS trust policy (SSH ``known_hosts``-style), language-neutral.

The ``boot/1`` node authenticates with a self-signed certificate, so the only
trust anchor is the certificate fingerprint the operator pins. This module owns
the *policy* that decides what to do with an observed fingerprint, mirroring the
SSH ``StrictHostKeyChecking`` model:

``ask``
    Prompt on an unknown node and pin it on acceptance; refuse a changed one.
    The default for interactive use (and fail-closed without a terminal).
``accept_new``
    Silently pin a first sighting (Trust-On-First-Use); refuse a changed one.
    Equivalent to the client's ``--bootnode-tofu``.
``strict``
    Require an explicit pin; refuse an unknown or changed node. Equivalent to
    ``--bootnode-fingerprint``.
``none``
    No verification (tests/loopback only). Equivalent to ``--insecure``.

Persistence (the ``bootnode_known_hosts.json`` store) and I/O live in the
consumers, never here: :func:`evaluate_bootnode_trust` is pure so the Python
client, the desktop subprocess contract and the Android mirror cannot drift.

Consumers: ``hsync-client`` (``boot_node_client``/discovery), the Android mirror
(``Pairing``-style object validated against the shared
``bootnode-trust-scenarios`` fixture), and the shared fixtures/parity tests.
"""

from __future__ import annotations

from enum import StrEnum

from .pairing import fingerprint_matches, normalize_fingerprint

__all__ = ["TrustAction", "TrustPolicy", "evaluate_bootnode_trust"]


class TrustPolicy(StrEnum):
    """How an observed bootnode fingerprint is evaluated (SSH-like)."""

    ask = "ask"  # prompt on an unknown node, refuse a changed one (default)
    accept_new = "accept-new"  # pin a first sighting silently, refuse a changed one
    strict = "strict"  # require an explicit pin; refuse unknown or changed
    none = "none"  # no verification (tests/loopback only)


class TrustAction(StrEnum):
    """What the caller must do after evaluating a policy against a fingerprint."""

    proceed = "proceed"  # the node may be contacted
    pin_and_proceed = "pin-and-proceed"  # store the fingerprint, then contact the node
    prompt = "prompt"  # ask the user; store on acceptance, refuse on rejection
    refuse = "refuse"  # the node must not be contacted (unknown/strict or changed)


def evaluate_bootnode_trust(
    policy: TrustPolicy,
    stored_fp: str | None,
    observed_fp: str | None,
) -> TrustAction:
    """Classify an observed bootnode fingerprint under *policy*.

    Args:
        policy: The active :class:`TrustPolicy`.
        stored_fp: The fingerprint already pinned for this ``host:port``, or
            ``None`` when the node has never been seen.
        observed_fp: The fingerprint the node presented now. A missing/invalid
            value can never be trusted (a changed/absent fingerprint is refused
            unless the policy disables verification entirely).

    Returns:
        The :class:`TrustAction` the caller must carry out. ``none`` always
        proceeds; otherwise an unknown node follows the policy and a changed
        fingerprint is always refused.

    Consumers: ``hsync-client`` (bootnode connect path) and the Android mirror,
    both fed by the shared ``bootnode-trust-scenarios`` fixture.
    """
    if policy is TrustPolicy.none:
        return TrustAction.proceed

    observed = normalize_fingerprint(observed_fp)
    if observed is None:
        # No usable fingerprint to pin or compare: never trust it.
        return TrustAction.refuse

    stored = normalize_fingerprint(stored_fp)
    if stored is None:
        if policy is TrustPolicy.accept_new:
            return TrustAction.pin_and_proceed
        if policy is TrustPolicy.ask:
            return TrustAction.prompt
        return TrustAction.refuse

    if fingerprint_matches(observed, [stored]):
        return TrustAction.proceed
    return TrustAction.refuse
