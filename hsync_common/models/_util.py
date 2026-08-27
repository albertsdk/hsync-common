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

import json
from hashlib import sha256
from pathlib import Path

__all__ = [
    "_parse_stored_vclock",
    "_parse_wire_timestamp",
    "_resolve_prefixed_path",
    "_vclock_to_json",
    "relpath_in_bucket",
    "tombstone_key",
]

# Module-level constant to avoid recreating the type tuple on every call to
# _parse_wire_timestamp (hot path: called for every version/tombstone row loaded
# from SQLite and every wire entry validated).
_NUMERIC_TYPES = (int, float, str)


def _vclock_to_json(vclock: dict[str, int]) -> str:
    """Serialize a validated vector clock for a ``vclock`` SQLite column."""
    return json.dumps(vclock, separators=(",", ":"), sort_keys=True)


def _parse_stored_vclock(raw: object) -> object:
    """Decode a persisted ``vclock`` column into a JSON-parseable object.

    The column is stored as a compact JSON string; a non-string value (a
    ``dict`` already parsed by the driver, or ``NULL``) is returned verbatim.
    Malformed JSON returns ``None`` so the caller's ``parse_vclock`` rejects
    the row instead of crashing on load.
    """
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _resolve_prefixed_path(data_filepath: str, prefix: str | None, *, strip: bool) -> str:
    """Resolve a filepath from a serialized dict with an optional prefix.

    Shared across :meth:`File.from_dict`, :meth:`Symlink.from_dict`,
    :meth:`Dir.from_dict` and :class:`Event` so the serialisation contract is
    defined once.

    Args:
        data_filepath: Raw ``filepath`` / ``path`` value from the dict.
        prefix: Base directory prefix (``dir_prefix`` / ``localpath``).
        strip: When ``True`` the prefix is stripped from *data_filepath*
            (making it bucket-relative, component-aware: a path outside
            *prefix* is kept verbatim); when ``False`` the prefix is
            prepended (making it absolute).

    Returns:
        The resolved path string.

    Raises:
        ValueError: When *strip* is ``True`` but *prefix* is falsy.
    """
    if strip and not prefix:
        raise ValueError("Set dir_prefix to strip it.")
    if strip and prefix:
        try:
            rel = str(Path(data_filepath).relative_to(prefix))
        except ValueError:
            # Not under prefix: keep the original path verbatim. Component-aware
            # stripping never mangles a sibling path that merely shares the
            # string prefix (e.g. "/base2/x" vs "/base" must not become "2/x").
            return str(data_filepath)
        return "" if rel == "." else rel.lstrip("/")
    if prefix:
        return str(Path(prefix) / str(data_filepath).lstrip("/"))
    return str(data_filepath)


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
    if isinstance(raw, bool) or not isinstance(raw, _NUMERIC_TYPES):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError, OverflowError):
        return None


def tombstone_key(relpath: str) -> str:
    """Return the stable, privacy-preserving key for a bucket-relative path."""
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
