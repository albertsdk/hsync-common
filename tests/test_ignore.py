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
    def test_no_ignore_file_defaults_to_hidden_only(self, bucket):
        m = IgnoreMatcher(str(bucket))
        assert m.matches(".cache") is True
        assert m.matches("document.txt") is False
        assert m.matches("backup.bak") is True

    def test_hsynckeep_always_kept(self, bucket):
        _write_ignore(bucket, "*\n")
        m = IgnoreMatcher(str(bucket))
        assert m.matches(HSYNCKEEP_FILENAME) is False

    def test_include_hidden_disables_default_patterns(self, bucket):
        m = IgnoreMatcher(str(bucket), include_hidden=True)
        assert m.matches(".cache") is False
        assert m.matches("file.bak") is False

    def test_partial_file_always_ignored(self, bucket):
        m = IgnoreMatcher(str(bucket))
        assert m.matches("document.txt.part") is True

    def test_partial_file_ignored_even_with_include_hidden(self, bucket):
        # In-progress transfer artifacts must never sync, regardless of flags.
        m = IgnoreMatcher(str(bucket), include_hidden=True)
        assert m.matches("document.txt.part") is True
        assert m.matches("sub/document.txt.part") is True


class TestGitignoreSyntax:
    def test_basic_glob(self, bucket):
        _write_ignore(bucket, "*.log\nnode_modules/\n")
        m = IgnoreMatcher(str(bucket), include_hidden=True)
        assert m.matches("server.log") is True
        assert m.matches("logs/app.log") is True
        assert m.matches("node_modules", is_dir=True) is True
        assert m.matches("source.py") is False

    def test_negation_reincludes(self, bucket):
        _write_ignore(bucket, "*.log\n!important.log\n")
        m = IgnoreMatcher(str(bucket), include_hidden=True)
        assert m.matches("debug.log") is True
        assert m.matches("important.log") is False

    def test_directory_only_pattern(self, bucket):
        _write_ignore(bucket, "build/\n")
        m = IgnoreMatcher(str(bucket), include_hidden=True)
        assert m.matches("build", is_dir=True) is True
        # File named "build" is NOT matched by "build/"
        assert m.matches("build", is_dir=False) is False

    def test_double_star_recursive(self, bucket):
        _write_ignore(bucket, "**/cache/**\n")
        m = IgnoreMatcher(str(bucket), include_hidden=True)
        assert m.matches("foo/cache/x.bin") is True
        assert m.matches("foo/bar/cache/baz/q.bin") is True


class TestPathNormalisation:
    def test_absolute_path_resolved_to_relative(self, bucket):
        _write_ignore(bucket, "secret.txt\n")
        m = IgnoreMatcher(str(bucket), include_hidden=True)
        assert m.matches(str(bucket / "secret.txt")) is True

    def test_root_anchored_pattern_only_matches_at_root(self, bucket):
        # Leading "/" anchors the pattern to the bucket root
        _write_ignore(bucket, "/secret.txt\n")
        m = IgnoreMatcher(str(bucket), include_hidden=True)
        assert m.matches("secret.txt") is True
        # Same basename in a subdirectory must NOT match
        assert m.matches("subdir/secret.txt") is False


class TestExtraPatterns:
    def test_extra_patterns_layered_on_top(self, bucket):
        m = IgnoreMatcher(str(bucket), include_hidden=True, extra_patterns=["*.private"])
        assert m.matches("notes.private") is True


class TestReload:
    def test_reload_picks_up_changes(self, bucket):
        m = IgnoreMatcher(str(bucket), include_hidden=True)
        assert m.matches("new.tmp") is False
        _write_ignore(bucket, "*.tmp\n")
        m.reload()
        assert m.matches("new.tmp") is True


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
        m = IgnoreMatcher(str(bucket), include_hidden=True)
        set_active_matcher(m)
        try:
            assert should_skip("foo.secret") is True
            assert should_skip("foo.txt") is False
        finally:
            set_active_matcher(None)

    def test_should_skip_falls_back_to_hidden_check(self):
        set_active_matcher(None)
        assert should_skip(".cache") is True
        assert should_skip("regular.txt") is False
