#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Relative-link checker for the HSYNC markdown docs.

Scans every ``*.md`` file under the given root(s) and verifies that each
relative link (``[text](path)``) and inline image points to a file or directory
that actually exists. External links (``http(s)://``, ``mailto:``), pure anchors
(``#section``) and absolute paths are skipped. Links that resolve *outside* the
scanned root (cross-project references between sibling repos) are also skipped:
they are unresolvable when a single repo is checked out in isolation and are
validated instead by the monorepo-root scan that includes every project. Exits
non-zero on the first set of broken links so it can gate CI / ``make
docs-link-check``.

Usage::

    check_doc_links.py [ROOT ...]

With no arguments it scans the repository root (the ``hsync-common`` checkout).
The root ``Makefile`` passes the workspace root (``.``) to scan every project.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# scripts/dev/check_doc_links.py -> parents[2] == repo root (hsync-common).
REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories that never contain authored docs we want to validate.
EXCLUDE_DIRS = {
    ".git",
    ".kilo",
    ".venv",
    "node_modules",
    "build",
    ".gradle",
    ".pytest_cache",
    "__pycache__",
    "dist",
    ".idea",
}

# [text](target) and ![alt](target); capture the target only.
_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_SKIP_PREFIXES = ("http://", "https://", "mailto:", "tel:", "#", "//")

# Projects whose documentation is referenced across the monorepo. Relative
# links pointing into these projects are broken when a single repo is checked
# out in isolation (CI / GitHub browsing). In user-facing docs (``docs/``)
# they must use absolute GitHub URLs; in the agent wiki (``llm-wiki/``) they
# are allowed to stay relative because the monorepo is always checked out
# together when agents run.
_HSYNC_PROJECTS = {
    "hsync-common",
    "hsync-client",
    "hsync-server",
    "hsync-desktop",
    "hsync-android",
}


def _is_cross_project_link(target: str) -> bool:
    """Return True when *target* is a relative path into another HSYNC project.

    A target like ``../../hsync-common/docs/foo.md`` or
    ``../../../hsync-server/docs/bar.md`` is recognised as a cross-project
    reference that will not resolve on GitHub when browsing a single repo.
    """
    first = target.lstrip("./").split("/", 1)[0]
    return first in _HSYNC_PROJECTS


def _is_user_docs(md_file: Path, root: Path) -> bool:
    """Return True when *md_file* lives under a user-facing ``docs/`` tree.

    Cross-project relative links are forbidden here (they break on GitHub when
    a single repo is checked out) and must be absolute GitHub URLs instead.
    The agent wiki (``llm-wiki/``) is exempt: it is only consumed inside the
    monorepo, where relative cross-project paths always resolve.
    """
    return "docs" in md_file.relative_to(root).parts


def iter_markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.md"):
        if any(part in EXCLUDE_DIRS for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return sorted(files)


def extract_targets(text: str) -> list[str]:
    targets: list[str] = []
    for raw in _LINK_RE.findall(text):
        target = raw.strip()
        # Drop optional link titles: [x](path "title").
        if " " in target:
            target = target.split(" ", 1)[0]
        targets.append(target)
    return targets


def is_checkable(target: str) -> bool:
    if not target:
        return False
    if target.startswith(_SKIP_PREFIXES):
        return False
    # Absolute filesystem paths are environment-specific: do not validate.
    return not target.startswith("/")


def resolve(md_file: Path, target: str) -> Path:
    # Strip anchor / query fragments before resolving the filesystem path.
    path_part = target.split("#", 1)[0].split("?", 1)[0]
    return (md_file.parent / path_part).resolve()


def find_broken_links(root: Path) -> tuple[list[tuple[Path, str]], int]:
    """Return ``(broken, checked)`` for every markdown file under ``root``."""
    broken: list[tuple[Path, str]] = []
    checked = 0

    for md_file in iter_markdown_files(root):
        try:
            text = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:  # pragma: no cover - I/O guard
            print(f"WARN: cannot read {md_file}: {exc}", file=sys.stderr)
            continue

        for target in extract_targets(text):
            if not is_checkable(target):
                continue
            # Cross-project relative links: forbidden in user-facing docs
            # (they break on GitHub when a single repo is checked out and
            # must be absolute GitHub URLs), allowed in the agent wiki
            # (``llm-wiki/``), which is only consumed inside the monorepo.
            if _is_cross_project_link(target):
                if _is_user_docs(md_file, root):
                    broken.append((md_file, target))
                continue
            resolved = resolve(md_file, target)
            if not resolved.is_relative_to(root):
                continue
            checked += 1
            if not resolved.exists():
                broken.append((md_file, target))

    return broken, checked


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    roots = [Path(a).resolve() for a in args] if args else [REPO_ROOT]

    broken: list[tuple[Path, str]] = []
    checked = 0
    for root in roots:
        root_broken, root_checked = find_broken_links(root)
        broken.extend(root_broken)
        checked += root_checked

    if broken:
        print(f"Broken relative links: {len(broken)} (checked {checked})\n")
        for md_file, target in broken:
            print(f"  {md_file} -> {target}")
        return 1

    print(f"docs-link-check OK: {checked} relative links valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
