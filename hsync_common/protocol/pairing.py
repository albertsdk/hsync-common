# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Canonical LAN security policy (single source of truth).

The LAN channel is **HTTPS/WSS-only**: every master serves over a self-signed
certificate whose fingerprint (``cert_fp``) travels in the mDNS TXT record, and
may authenticate writes with a shared ``HSYNC_LAN_KEY``. Neither, on its own,
proves *identity*: a self-signed certificate is trusted only because it is the
first one seen for a given peer (Trust On First Use). Because the transport is
mandatory, a peer always presents a fingerprint; there is no plain-HTTP mode and
therefore no "nothing to pin" outcome. This module owns the two pure decisions
that follow from that model so the Python client and the Android client cannot
drift:

* :func:`evaluate_pin` — compare an observed certificate fingerprint against the
  one previously pinned for a ``(cid, bucket)`` and classify the outcome.
* :func:`lan_write_requires_key` — decide whether a shared key is mandatory
  before performing write operations against a master.

Both are side-effect free; persistence (the pin store) and I/O (events, prompts)
live in the consuming client, never here. The threat model these decisions
implement is documented in ``hsync-common/docs/lan-protocol.md``.
"""

from __future__ import annotations

from enum import StrEnum

from .lan import SYNC_DIRECTION_BIDIRECTIONAL

__all__ = [
    "SYNC_DIRECTION_DOWNLOAD_ONLY",
    "SYNC_DIRECTION_UPLOAD_ONLY",
    "PinDecision",
    "evaluate_pin",
    "is_write_direction",
    "lan_write_requires_key",
    "normalize_fingerprint",
    "requires_pairing_confirmation",
]

# Sync-direction vocabulary that, together with ``SYNC_DIRECTION_BIDIRECTIONAL``,
# is the canonical set used across the protocol. Only directions that push data
# to the master ("write") are relevant to the LAN-key policy below.
SYNC_DIRECTION_UPLOAD_ONLY = "upload-only"
SYNC_DIRECTION_DOWNLOAD_ONLY = "download-only"

# Directions that upload to (write on) the master and therefore require auth when
# running unattended. ``download-only`` is read-only against the master.
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
            "a certificate fingerprint is mandatory in LAN mode (HTTPS-only); "
            "got a missing/blank fingerprint"
        )
    stored = normalize_fingerprint(stored_fp)
    if stored is None:
        return PinDecision.trusted
    return PinDecision.matched if observed == stored else PinDecision.changed


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


def lan_write_requires_key(sync_direction: str, *, interactive: bool) -> bool:
    """Whether a shared LAN key is mandatory before writing to the master.

    A self-signed transport hides traffic from passive eavesdroppers but does
    not prove the master's identity, so an unattended client that uploads data
    must authenticate with a shared secret. In interactive use the operator can
    vouch for the peer out of band, so the key stays recommended, not required.

    Args:
        sync_direction: This client's configured direction.
        interactive: ``True`` when a human can confirm trust (a TTY / no
            ``--yes``); ``False`` for unattended/non-interactive runs.

    Returns:
        ``True`` when the run is non-interactive *and* write-capable.
    """
    return not interactive and is_write_direction(sync_direction)
