# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Canonical LAN security policy (single source of truth).

The LAN channel is **HTTPS/WSS-only**: every master serves over a self-signed
certificate whose fingerprint (``cert_fp``) travels in the mDNS TXT record, and
write authorization uses either a shared ``HSYNC_P2P_KEY`` or the explicit
dangerous keyless-write opt-in from ADR-0029. A self-signed certificate does not,
on its own, prove *identity*: it is trusted only because it is the first one seen
for a given peer (Trust On First Use). Because the transport is mandatory, a peer
always presents a fingerprint; there is no plain-HTTP mode and therefore no
"nothing to pin" outcome. This module owns the two pure decisions that follow
from that model so the Python client and the Android client cannot drift:

* :func:`evaluate_pin` — compare an observed certificate fingerprint against the
  one previously pinned for a ``(cid, bucket)`` and classify the outcome.
* :func:`p2p_write_requires_key` — decide whether a shared key is mandatory
  before performing write operations against a master.

Both are side-effect free; persistence (the pin store) and I/O (events, prompts)
live in the consuming client, never here. The threat model these decisions
implement is documented in ``hsync-common/docs/p2p-protocol.md``.
"""

from __future__ import annotations

import hmac
from collections.abc import Sequence
from enum import StrEnum

from hsync_common.hashing import is_sha256_hex

from .p2p import SYNC_DIRECTION_BIDIRECTIONAL

__all__ = [
    "SYNC_DIRECTION_DOWNLOAD_ONLY",
    "SYNC_DIRECTION_UPLOAD_ONLY",
    "FingerprintMismatch",
    "PinDecision",
    "evaluate_pin",
    "fingerprint_matches",
    "is_write_direction",
    "normalize_fingerprint",
    "p2p_write_requires_key",
    "parse_fingerprint",
    "requires_pairing_confirmation",
]

# Sync-direction vocabulary that, together with ``SYNC_DIRECTION_BIDIRECTIONAL``,
# is the canonical set used across the protocol. Only directions that push data
# to the master ("write") are relevant to the LAN-key policy below.
SYNC_DIRECTION_UPLOAD_ONLY = "upload-only"
SYNC_DIRECTION_DOWNLOAD_ONLY = "download-only"

# Directions that upload to (write on) the master and therefore require a LAN
# key unless the explicit ADR-0029 keyless-write opt-in is enabled.
# ``download-only`` is read-only against the master.
_WRITE_DIRECTIONS = frozenset({SYNC_DIRECTION_BIDIRECTIONAL, SYNC_DIRECTION_UPLOAD_ONLY})


class PinDecision(StrEnum):
    """Outcome of comparing an observed fingerprint against the stored pin.

    The consuming client maps these to behaviour: ``trusted``/``matched`` proceed
    and ``changed`` is refused and surfaced as a ``fingerprint_changed`` event.
    Since LAN transport is HTTPS-only, a fingerprint is always present; a missing
    one is a contract violation (:func:`evaluate_pin` raises), not an outcome.
    """

    trusted = "trusted"  # first sighting for this (cid, bucket): pin it and proceed (TOFU)
    matched = "matched"  # observed fingerprint equals the stored pin: proceed
    changed = "changed"  # observed differs from the stored pin: refuse (possible MITM)


class FingerprintMismatch(Exception):
    """The observed certificate fingerprint matches none of the accepted pins.

    Raised by the consuming client when a bootnode presents a certificate whose
    SHA-256 DER fingerprint is not in the accepted set (explicit pins or the TOFU
    store). It is fatal: the connection is closed before any frame is sent.
    """


def normalize_fingerprint(fingerprint: str | None) -> str | None:
    """Normalise a certificate fingerprint for stable, case-insensitive compares.

    Returns ``None`` for missing/blank input. Otherwise lower-cases and strips
    surrounding whitespace and any ``:``/space separators some tools insert
    between hex octets, so ``AA:BB`` and ``aabb`` pin identically.
    """
    if not fingerprint:
        return None
    cleaned = fingerprint.strip().lower().replace(":", "").replace(" ", "")
    return cleaned or None


def parse_fingerprint(value: str | None) -> str | None:
    """Parse a bootnode certificate fingerprint into canonical lowercase hex.

    Accepts the canonical ``sha256:<hex>`` form and bare hex (optionally
    colon- or space-separated), and returns the normalized 64-char lowercase hex
    digest. Returns ``None`` when the value is missing, blank, or not a full
    SHA-256 hex digest — an invalid pin never becomes a silent match.

    Consumers: ``hsync-client`` (bootnode fingerprint pinning), the bootnode
    CLI ``identity show``, and the language-neutral parity test.
    """
    if not value:
        return None
    cleaned = value.strip().lower()
    if cleaned.startswith("sha256:"):
        cleaned = cleaned[len("sha256:") :]
    normalized = normalize_fingerprint(cleaned)
    if normalized is None or not is_sha256_hex(normalized):
        return None
    return normalized


def evaluate_pin(stored_fp: str | None, observed_fp: str | None) -> PinDecision:
    """Classify an observed fingerprint against the previously pinned one (TOFU).

    Args:
        stored_fp: The fingerprint already pinned for this ``(cid, bucket)``, or
            ``None`` when the peer has never been seen.
        observed_fp: The fingerprint presented now. LAN transport is HTTPS-only,
            so a master always presents one; a missing/blank value is a contract
            violation.

    Returns:
        :class:`PinDecision` describing the trust outcome.

    Raises:
        ValueError: when ``observed_fp`` is missing/blank (no plain-HTTP master
            exists under the HTTPS-only LAN contract).
    """
    observed = normalize_fingerprint(observed_fp)
    if observed is None:
        raise ValueError(
            "a certificate fingerprint is mandatory in p2p mode (HTTPS-only); "
            "got a missing/blank fingerprint"
        )
    stored = normalize_fingerprint(stored_fp)
    if stored is None:
        return PinDecision.trusted
    return PinDecision.matched if observed == stored else PinDecision.changed


def fingerprint_matches(observed: str, pins: Sequence[str]) -> bool:
    """Return ``True`` when *observed* matches any accepted pin, constant-time.

    The observed fingerprint and each pin are parsed with
    :func:`parse_fingerprint` (so ``sha256:<hex>`` and bare/colon-separated hex
    all normalize to the same 64-char lowercase digest) and compared with
    :func:`hmac.compare_digest`, so an attacker cannot time the comparison. An
    invalid observed fingerprint or an invalid pin never matches.

    Consumers: ``hsync-client`` (bootnode fingerprint pinning).
    """
    observed_norm = parse_fingerprint(observed)
    if observed_norm is None:
        return False
    for pin in pins:
        pin_norm = parse_fingerprint(pin)
        if pin_norm is not None and hmac.compare_digest(observed_norm, pin_norm):
            return True
    return False


def requires_pairing_confirmation(decision: PinDecision, *, require_pairing: bool) -> bool:
    """Whether a first-seen fingerprint must be confirmed out of band first.

    Under *strict pairing* the Trust-On-First-Use shortcut is disabled: a peer's
    first certificate (``trusted``) is no longer auto-pinned but must be vouched
    for by the operator out of band, so the client refuses and emits
    ``pairing_needed`` instead of silently trusting it. Every other decision
    (``matched``/``changed``) is unaffected — pairing only gates the very first
    sighting.

    Args:
        decision: The outcome of :func:`evaluate_pin` for this peer.
        require_pairing: ``True`` when strict pairing is enabled.

    Returns:
        ``True`` when the connection must be refused pending explicit pairing.
    """
    return require_pairing and decision is PinDecision.trusted


def is_write_direction(sync_direction: str) -> bool:
    """True when *sync_direction* uploads data to (writes on) the master."""
    return sync_direction in _WRITE_DIRECTIONS


def p2p_write_requires_key(
    sync_direction: str,
    *,
    allow_unauthenticated_writes: bool = False,
) -> bool:
    """Whether a shared LAN key is mandatory before writing to the master.

    A self-signed transport hides traffic from passive eavesdroppers but does
    not authorize mutation. A write-capable no-key run is therefore rejected by
    default and is enabled only by the explicit dangerous opt-in from ADR-0029.

    Args:
        sync_direction: This client's configured direction.
        allow_unauthenticated_writes: Explicit local opt-in to no-key mutation.

    Returns:
        ``True`` when the run is write-capable without the explicit opt-in.
    """
    return is_write_direction(sync_direction) and not allow_unauthenticated_writes
