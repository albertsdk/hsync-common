"""Tests for hsync_common models (File, Dir, Symlink, Event, SyncAction)."""

import pytest

from hsync_common.models.dir import Dir, is_hidden_dir
from hsync_common.models.file import (
    is_hidden_file,
)
from hsync_common.models.symlink import Symlink

# =============================================================================
# Dir model
# =============================================================================


class TestIsHiddenDir:
    """Default ignore patterns follow the industry standard: only OS cache
    and editor/office temporary files are excluded. Dotfile directories in
    general (.git/, .config/ …) are synchronised normally."""

    def test_dot_dir_not_hidden_by_default(self):
        """Dotfile directories like .git, .config are synced normally."""
        assert is_hidden_dir(".git") is False
        assert is_hidden_dir(".config") is False

    def test_regular_dir_not_hidden(self):
        assert is_hidden_dir("documents") is False

    def test_ds_store_dir_is_hidden(self):
        """A directory named .DS_Store matches the default pattern (gitignore
        patterns match both files and directories unless they end with /)."""
        assert is_hidden_dir(".DS_Store") is True

    def test_internal_dir_is_hidden(self):
        """Engine-owned directories like .hsyncignore are always excluded."""
        assert is_hidden_dir(".hsyncignore") is True


class TestIsHiddenMatcherAwareness:
    """is_hidden_dir/is_hidden_file consult the active IgnoreMatcher.

    The matcher-aware behaviour now lives in hsync_common, so importing the
    functions from common, client or server yields identical results.
    """

    @pytest.fixture
    def active_secret_matcher(self, tmp_path):
        from hsync_common.constants import HSYNCIGNORE_FILENAME
        from hsync_common.ignore import IgnoreMatcher, set_active_matcher

        (tmp_path / HSYNCIGNORE_FILENAME).write_text("*.secret\nbuild/\n")
        matcher = IgnoreMatcher(str(tmp_path))
        set_active_matcher(matcher)
        try:
            yield tmp_path
        finally:
            set_active_matcher(None)

    def test_no_matcher_uses_default_patterns(self):
        from hsync_common.ignore import set_active_matcher

        set_active_matcher(None)
        # Default patterns still exclude OS cache files
        assert is_hidden_file(".DS_Store") is True
        assert is_hidden_file("foo.secret") is False
        assert is_hidden_file(".env") is False

    def test_file_consults_active_matcher(self, active_secret_matcher):
        assert is_hidden_file("foo.secret") is True
        assert is_hidden_file("foo.txt") is False

    def test_dir_consults_active_matcher(self, active_secret_matcher):
        assert is_hidden_dir("build") is True
        assert is_hidden_dir("documents") is False

    def test_matcher_dotfiles_not_excluded_by_default(self, active_secret_matcher):
        # Dotfiles are NOT excluded by default (industry standard).
        assert is_hidden_file(".env") is False
        assert is_hidden_dir(".cache") is False


class TestDirModel:
    def test_init(self):
        d = Dir(path="/tmp/sync", permissions="755")
        assert d.path == "/tmp/sync"

    def test_to_dict(self):
        d = Dir(path="/tmp/sync")
        result = d.to_dict()
        assert "path" in result
        assert "permissions" in result

    def test_get_existing(self, tmp_path):
        d = Dir.get(str(tmp_path))
        assert d is not None

    def test_get_nonexistent(self):
        assert Dir.get("/nonexistent/1234") is None

    def test_from_dict(self):
        d = Dir.from_dict({"path": "subdir"}, localpath="/base", strip_localpath=False)
        assert "/base" in d.path  # type: ignore[reportOperatorIssue]

    def test_repr_contains_fields(self):
        d = Dir(path="/tmp/sync", permissions="755")
        text = repr(d)
        assert "Dir(" in text
        assert "/tmp/sync" in text
        assert "755" in text


# =============================================================================
# Symlink model
# =============================================================================


class TestSymlinkModel:
    def test_init(self):
        s = Symlink(filepath="/tmp/link.txt", target="/tmp/real.txt")
        assert s.name == "link.txt"
        assert s.target == "/tmp/real.txt"

    def test_target_empty_rejected(self):
        with pytest.raises(ValueError):
            Symlink(filepath="/tmp/link.txt", target="")

    def test_target_null_byte_rejected(self):
        with pytest.raises(ValueError, match="null byte"):
            Symlink(filepath="/tmp/link.txt", target="a\x00b")

    def test_target_over_long_rejected(self):
        with pytest.raises(ValueError, match="maximum length"):
            Symlink(filepath="/tmp/link.txt", target="a" * 4097)

    def test_to_dict(self):
        s = Symlink(filepath="/tmp/link.txt", target="/tmp/real.txt")
        d = s.to_dict()
        assert d["type"] == "symlink"
        assert "filepath" in d
        assert "target" in d

    def test_from_dict(self):
        s = Symlink.from_dict({"filepath": "/a/link", "target": "/b/real"}, strip_dir_prefix=False)
        assert s.filepath == "/a/link"
        assert s.target == "/b/real"

    def test_get_nonexistent(self):
        assert Symlink.get("/nonexistent/link") is None

    def test_get_real_symlink(self, tmp_path):
        target = tmp_path / "target.txt"
        target.write_text("data")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        result = Symlink.get(str(link))
        assert result is not None
        assert result.target == str(target)

    def test_get_regular_file_returns_none(self, tmp_path):
        # An existing path that is not a symlink must be rejected.
        regular = tmp_path / "regular.txt"
        regular.write_text("data")
        assert Symlink.get(str(regular)) is None

    def test_get_oserror_returns_none(self, tmp_path, monkeypatch):
        target = tmp_path / "t.txt"
        target.write_text("data")
        link = tmp_path / "l.txt"
        link.symlink_to(target)

        import hsync_common.models.symlink as symlink_mod

        def _boom(*_args, **_kwargs):
            raise OSError("readlink failed")

        monkeypatch.setattr(symlink_mod, "readlink", _boom)
        assert Symlink.get(str(link)) is None

    def test_repr_contains_fields(self):
        s = Symlink(filepath="/tmp/link.txt", target="/tmp/real.txt")
        text = repr(s)
        assert "Symlink(" in text
        assert "/tmp/link.txt" in text
        assert "/tmp/real.txt" in text


# =============================================================================
