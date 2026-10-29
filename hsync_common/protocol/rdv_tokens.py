# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""``rdv/1`` bucket-token primitives shared by the rendezvous and its clients.

The bucket token is derived from the group key (the raw ``HSYNC_P2P_KEY``, or the
64-hex key derived from ``HSYNC_P2P_PASSPHRASE``):
``HMAC-SHA256(key, "rdv/1" || bucket)[:32]``, hex-encoded (64 chars). The key
itself is never transported on the wire; only the derived token is.

These primitives are protocol-neutral (no frame models), so both the canonical
rendezvous implementation and the dependency-free client mirror import them from
here instead of copying the algorithms (ADR-0033 keeps the *models* separate,
not the cryptography).

Consumers: ``hsync-rendezvous/python`` (``protocol.py`` / ``tokens.py``),
``hsync_common.protocol.rendezvous`` (client mirror), tests.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata

__all__ = [
    "BUCKET_TOKEN_LEN",
    "MIN_GROUP_KEY_CHARS",
    "MIN_GROUP_PASSPHRASE_CHARS",
    "WeakGroupPassphrase",
    "constant_time_equals",
    "derive_bucket_token",
    "derive_group_key",
    "is_valid_bucket_token",
    "passphrase_warning",
    "validate_group_key",
    "validate_group_passphrase",
    "verify_bucket_token",
]

# hex(32 bytes) = 64 chars. Absent = open bucket.
BUCKET_TOKEN_LEN = 64

# A group key is the ONLY entropy behind a bucket token
# (``hex(HMAC-SHA256(key, "rdv/1" || bucket)[:32])``): with a guessable key a
# token seen anywhere (an instrumented client, a process dump) can be brute
# forced offline. 32 characters carries >=128 bits for any random or
# passphrase-grade value, and is the single threshold both the node (key file)
# and the client (``HSYNC_P2P_KEY``) enforce.
MIN_GROUP_KEY_CHARS = 32

_BUCKET_TOKEN_RE = re.compile(rf"^[0-9a-f]{{{BUCKET_TOKEN_LEN}}}$")

# Domain separation: the same key derives different tokens per protocol channel.
_TOKEN_DOMAIN = b"rdv/1"


def derive_bucket_token(key: bytes, bucket: str) -> str:
    """Derive the 64-char hex bucket token for the given group key + bucket."""
    digest = hmac.new(key, _TOKEN_DOMAIN + bucket.encode("utf-8"), hashlib.sha256).digest()
    return digest[:32].hex()


def is_valid_bucket_token(value: str) -> bool:
    """True iff ``value`` is a well-formed 64-char lowercase hex token."""
    return _BUCKET_TOKEN_RE.fullmatch(value) is not None


def validate_group_key(key: str) -> None:
    """Reject a group key too weak to protect the derived bucket token.

    Raises:
        ValueError: when ``key`` is shorter than :data:`MIN_GROUP_KEY_CHARS`.

    Consumers: ``hsync-rendezvous`` (``cli._parse_keys``, the node's key source) and
    ``hsync-client`` (``config.get_p2p_key``, ``HSYNC_P2P_KEY``), so both ends of
    a bucket enforce one threshold.
    """
    if len(key) < MIN_GROUP_KEY_CHARS:
        raise ValueError(
            f"group key must be at least {MIN_GROUP_KEY_CHARS} characters "
            f"(got {len(key)}); generate one with 'openssl rand -hex 32'"
        )


# A user-typed passphrase is derived to a full-strength group key, so it has its
# own (lower) floor. The derived value is a 64-char hex string, byte-identical in
# shape to a raw HSYNC_P2P_KEY, so every downstream consumer is unchanged.
MIN_GROUP_PASSPHRASE_CHARS = 12

# Fixed, versioned salt. It is deliberately independent of the (display-only)
# group label so renaming a group never silently re-keys it. The trade-off is
# that the passphrase must be unique per group.
_GROUP_KEY_SALT = b"hsync-p2p-group-key/v1"
_GROUP_KEY_N = 2**15
_GROUP_KEY_R = 8
_GROUP_KEY_P = 1
_GROUP_KEY_MAXMEM = 64 * 1024 * 1024

# Short exact-match denylist. It must be mirrored verbatim in the Android client
# (util/GroupKey.kt) and the parity test pins the same cases; keep it exact-match
# (no leet/substring heuristics) so the two implementations cannot drift.
_WEAK_GROUP_PASSPHRASES = frozenset(
    {
        "password1234",
        "password12345",
        "passw0rd1234",
        "qwertyuiopas",
        "qwerty123456",
        "123456789012",
        "letmein12345",
        "iloveyou1234",
        "adminadmin12",
        "changeme1234",
        "welcome12345",
        "hsyncpassword",
        "hsynchsync123",
    }
)


class WeakGroupPassphrase(ValueError):
    """A passphrase rejected by :func:`validate_group_passphrase`.

    ``code`` is stable (``"too_short"`` / ``"too_weak"``) so localized clients
    map it to their own message instead of surfacing English prose.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _normalize_passphrase(passphrase: str) -> str:
    """NFKC + strip: visually identical passphrases derive the same key."""
    return unicodedata.normalize("NFKC", passphrase).strip()


def derive_group_key(passphrase: str) -> str:
    """Derive the 64-char hex group key from a user-typed passphrase.

    scrypt (``n=2**15, r=8, p=1``) with the fixed versioned salt above. The
    result is byte-identical in shape to a raw ``HSYNC_P2P_KEY`` (64 hex), so
    ``derive_bucket_token`` and the Bearer comparison need no changes.
    """
    normalized = _normalize_passphrase(passphrase)
    digest = hashlib.scrypt(
        normalized.encode("utf-8"),
        salt=_GROUP_KEY_SALT,
        n=_GROUP_KEY_N,
        r=_GROUP_KEY_R,
        p=_GROUP_KEY_P,
        dklen=32,
        maxmem=_GROUP_KEY_MAXMEM,
    )
    return digest.hex()


def _is_strictly_consecutive(value: str) -> bool:
    return len(value) >= 2 and all(
        ord(right) - ord(left) == 1 for left, right in zip(value, value[1:], strict=False)
    )


def validate_group_passphrase(passphrase: str) -> None:
    """Reject a passphrase that is too short or trivially weak.

    Raises:
        WeakGroupPassphrase: with ``code`` ``"too_short"`` or ``"too_weak"``.

    The four blocking rules are intentionally algorithmic (plus an exact-match
    denylist) so the Kotlin mirror makes identical decisions.
    """
    normalized = _normalize_passphrase(passphrase)
    if len(normalized) < MIN_GROUP_PASSPHRASE_CHARS:
        raise WeakGroupPassphrase(
            "too_short",
            f"shared password must be at least {MIN_GROUP_PASSPHRASE_CHARS} "
            f"characters (got {len(normalized)})",
        )
    if len(set(normalized)) == 1:
        raise WeakGroupPassphrase("too_weak", "shared password must not repeat a single character")
    if _is_strictly_consecutive(normalized):
        raise WeakGroupPassphrase("too_weak", "shared password must not be a consecutive sequence")
    if normalized.lower() in _WEAK_GROUP_PASSPHRASES:
        raise WeakGroupPassphrase("too_weak", "shared password is too common")


def passphrase_warning(passphrase: str) -> str | None:
    """Non-blocking hint code (``"short"``) for a 12-15 char passphrase."""
    normalized = _normalize_passphrase(passphrase)
    if MIN_GROUP_PASSPHRASE_CHARS <= len(normalized) < 16:
        return "short"
    return None


def constant_time_equals(a: bytes, b: bytes) -> bool:
    """Constant-time byte-string comparison (no timing side-channel)."""
    return hmac.compare_digest(a, b)


def verify_bucket_token(expected: str, provided: str | None) -> bool:
    """Return True iff a provided token matches the expected one, uniformly.

    A missing/malformed token simply never matches (caller decides whether the
    bucket requires one — this helper never reveals that a bucket exists).
    """
    if provided is None:
        return False
    if not is_valid_bucket_token(provided):
        return False
    return constant_time_equals(
        expected.encode("ascii"),
        provided.encode("ascii"),
    )
