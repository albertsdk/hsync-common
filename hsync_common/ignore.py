# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
gitignore-style ignore filtering for HSYNC.

This module provides :class:`IgnoreMatcher`, a thin wrapper around
`pathspec` that combines three layers of rules:

1. **Default hidden patterns** — the built-in regex used by
   :func:`hsync_common.models.file.is_hidden_file` and
   :func:`hsync_common.models.dir.is_hidden_dir`.  Active when
   ``include_hidden=False`` (the default).
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
from pathspec.patterns import GitWildMatchPattern

from hsync_common.constants import HSYNCIGNORE_FILENAME, HSYNCKEEP_FILENAME
from hsync_common.models.dir import _is_hidden_dir_basic
from hsync_common.models.file import _is_hidden_file_basic


class IgnoreMatcher:
    """gitignore-style matcher with hidden-file fallback.

    The matcher is built around a *bucket root*; all paths passed to
    :meth:`match` are normalised relative to that root before being
    tested against the loaded ``.hsyncignore`` rules.

    Attributes:
        bucket_root: Absolute path of the directory being synchronised.
        include_hidden: When ``True`` the built-in hidden-file detection
            is disabled and only ``.hsyncignore`` (plus extra patterns)
            filters paths.
    """

    def __init__(
        self,
        bucket_root: str,
        include_hidden: bool = False,
        extra_patterns: Iterable[str] | None = None,
    ) -> None:
        self.bucket_root = str(Path(bucket_root).resolve()) if bucket_root else ""
        self.include_hidden = include_hidden
        self._extra_patterns = list(extra_patterns or [])
        self._spec: PathSpec = PathSpec.from_lines(GitWildMatchPattern, [])
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

        if self.bucket_root:
            ignore_path = Path(self.bucket_root) / HSYNCIGNORE_FILENAME
            if ignore_path.is_file():
                try:
                    patterns.extend(
                        ignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    )
                except OSError:
                    pass

        patterns.extend(self._extra_patterns)

        with self._lock:
            self._spec = PathSpec.from_lines(GitWildMatchPattern, patterns)

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _to_relative(self, path: str) -> str:
        """Normalise *path* to a POSIX bucket-root-relative form."""
        if not path:
            return ""
        if Path(path).is_absolute() and self.bucket_root:
            try:
                rel = relpath(path, self.bucket_root)
            except ValueError:
                # Different drives on Windows, etc.
                rel = path
        else:
            rel = path
        return rel.replace("\\", "/").lstrip("./")

    def matches(self, path: str, is_dir: bool = False) -> bool:
        """Return ``True`` when *path* should be **excluded** from sync.

        Args:
            path: File or directory path (absolute or bucket-relative).
            is_dir: When ``True`` the trailing slash is appended so
                gitignore directory-only patterns (``foo/``) match.
        """
        name = Path(path.rstrip("/")).name

        # Sentinel file is always preserved
        if name == HSYNCKEEP_FILENAME:
            return False

        rel = self._to_relative(path)
        if not rel:
            return False

        # gitignore directory patterns need a trailing slash to fire
        candidate = rel + ("/" if is_dir and not rel.endswith("/") else "")

        with self._lock:
            if self._spec.match_file(candidate):
                return True

        if self.include_hidden:
            return False

        return _is_hidden_dir_basic(path) if is_dir else _is_hidden_file_basic(path)


# ----------------------------------------------------------------------
# Module-level singleton (set by the client at startup)
# ----------------------------------------------------------------------

_active_matcher: IgnoreMatcher | None = None
_active_lock = threading.RLock()


def set_active_matcher(matcher: IgnoreMatcher | None) -> None:
    """Install *matcher* as the process-wide active matcher.

    Passing ``None`` clears the active matcher, which causes
    :func:`should_skip` to fall back to the legacy hidden-file checks
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


def should_skip(path: str, is_dir: bool = False) -> bool:
    """Convenience entry point used by sync engines.

    Delegates to the active :class:`IgnoreMatcher` when one is
    installed, otherwise falls back to the built-in hidden-file
    detection so legacy behaviour is preserved.
    """
    matcher = get_active_matcher()
    if matcher is not None:
        return matcher.matches(path, is_dir=is_dir)

    name = Path(path.rstrip("/")).name
    if name == HSYNCKEEP_FILENAME:
        return False
    return _is_hidden_dir_basic(path) if is_dir else _is_hidden_file_basic(path)
