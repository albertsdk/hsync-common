# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Canonical HSYNC alphanumeric identifiers (client CID, server account id).

Deliberately lightweight and stdlib-only: the alphabet, the wire pattern, the
mint and the validator are needed on the CLI startup fast path
(``hsync --version`` / ``--help``) and by the server account ids, so they must
not drag in the model layer (``cryptography`` and friends).

The id shape is strictly alphanumeric ASCII, exactly 21 characters, so a cid
always starts with a letter or digit — never ``-`` or ``_``.
"""

from __future__ import annotations

import secrets

__all__ = [
    "CID_ALPHABET",
    "CID_LENGTH",
    "CID_PATTERN",
    "is_valid_cid",
    "mint_cid",
]

CID_LENGTH = 21
# Strictly alphanumeric (A-Z a-z 0-9), matching CID_PATTERN.
CID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

# Public regex string (consumed by protocol.schemas and protocol.rendezvous);
# is_valid_cid deliberately does NOT use it at runtime — the len/isascii/isalnum
# chain is exactly equivalent and avoids the regex engine on the hot path.
CID_PATTERN = r"^[A-Za-z0-9]{21}$"


def is_valid_cid(value: object) -> bool:
    """Return True when *value* is a well-formed client ID (see CID_PATTERN)."""
    return (
        isinstance(value, str) and len(value) == CID_LENGTH and value.isascii() and value.isalnum()
    )


def mint_cid(length: int = CID_LENGTH) -> str:
    """Mint a fresh alphanumeric id (NanoID-style) matching :data:`CID_PATTERN`.

    ``secrets.choice`` is unbiased, unlike a ``byte % len`` mapping (64 does not
    divide 62).
    """
    return "".join(secrets.choice(CID_ALPHABET) for _ in range(length))
