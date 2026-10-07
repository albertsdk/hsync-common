# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Internal shared helpers for the models package.

Houses the tiny utilities that both ``version.py`` and ``tombstone.py`` need
(path hashing/relativisation and wire-timestamp parsing) in a module that
imports from neither, so the causal models can cross-reference each other
without circular imports.
"""

import json
import os
from hashlib import sha256

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


def _split_path_components(path: str) -> list[str]:
    """Split *path* into components the way ``PurePath`` parsing does.

    Duplicate separators are collapsed and ``.`` components are dropped, but
    ``..`` is **preserved**: resolving it would silently relocate a path, while
    ``Path.relative_to`` kept it verbatim. The leading separator of an absolute
    path is kept as an empty first component so absoluteness takes part in the
    prefix comparison. Uses ``os.sep``; on Windows the alternate separator
    (``/``) is folded in, exactly as ``WindowsPath`` does, while on POSIX a
    backslash stays a legal filename character.
    """
    if os.sep != "/":
        path = path.replace("/", os.sep)
    parts = [part for part in path.split(os.sep) if part and part != "."]
    return ["", *parts] if path.startswith(os.sep) else parts


# LRU-1 cache of the *prefix* component split: ``relpath_in_bucket`` / decoded
# models call :func:`_strip_prefix_components` once per scanned path with the
# same bucket root, so re-splitting the constant prefix per entry is pure waste.
# A single entry keeps memory bounded; a concurrent miss just recomputes.
_last_prefix: str | None = None
_last_prefix_parts: list[str] = []


def _strip_prefix_components(path: str, prefix: str) -> str | None:
    """Return *path* relative to *prefix*, or ``None`` when it is not inside.

    Component-aware: ``/base2/x`` is never stripped against ``/base`` (a string
    prefix check would yield ``2/x``), the prefix itself maps to ``""``, and the
    result never carries a leading separator. An empty *prefix* means "nothing
    is inside" and yields ``None``.

    Replaces ``Path(path).relative_to(prefix)`` on the hot path: pathlib
    parsing costs ~12.7 us per call against ~1.0 us here, and it is invoked once
    per path of every scan (``relpath_in_bucket``) and per decoded model.
    """
    global _last_prefix, _last_prefix_parts
    if not prefix:
        return None
    if prefix == _last_prefix:
        prefix_parts = _last_prefix_parts
    else:
        prefix_parts = _split_path_components(prefix)
        _last_prefix = prefix
        _last_prefix_parts = prefix_parts
    path_parts = _split_path_components(str(path))
    if len(path_parts) < len(prefix_parts) or path_parts[: len(prefix_parts)] != prefix_parts:
        return None
    return os.sep.join(path_parts[len(prefix_parts) :])


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
        # Fast path: an already-relative path can never sit under an absolute
        # prefix, so it is returned verbatim — exactly what the component-aware
        # strip below would conclude after two list splits (it is a pure no-op).
        if not str(data_filepath).startswith(os.sep) and prefix.startswith(os.sep):
            return str(data_filepath)
        relative = _strip_prefix_components(data_filepath, prefix)
        # Not under prefix: keep the original path verbatim. Component-aware
        # stripping never mangles a sibling path that merely shares the
        # string prefix (e.g. "/base2/x" vs "/base" must not become "2/x").
        return str(data_filepath) if relative is None else relative
    if prefix:
        # String concat instead of Path(prefix) / rel: avoids pathlib parsing
        # (~2 us saved per decoded model on the prepend branch). String
        # equality with ``str(Path(prefix) / rel)`` is guaranteed only for
        # already-normalized inputs (no trailing slash on the prefix, no "."
        # / duplicate separators inside): that is the shape of every
        # production caller (bucket roots, dir_prefix, localpath) and of the
        # benchmark fixtures, and it is pinned by the prepend-equivalence
        # test in tests/test_models_file.py.
        return prefix.rstrip("/") + "/" + str(data_filepath).lstrip("/")
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

    Component-aware and never resolves ``..`` (a path that merely shares a
    string prefix with the bucket, e.g. ``/data/bucket2`` vs ``/data/bucket``,
    is not stripped into a bogus relative path such as ``2/x``).

    A path outside the bucket returns ``None`` (never the empty string of
    the bucket root): mapping it to the root key (``tombstone_key("")``)
    would corrupt the root's causal state, so callers must treat ``None``
    as "not in bucket" and skip the path. An empty *bucket_dir* means no path
    is inside, so the result is always ``None``.
    """
    return _strip_prefix_components(str(abs_path), str(bucket_dir))
