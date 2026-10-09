#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

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
    "hsync-bootnode",
}

# Projects whose wiki symbol anchors are enforced (migrated to ``file.py::symbol``).
# The remaining wikis are migrated later; their legacy line anchors are warnings.
_ENFORCED_PROJECTS = {
    "hsync-common",
    "hsync-server",
    "hsync-bootnode",
    "hsync-client",
}

# Wiki symbol anchors: ``path/to/file.py::symbol`` and the legacy
# ``path/to/file.py:123`` line form we are retiring.
_ANCHOR_SPAN_RE = re.compile(r"`([^`\n]+)`")
_ANCHOR_PATTERN = re.compile(r"^([A-Za-z0-9_./-]+\.(?:py|kt|rs))::([A-Za-z_][A-Za-z0-9_.]*)$")
_LEGACY_LINE_PATTERN = re.compile(r"^([A-Za-z0-9_./-]+\.(?:py|kt|rs)):\d+$")


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


def _is_wiki_file(md_file: Path, root: Path) -> bool:
    """Return True when *md_file* lives under an ``llm-wiki/`` tree."""
    try:
        return "llm-wiki" in md_file.relative_to(root).parts
    except ValueError:
        return False


def _project_base(md_file: Path) -> Path | None:
    """Return the project directory that owns *md_file* (the ``llm-wiki/`` parent).

    When the checker scans the monorepo root, a wiki file lives at
    ``<root>/<project>/llm-wiki/...`` and its anchors are written relative to
    ``<root>/<project>``; when it scans a single repo, the base is the root
    itself. Walking up to the ``llm-wiki`` ancestor handles both cases.
    """
    for parent in md_file.parents:
        if parent.name == "llm-wiki":
            return parent.parent
    return None


def _project_name(md_file: Path, root: Path) -> str:
    """Return the hyphenated project dir name that owns *md_file*."""
    project = _project_base(md_file)
    return project.name if project is not None else root.name


def _is_enforced_file(md_file: Path, root: Path) -> bool:
    """Return True when *md_file*'s project has symbol-anchor enforcement.

    Enforced for migrated wikis (``_ENFORCED_PROJECTS``); the remaining projects
    are migrated later, so their legacy line anchors are non-fatal warnings.
    """
    return _project_name(md_file, root) in _ENFORCED_PROJECTS


def _anchor_project(rel: str) -> str | None:
    """Return the hyphenated project named by *rel*'s first component, if any.

    ``hsync_server/api/x.py`` -> ``hsync-server``; package-relative paths like
    ``api/x.py`` return ``None``.
    """
    normalized = rel.split("/", 1)[0].replace("_", "-")
    return normalized if normalized in _HSYNC_PROJECTS else None


def _resolve_anchor_file(project: Path, rel: str) -> Path | None:
    """Resolve a wiki anchor file path to an existing file under *project*.

    Wiki anchor paths are written relative to either the project root
    (``hsync_server/api/x.py``) or the package directory (``api/x.py``,
    ``constants.py``, ``models/...``), so both bases are tried.
    """
    package_dir = project.name.replace("-", "_")
    candidates = [project / rel]
    if not rel.startswith(package_dir + "/"):
        candidates.append(project / package_dir / rel)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _symbol_present(path: Path, symbol: str) -> bool:
    """Return True when *symbol* is defined in *path*.

    Only the final dotted component is matched (``File.get`` -> ``get``), and a
    definition-shaped occurrence is required (``def``/``class`` or an assignment)
    so a mention in a comment/docstring does not count as the definition.
    """
    if path.suffix != ".py":
        return True
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    token = symbol.split(".")[-1]
    if not token:
        return False
    def_re = re.compile(
        rf"(?:^|\n)\s*(?:(?:async\s+)?def\s+{re.escape(token)}\b|class\s+{re.escape(token)}\b)"
    )
    assign_re = re.compile(rf"(?:^|\n)\s*{re.escape(token)}\s*(?::[^=\n]+)?=")
    return bool(def_re.search(text) or assign_re.search(text))


def find_broken_anchors(
    root: Path,
) -> tuple[list[tuple[Path, str]], list[tuple[Path, str]], int]:
    """Return ``(errors, warnings, checked)`` for wiki symbol anchors under *root*.

    ``errors`` are anchors whose file is missing or whose symbol is not defined
    (or a legacy line anchor in hsync-common) — fatal. ``warnings`` are legacy
    line anchors in the not-yet-migrated sibling wikis — non-fatal.
    """
    errors: list[tuple[Path, str]] = []
    warnings: list[tuple[Path, str]] = []
    checked = 0

    for md_file in iter_markdown_files(root):
        if not _is_wiki_file(md_file, root):
            continue
        enforced = _is_enforced_file(md_file, root)
        project = _project_base(md_file)
        if project is None:
            continue
        current_project = project.name
        try:
            text = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover - I/O guard
            continue

        for raw in _ANCHOR_SPAN_RE.findall(text):
            span = raw.strip()
            if _LEGACY_LINE_PATTERN.match(span):
                if enforced:
                    errors.append((md_file, span))
                else:
                    warnings.append((md_file, span))
                continue

            # Symbol anchors are only enforced for migrated projects.
            if not enforced:
                continue

            match = _ANCHOR_PATTERN.match(span)
            if not match:
                continue
            rel, symbol = match.group(1), match.group(2)
            anchor_project = _anchor_project(rel)
            if anchor_project is not None and anchor_project != current_project:
                # Cross-project anchor: not validated in this repo's scan.
                continue
            anchor_file = _resolve_anchor_file(project, rel)
            if anchor_file is None:
                errors.append((md_file, span))
                continue
            checked += 1
            if not _symbol_present(anchor_file, symbol):
                errors.append((md_file, span))

    return errors, warnings, checked


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    roots = [Path(a).resolve() for a in args] if args else [REPO_ROOT]

    broken: list[tuple[Path, str]] = []
    checked = 0
    anchor_errors: list[tuple[Path, str]] = []
    anchor_warnings: list[tuple[Path, str]] = []
    anchor_checked = 0
    for root in roots:
        root_broken, root_checked = find_broken_links(root)
        broken.extend(root_broken)
        checked += root_checked
        errs, warns, achecked = find_broken_anchors(root)
        anchor_errors.extend(errs)
        anchor_warnings.extend(warns)
        anchor_checked += achecked

    if anchor_warnings:
        print(f"Wiki anchor warnings (legacy line anchors, migrate later): {len(anchor_warnings)}")
        for md_file, anchor in anchor_warnings:
            print(f"  {md_file} -> {anchor}")
        print()

    if broken or anchor_errors:
        if broken:
            print(f"Broken relative links: {len(broken)} (checked {checked})\n")
            for md_file, target in broken:
                print(f"  {md_file} -> {target}")
            print()
        if anchor_errors:
            print(f"Broken wiki anchors: {len(anchor_errors)} (checked {anchor_checked})\n")
            for md_file, anchor in anchor_errors:
                print(f"  {md_file} -> {anchor}")
        return 1

    print(
        f"docs-link-check OK: {checked} relative links valid, {anchor_checked} wiki anchors valid."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
