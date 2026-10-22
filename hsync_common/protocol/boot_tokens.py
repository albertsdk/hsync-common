# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""``boot/1`` bucket-token primitives shared by the bootnode and its clients.

The bucket token is derived from the existing group key ``HSYNC_P2P_KEY``:
``HMAC-SHA256(key, "boot/1" || bucket)[:32]``, hex-encoded (64 chars). The key
itself is never transported on the wire; only the derived token is.

These primitives are protocol-neutral (no frame models), so both the canonical
bootnode implementation and the dependency-free client mirror import them from
here instead of copying the algorithms (ADR-0033 keeps the *models* separate,
not the cryptography).

Consumers: ``hsync-bootnode/python`` (``protocol.py`` / ``tokens.py``),
``hsync_common.protocol.bootnode`` (client mirror), tests.
"""

from __future__ import annotations

import hashlib
import hmac
import re

__all__ = [
    "BUCKET_TOKEN_LEN",
    "constant_time_equals",
    "derive_bucket_token",
    "is_valid_bucket_token",
    "verify_bucket_token",
]

# hex(32 bytes) = 64 chars. Absent = open bucket.
BUCKET_TOKEN_LEN = 64
_BUCKET_TOKEN_RE = re.compile(rf"^[0-9a-f]{{{BUCKET_TOKEN_LEN}}}$")

# Domain separation: the same key derives different tokens per protocol channel.
_TOKEN_DOMAIN = b"boot/1"


def derive_bucket_token(key: bytes, bucket: str) -> str:
    """Derive the 64-char hex bucket token for the given group key + bucket."""
    digest = hmac.new(key, _TOKEN_DOMAIN + bucket.encode("utf-8"), hashlib.sha256).digest()
    return digest[:32].hex()


def is_valid_bucket_token(value: str) -> bool:
    """True iff ``value`` is a well-formed 64-char lowercase hex token."""
    return _BUCKET_TOKEN_RE.fullmatch(value) is not None


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
