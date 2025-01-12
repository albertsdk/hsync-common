# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for hsync_common.ignore.IgnoreMatcher."""

import tempfile
from pathlib import Path

import pytest

from hsync_common.constants import HSYNCIGNORE_FILENAME, HSYNCKEEP_FILENAME
from hsync_common.ignore import (
    IgnoreMatcher,
    get_active_matcher,
    set_active_matcher,
    should_skip,
)


@pytest.fixture
def bucket():
    """Yield a temporary bucket root used for matcher tests."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _write_ignore(bucket: Path, content: str) -> None:
    (bucket / HSYNCIGNORE_FILENAME).write_text(content, encoding="utf-8")


class TestDefaults:
    """Built-in default patterns are always active (industry standard).

    Only OS cache files and editor/office temporary files are excluded.
    Dotfiles in general (.env, .config, .git …) are synchronised normally.
    """

    def test_no_ignore_file_excludes_os_cache(self, bucket):
        m = IgnoreMatcher(str(bucket))
        assert m.matches(".DS_Store") is True
        assert m.matches("Thumbs.db") is True
        assert m.matches("document.txt") is False

    def test_no_ignore_file_syncs_dotfiles(self, bucket):
        """Dotfiles are NOT excluded by default (industry standard)."""
        m = IgnoreMatcher(str(bucket))
        assert m.matches(".env") is False
        assert m.matches(".config") is False
        assert m.matches(".gitignore") is False

    def test_hsynckeep_always_kept(self, bucket):
        _write_ignore(bucket, "*\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches(HSYNCKEEP_FILENAME) is False

    def test_partial_file_always_ignored(self, bucket):
        m = IgnoreMatcher(str(bucket))
        assert m.matches("document.txt.part") is True

    def test_editor_safe_save_temp_ignored(self, bucket):
        """GNOME GIO safe-save temp files (.goutputstream-*) are excluded."""
        m = IgnoreMatcher(str(bucket))
        assert m.matches(".goutputstream-ABCD12") is True
        assert m.matches("sub/.goutputstream-XYZ") is True
        # The final file is NOT ignored
        assert m.matches("hello.txt") is False

    def test_browser_download_temp_ignored(self, bucket):
        """Chromium browser download temp files (*.crdownload) are excluded."""
        m = IgnoreMatcher(str(bucket))
        assert m.matches("report.crdownload") is True
        assert m.matches("sub/large-file.zip.crdownload") is True
        # The final file (after download completes) is NOT ignored
        assert m.matches("report.pdf") is False
        assert m.matches("large-file.zip") is False

    def test_internal_files_always_ignored(self, bucket):
        # Engine-owned state files must never be synced: a peer that could
        # push them would rewrite the victim's sync behaviour via the sync
        # channel itself (poisoned .hsyncignore / .hsynctombstones).
        m = IgnoreMatcher(str(bucket))
        assert m.matches(".hsyncignore") is True
        assert m.matches(".hsyncstate") is True
        assert m.matches(".hsynctombstones") is True
        assert m.matches("sub/.hsyncignore") is True

    def test_default_patterns_cannot_be_disabled(self, bucket):
        """Default patterns are always active — there is no way to disable them."""
        m = IgnoreMatcher(str(bucket))
        assert m.matches(".DS_Store") is True
        assert m.matches("Thumbs.db") is True
        assert m.matches("backup.bak") is True
        assert m.matches("temp.tmp") is True


class TestDotfilePatterns:
    """_to_relative must strip only leading "./", never the dot of dotfiles."""

    def test_pattern_matches_dotfile(self, bucket):
        _write_ignore(bucket, ".env\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches(".env") is True
        assert m.matches("document.txt") is False

    def test_pattern_matches_dotfile_with_relative_prefix(self, bucket):
        _write_ignore(bucket, ".secret\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches("./.secret") is True

    def test_dotfile_glob(self, bucket):
        _write_ignore(bucket, ".*.log\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches(".debug.log") is True


class TestGitignoreSyntax:
    def test_basic_glob(self, bucket):
        _write_ignore(bucket, "*.log\nnode_modules/\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches("server.log") is True
        assert m.matches("logs/app.log") is True
        assert m.matches("node_modules", is_dir=True) is True
        assert m.matches("source.py") is False

    def test_negation_reincludes(self, bucket):
        _write_ignore(bucket, "*.log\n!important.log\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches("debug.log") is True
        assert m.matches("important.log") is False

    def test_negation_reincludes_default_pattern(self, bucket):
        """A user can re-include a file excluded by the default patterns."""
        _write_ignore(bucket, "!*.tmp\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches("temp.tmp") is False

    def test_directory_only_pattern(self, bucket):
        _write_ignore(bucket, "build/\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches("build", is_dir=True) is True
        # File named "build" is NOT matched by "build/"
        assert m.matches("build", is_dir=False) is False

    def test_double_star_recursive(self, bucket):
        _write_ignore(bucket, "**/cache/**\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches("foo/cache/x.bin") is True
        assert m.matches("foo/bar/cache/baz/q.bin") is True


class TestPathNormalisation:
    def test_absolute_path_resolved_to_relative(self, bucket):
        _write_ignore(bucket, "secret.txt\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches(str(bucket / "secret.txt")) is True

    def test_root_anchored_pattern_only_matches_at_root(self, bucket):
        # Leading "/" anchors the pattern to the bucket root
        _write_ignore(bucket, "/secret.txt\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches("secret.txt") is True
        # Same basename in a subdirectory must NOT match
        assert m.matches("subdir/secret.txt") is False


class TestExtraPatterns:
    def test_extra_patterns_layered_on_top(self, bucket):
        m = IgnoreMatcher(str(bucket), extra_patterns=["*.private"])
        assert m.matches("notes.private") is True


class TestReload:
    def test_reload_picks_up_changes(self, bucket):
        m = IgnoreMatcher(str(bucket))
        assert m.matches("new.tmp") is True  # excluded by default
        _write_ignore(bucket, "!*.tmp\n")
        m.reload()
        assert m.matches("new.tmp") is False  # re-included by .hsyncignore


class TestComments:
    """Verify that comment lines (starting with '#') are properly ignored."""

    def test_comment_lines_are_ignored(self, bucket):
        """Patterns after comment lines should still work."""
        _write_ignore(bucket, "# Ignore log files\n*.log\n# Ignore temp files\n*.tmp\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches("server.log") is True
        assert m.matches("data.tmp") is True
        assert m.matches("important.txt") is False

    def test_comment_with_leading_whitespace(self, bucket):
        """Comments with leading spaces/tabs should still be treated as comments."""
        _write_ignore(bucket, "  # This is a comment\n*.log\n\t# Another comment\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches("app.log") is True
        assert m.matches("readme.md") is False

    def test_blank_lines_between_patterns(self, bucket):
        """Blank lines should not affect pattern matching."""
        _write_ignore(bucket, "*.log\n\n*.tmp\n\n\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches("server.log") is True
        assert m.matches("data.tmp") is True
        assert m.matches("readme.md") is False

    def test_only_comments_and_blanks(self, bucket):
        """A file with only comments and blank lines should match nothing extra."""
        _write_ignore(bucket, "# Everything is a comment\n\n  # indented comment\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches("anyfile.txt") is False
        assert m.matches("another.doc") is False

    def test_inline_hash_not_a_comment(self, bucket):
        """A '#' in the middle of a line is literal, not a comment.
        In standard .gitignore, only a '#' at the start of a line
        (possibly after whitespace) is a comment."""
        _write_ignore(bucket, "file#name.log\n")
        m = IgnoreMatcher(str(bucket))
        # The pattern "file#name.log" should literally match a file named "file#name.log"
        assert m.matches("file#name.log") is True
        assert m.matches("file.log") is False

    def test_escaped_hash_is_pattern(self, bucket):
        """A line starting with '\\#' is an escaped hash, treated as a pattern."""
        _write_ignore(bucket, "\\#not_a_comment.log\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches("#not_a_comment.log") is True
        assert m.matches("not_a_comment.log") is False


class TestActiveMatcher:
    def test_set_and_get_active_matcher(self, bucket):
        m = IgnoreMatcher(str(bucket))
        set_active_matcher(m)
        try:
            assert get_active_matcher() is m
        finally:
            set_active_matcher(None)

    def test_should_skip_uses_active_matcher(self, bucket):
        _write_ignore(bucket, "*.secret\n")
        m = IgnoreMatcher(str(bucket))
        set_active_matcher(m)
        try:
            assert should_skip("foo.secret") is True
            assert should_skip("foo.txt") is False
        finally:
            set_active_matcher(None)

    def test_should_skip_falls_back_to_default_patterns(self):
        set_active_matcher(None)
        # Default patterns still exclude OS cache files
        assert should_skip(".DS_Store") is True
        assert should_skip("Thumbs.db") is True
        # Dotfiles are NOT excluded
        assert should_skip(".env") is False
        assert should_skip("regular.txt") is False
