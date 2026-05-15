"""Tests for hsync_common.path_validation."""

import tempfile

import pytest

from hsync_common.path_validation import (
    FORBIDDEN_FILENAME_CHARS,
    FORBIDDEN_PATH_CHARS,
    PROBLEMATIC_TRAILING_CHARS,
    RESERVED_FILENAMES,
    has_control_chars,
    has_forbidden_chars,
    has_problematic_trailing,
    is_reserved_name,
    is_safe_path_component,
    is_valid_filename,
    is_valid_path,
    sanitize_filename,
)


class TestForbiddenChars:
    def test_has_forbidden_chars_detects_slash(self):
        assert has_forbidden_chars("foo/bar", FORBIDDEN_FILENAME_CHARS) is True

    def test_has_forbidden_chars_clean_name(self):
        assert has_forbidden_chars("hello_world.txt", FORBIDDEN_FILENAME_CHARS) is False

    def test_has_forbidden_chars_nul(self):
        assert has_forbidden_chars("foo\x00bar", FORBIDDEN_FILENAME_CHARS) is True

    def test_path_chars_allows_slash(self):
        assert has_forbidden_chars("some/path", FORBIDDEN_PATH_CHARS) is False

    def test_path_chars_forbids_backslash(self):
        assert has_forbidden_chars("some\\path", FORBIDDEN_PATH_CHARS) is True


class TestControlChars:
    def test_detects_control_char(self):
        assert has_control_chars("foo\x01bar") is True

    def test_clean_name_no_control_chars(self):
        assert has_control_chars("normal_file.txt") is False

    def test_tab_is_control(self):
        assert has_control_chars("foo\tbar") is True

    def test_nul_not_in_range_1_31(self):
        # NUL is \x00, range is 1-31, so not caught here
        assert has_control_chars("foo\x00bar") is False


class TestReservedNames:
    def test_nul_is_reserved(self):
        assert is_reserved_name("NUL") is True

    def test_com1_is_reserved(self):
        assert is_reserved_name("COM1") is True

    def test_lpt9_is_reserved(self):
        assert is_reserved_name("LPT9") is True

    def test_reserved_case_insensitive(self):
        assert is_reserved_name("con") is True
        assert is_reserved_name("Con") is True

    def test_reserved_with_extension(self):
        assert is_reserved_name("NUL.txt") is True

    def test_normal_name_not_reserved(self):
        assert is_reserved_name("document.txt") is False


class TestProblematicTrailing:
    def test_trailing_space(self):
        assert has_problematic_trailing("file ") is True

    def test_trailing_dot(self):
        assert has_problematic_trailing("file.") is True

    def test_clean_name(self):
        assert has_problematic_trailing("file.txt") is False

    def test_empty_name(self):
        assert has_problematic_trailing("") is False


class TestIsSafePathComponent:
    def test_simple_name(self):
        assert is_safe_path_component("hello.txt") is True

    def test_traversal_dotdot(self):
        assert is_safe_path_component("../secret") is False

    def test_absolute_path(self):
        assert is_safe_path_component("/etc/passwd") is False

    def test_windows_drive(self):
        assert is_safe_path_component("C:/Windows") is False

    def test_empty(self):
        assert is_safe_path_component("") is False

    def test_subdir(self):
        assert is_safe_path_component("subdir/file.txt") is True


class TestIsValidFilename:
    def test_valid_simple(self):
        assert is_valid_filename("hello.txt") is True

    def test_empty_invalid(self):
        assert is_valid_filename("") is False

    def test_slash_invalid(self):
        assert is_valid_filename("foo/bar.txt") is False

    def test_control_char_invalid(self):
        assert is_valid_filename("foo\x01bar") is False

    def test_reserved_name_invalid(self):
        assert is_valid_filename("NUL") is False
        assert is_valid_filename("NUL.txt") is False

    def test_trailing_space_invalid(self):
        assert is_valid_filename("file ") is False

    def test_trailing_dot_invalid(self):
        assert is_valid_filename("file.") is False

    def test_traversal_invalid(self):
        assert is_valid_filename("../escape") is False

    def test_unicode_valid(self):
        assert is_valid_filename("résumé.pdf") is True


class TestIsValidPath:
    def test_empty_path_is_valid(self, tmp_path):
        assert is_valid_path("", str(tmp_path)) is True

    def test_safe_relative_path(self, tmp_path):
        assert is_valid_path("subdir/file.txt", str(tmp_path)) is True

    def test_traversal_attempt(self, tmp_path):
        assert is_valid_path("../../etc/passwd", str(tmp_path)) is False


class TestSanitizeFilename:
    def test_slash_replaced(self):
        result = sanitize_filename("foo/bar.txt")
        assert "/" not in result

    def test_control_char_replaced(self):
        result = sanitize_filename("foo\x01bar.txt")
        assert "\x01" not in result

    def test_empty_returns_unnamed(self):
        assert sanitize_filename("") == "unnamed"

    def test_reserved_name_replaced(self):
        result = sanitize_filename("NUL")
        assert result == "unnamed"

    def test_trailing_space_stripped(self):
        result = sanitize_filename("file ")
        assert not result.endswith(" ")

    def test_long_filename_truncated(self):
        long_name = "a" * 300 + ".txt"
        result = sanitize_filename(long_name)
        assert len(result) <= 255
