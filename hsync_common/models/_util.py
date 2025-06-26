# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Internal shared helpers for the models package.

Houses the tiny utilities that both ``version.py`` and ``tombstone.py`` need
(path hashing/relativisation and wire-timestamp parsing) in a module that
imports from neither, so the causal models can cross-reference each other
without circular imports.
"""

from pathlib import Path

__all__ = ["_parse_wire_timestamp", "relpath_in_bucket", "tombstone_key"]


def _parse_wire_timestamp(raw: object) -> int | None:
    """Parse a timestamp from an untrusted wire/storage payload.

    Rejects ``bool`` (which is an ``int`` subclass), non-finite floats
    (``NaN``, ``Infinity``) and non-numeric values, so a malformed entry
    cannot produce a bogus timestamp of 0/1 or crash ``int()``.

    Args:
        raw: The raw timestamp value (int, float, str, etc.).

    Returns:
        The timestamp as a positive integer, or ``None`` when invalid.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError, OverflowError):
        return None


def tombstone_key(relpath: str) -> str:
    """Return the stable, privacy-preserving key for a bucket-relative path."""
    from hashlib import sha256

    return sha256(relpath.encode("utf-8")).hexdigest()


def relpath_in_bucket(abs_path: str, bucket_dir: str) -> str | None:
    """Return the bucket-relative path used as the tombstone identity.

    Uses :meth:`pathlib.Path.relative_to` so a sibling-prefix directory
    (e.g. ``/data/bucket2`` vs ``/data/bucket``) is never confused with
    the bucket itself: ``removeprefix`` would strip the shared prefix and
    produce a bogus relative path (``2/x``), while ``relative_to`` raises
    ``ValueError`` for paths outside the bucket.

    A path outside the bucket returns ``None`` (never the empty string of
    the bucket root): mapping it to the root key (``tombstone_key("")``)
    would corrupt the root's causal state, so callers must treat ``None``
    as "not in bucket" and skip the path.
    """
    try:
        rel = str(Path(str(abs_path)).relative_to(str(bucket_dir)))
        # relative_to of the bucket itself yields ".", normalise to "" so the
        # caller treats the bucket root as an empty relative path.
        return "" if rel == "." else rel
    except ValueError:
        return None
