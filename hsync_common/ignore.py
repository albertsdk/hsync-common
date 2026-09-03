# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
gitignore-style ignore filtering for HSYNC.

This module provides :class:`IgnoreMatcher`, a thin wrapper around
`pathspec` that combines three layers of rules:

1. **Default ignore patterns** — built-in gitignore-style patterns for
   operating-system cache files (``.DS_Store``, ``Thumbs.db`` …) and
   editor/office temporary files.  These are *always* active and cannot
   be disabled, following the industry standard (Syncthing, rsync,
   Nextcloud, OneDrive).  Dotfiles in general (``.env``, ``.config`` …)
   are **not** excluded: they are synchronised normally.
2. **Bucket-local ``.hsyncignore``** — gitignore-syntax file at the
   bucket root.  Always honoured when present.
3. **Extra patterns** — additional gitignore patterns supplied by the
   client (e.g. from a global user config).

The sentinel file :data:`HSYNCKEEP_FILENAME` is always kept regardless
of any pattern so empty-directory synchronisation keeps working.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from os.path import relpath
from pathlib import Path

from pathspec import PathSpec
from pathspec.patterns.gitignore.spec import GitIgnoreSpecPattern

from hsync_common.constants import (
    DEFAULT_IGNORE_PATTERNS,
    HSYNCIGNORE_FILENAME,
    HSYNCKEEP_FILENAME,
)
from hsync_common.models.file import is_partial_file
from hsync_common.path_validation import basename, is_internal_name

# Maximum number of total ignore patterns (defaults + .hsyncignore + extras).
# Beyond this cap the remaining patterns are silently dropped to prevent
# ReDoS from a crafted file with thousands of complex regex-compiled globs.
_MAX_IGNORE_PATTERNS = 1000


class IgnoreMatcher:
    """gitignore-style matcher with built-in default patterns.

    The matcher is built around a *bucket root*; all paths passed to
    :meth:`matches` are normalised relative to that root before being
    tested against the loaded ``.hsyncignore`` rules.

    Attributes:
        bucket_root: Absolute path of the directory being synchronised.
        extra_patterns: Additional gitignore patterns supplied at
            construction time (e.g. from ``--ignore-pattern``).
    """

    def __init__(
        self,
        bucket_root: str,
        extra_patterns: Iterable[str] | None = None,
    ) -> None:
        self.bucket_root = str(Path(bucket_root).resolve()) if bucket_root else ""
        self._extra_patterns = list(extra_patterns or [])
        self._spec: PathSpec = PathSpec.from_lines(GitIgnoreSpecPattern, [])
        self._lock = threading.RLock()
        self.reload()

    # ------------------------------------------------------------------
    # Loading / reloading
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Re-read ``.hsyncignore`` from disk and rebuild the spec.

        Called automatically by :meth:`__init__` and intended to be
        invoked by client code (or a file watcher) whenever the ignore
        file changes on disk.
        """
        patterns: list[str] = []

        # Layer 1 — built-in default patterns (always active)
        patterns.extend(DEFAULT_IGNORE_PATTERNS)

        # Layer 2 — bucket-local .hsyncignore
        if self.bucket_root:
            ignore_path = Path(self.bucket_root) / HSYNCIGNORE_FILENAME
            if ignore_path.is_file():
                try:
                    patterns.extend(
                        ignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    )
                except OSError:
                    pass

        # Layer 3 — extra programmatic patterns
        patterns.extend(self._extra_patterns)

        # Enforce a maximum number of patterns to prevent ReDoS from a
        # crafted .hsyncignore with thousands of complex glob expressions.
        # Each pattern is compiled to a regex internally; 1000 is well
        # beyond any reasonable hand-crafted file.
        if len(patterns) > _MAX_IGNORE_PATTERNS:
            import warnings

            warnings.warn(
                f"Ignore patterns exceed {_MAX_IGNORE_PATTERNS}; "
                f"truncating to first {_MAX_IGNORE_PATTERNS}",
                stacklevel=2,
            )
            patterns = patterns[:_MAX_IGNORE_PATTERNS]

        with self._lock:
            self._spec = PathSpec.from_lines(GitIgnoreSpecPattern, patterns)

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _to_relative(self, path: str) -> str:
        """Normalise *path* to a POSIX bucket-root-relative form."""
        if not path:
            return ""
        # Str-level absolute-path test: cheaper than constructing a Path object
        # per scanned entry (called once per file during every scan).
        if (
            path.startswith("/") or path.startswith("\\") or (len(path) > 2 and path[1] == ":")
        ) and self.bucket_root:
            try:
                rel = relpath(path, self.bucket_root)
            except ValueError:
                # Different drives on Windows, etc.
                rel = path
        else:
            rel = path
        rel = rel.replace("\\", "/")
        # Strip only leading "./" segments: a blanket lstrip("./") would also
        # eat leading dots, making dotfiles (.env, .hsyncignore) unmatchable.
        while rel.startswith("./"):
            rel = rel[2:]
        return rel

    def matches(self, path: str, is_dir: bool = False) -> bool:
        """Return ``True`` when *path* should be **excluded** from sync.

        Args:
            path: File or directory path (absolute or bucket-relative).
            is_dir: When ``True`` the trailing slash is appended so
                gitignore directory-only patterns (``foo/``) match.
        """
        name = basename(path)

        # Sentinel file is always preserved
        if name == HSYNCKEEP_FILENAME:
            return False

        # Engine-owned artifacts (.hsyncignore, .hsyncfolder, leftover
        # .hsyncstate / .hsynctombstones)
        # and in-progress transfer artifacts (.part) are never synced,
        # regardless of .hsyncignore rules.
        if is_internal_name(name):
            return True
        if not is_dir and is_partial_file(name):
            return True

        rel = self._to_relative(path)
        if not rel:
            return False

        # gitignore directory patterns need a trailing slash to fire
        candidate = rel + ("/" if is_dir and not rel.endswith("/") else "")

        with self._lock:
            return self._spec.match_file(candidate)


# ----------------------------------------------------------------------
# Module-level singleton (set by the client at startup)
# ----------------------------------------------------------------------

_active_matcher: IgnoreMatcher | None = None
_active_lock = threading.RLock()


def set_active_matcher(matcher: IgnoreMatcher | None) -> None:
    """Install *matcher* as the process-wide active matcher.

    Passing ``None`` clears the active matcher, which causes
    :func:`should_skip` to fall back to the built-in default patterns
    only.  This keeps existing code paths that have no notion of an
    ignore file working unchanged.
    """
    global _active_matcher
    with _active_lock:
        _active_matcher = matcher


def get_active_matcher() -> IgnoreMatcher | None:
    """Return the currently active :class:`IgnoreMatcher`, if any."""
    with _active_lock:
        return _active_matcher


# Fallback matcher used when no matcher is installed (e.g. on the server).
# bucket_root="" → reload() skips .hsyncignore I/O and uses only the built-in
# default patterns, exactly matching the legacy behaviour of should_skip.
_fallback_matcher = IgnoreMatcher("")


def should_skip(path: str, is_dir: bool = False) -> bool:
    """Convenience entry point used by sync engines.

    Delegates to the active :class:`IgnoreMatcher` when one is
    installed, otherwise falls back to the built-in default patterns
    so legacy behaviour is preserved.
    """
    matcher = get_active_matcher()
    return (matcher or _fallback_matcher).matches(path, is_dir=is_dir)
