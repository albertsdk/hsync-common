"""Tests for hsync_common.path_validation."""

from hsync_common.path_validation import (
    FORBIDDEN_FILENAME_CHARS,
    FORBIDDEN_PATH_CHARS,
    INTERNAL_FILENAMES,
    has_control_chars,
    has_dotdot_component,
    has_forbidden_chars,
    has_problematic_trailing,
    is_internal_name,
    is_reserved_name,
    is_safe_path_component,
    is_safe_symlink_target,
    is_valid_bucket_name,
    is_valid_filename,
    resolve_within,
    safe_resolve_path,
    sanitize_filename,
    validate_remote_relpath,
    wire_relpaths,
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


class TestHasDotdotComponent:
    def test_plain_name(self):
        assert has_dotdot_component("hello.txt") is False

    def test_embedded_double_dots(self):
        assert has_dotdot_component("lib..1.dylib") is False
        assert has_dotdot_component("a..b.txt") is False

    def test_triple_dots(self):
        assert has_dotdot_component("...") is False

    def test_dotdot_component(self):
        assert has_dotdot_component("..") is True
        assert has_dotdot_component("../secret") is True
        assert has_dotdot_component("foo/../bar") is True

    def test_dotdot_backslash(self):
        assert has_dotdot_component("foo\\..\\bar") is True


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

    def test_double_dots_in_filename(self):
        # ".." embedded in a name (not a component) must be allowed
        assert is_safe_path_component("lib..1.dylib") is True
        assert is_safe_path_component("a..b.txt") is True
        assert is_safe_path_component("v1.2.3.tar.gz") is True

    def test_triple_dots_filename(self):
        assert is_safe_path_component("...") is True

    def test_traversal_component_in_subdir(self):
        assert is_safe_path_component("foo/../bar") is False
        assert is_safe_path_component("foo/../../bar") is False

    def test_traversal_mixed_separators(self):
        # Backslash-normalized traversal must still be blocked
        assert is_safe_path_component("foo/..\\bar") is False
        assert is_safe_path_component("..\\secret") is False


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

    def test_long_multibyte_filename_truncated_without_splitting_utf8(self):
        # Each 'é' is 2 UTF-8 bytes: 200 of them exceed the 255-byte limit.
        # Byte-aware truncation must not split a multi-byte sequence (which
        # would produce an invalid encoding) and must preserve the extension.
        result = sanitize_filename("é" * 200 + ".txt")
        assert result.endswith(".txt")
        assert len(result.encode("utf-8")) <= 255
        # Would raise UnicodeDecodeError/encode implicitly fails on a split
        # sequence if the implementation sliced characters instead of bytes.
        assert result.encode("utf-8").decode("utf-8") == result

    def test_long_extensionless_name_truncated(self):
        result = sanitize_filename("a" * 300)
        assert len(result.encode("utf-8")) <= 255
        assert result != "unnamed"


class TestIsValidBucketName:
    def test_valid_names(self):
        assert is_valid_bucket_name("bucket")
        assert is_valid_bucket_name("My-Bucket_1")
        assert is_valid_bucket_name("a")
        assert is_valid_bucket_name("A1")

    def test_invalid_names(self):
        assert not is_valid_bucket_name("")
        assert not is_valid_bucket_name("-bucket")
        assert not is_valid_bucket_name("bucket-")
        assert not is_valid_bucket_name("_bucket")
        assert not is_valid_bucket_name("bad/name")
        assert not is_valid_bucket_name("dot.name")


class TestSafeResolvePath:
    def test_empty_returns_none(self):
        assert safe_resolve_path("") is None

    def test_dotdot_rejected(self):
        assert safe_resolve_path("../etc/passwd") is None
        assert safe_resolve_path("foo/../../bar") is None

    def test_nul_stripped_and_resolved(self, tmp_path):
        target = tmp_path / "file.txt"
        result = safe_resolve_path(f"{target}\x00")
        assert result == str(target.resolve())

    def test_absolute_rejected_when_disallowed(self, tmp_path):
        assert safe_resolve_path(str(tmp_path), allow_absolute=False) is None

    def test_relative_path_resolved_when_absolute_allowed(self):
        result = safe_resolve_path("subdir/file.txt")
        assert result is not None and result.endswith("subdir/file.txt")


class TestIsInternalName:
    def test_internal_filenames_detected(self):
        for name in INTERNAL_FILENAMES:
            assert is_internal_name(name) is True
            assert is_internal_name(f"sub/dir/{name}") is True

    def test_expected_contents(self):
        assert frozenset({".hsyncignore", ".hsyncstate", ".hsynctombstones"}) == INTERNAL_FILENAMES

    def test_partial_suffix_is_internal(self):
        assert is_internal_name("file.txt.part") is True
        assert is_internal_name("dir/.hsyncstate.part") is True

    def test_hsynckeep_not_internal(self):
        # .hsynckeep legitimately appears in delete events between peers.
        assert is_internal_name(".hsynckeep") is False

    def test_regular_files_not_internal(self):
        assert is_internal_name("document.txt") is False
        assert is_internal_name(".env") is False

    def test_backslash_separators_normalised(self):
        assert is_internal_name("dir\\.hsyncignore") is True

    def test_case_variants_rejected(self):
        # On case-insensitive filesystems (Windows, default macOS) these are
        # the SAME files as their lowercase counterparts: a remote peer must
        # not overwrite the victim's engine artifacts via a case variant.
        assert is_internal_name(".HSYNCIGNORE") is True
        assert is_internal_name(".HsyncState") is True
        assert is_internal_name("sub/dir/.HSYNCTOMBSTONES") is True
        assert is_internal_name("file.txt.PART") is True

    def test_validate_remote_relpath_rejects_case_variants(self):
        assert validate_remote_relpath(".HSYNCIGNORE") is None
        assert validate_remote_relpath("dir/.HsyncState") is None
        assert validate_remote_relpath("report.pdf.PART") is None


class TestValidateRemoteRelpath:
    def test_valid_relative_paths(self):
        assert validate_remote_relpath("a/b/c.txt") == "a/b/c.txt"
        assert validate_remote_relpath("file.txt") == "file.txt"
        assert validate_remote_relpath("dir/") == "dir"

    def test_empty_and_non_string_rejected(self):
        assert validate_remote_relpath("") is None
        assert validate_remote_relpath(None) is None  # type: ignore[reportArgumentType]
        assert validate_remote_relpath(123) is None  # type: ignore[reportArgumentType]
        assert validate_remote_relpath("/") is None

    def test_traversal_rejected(self):
        assert validate_remote_relpath("../evil.txt") is None
        assert validate_remote_relpath("a/../../evil.txt") is None
        assert validate_remote_relpath("..") is None
        assert validate_remote_relpath("a/./b") is None

    def test_absolute_and_drive_letter_rejected(self):
        assert validate_remote_relpath("/etc/passwd") is None
        assert validate_remote_relpath("C:/windows/win.ini") is None
        assert validate_remote_relpath("C:\\windows\\win.ini") is None

    def test_backslash_rejected(self):
        # Windows separator differential: a Linux-legal name must not reach
        # a Windows peer where it would resolve outside the bucket.
        assert validate_remote_relpath("..\\..\\evil.txt") is None
        assert validate_remote_relpath("dir\\file.txt") is None

    def test_forbidden_and_control_chars_rejected(self):
        assert validate_remote_relpath("a<b>.txt") is None
        assert validate_remote_relpath("a|b.txt") is None
        assert validate_remote_relpath("a\x00b.txt") is None
        assert validate_remote_relpath("a\x1fb.txt") is None

    def test_reserved_names_rejected(self):
        assert validate_remote_relpath("NUL") is None
        assert validate_remote_relpath("dir/COM1.txt") is None

    def test_problematic_trailing_rejected(self):
        assert validate_remote_relpath("file.txt ") is None
        assert validate_remote_relpath("dir./file.txt") is None

    def test_internal_names_rejected(self):
        assert validate_remote_relpath(".hsyncignore") is None
        assert validate_remote_relpath("sub/.hsyncstate") is None
        assert validate_remote_relpath("file.txt.part") is None


class TestResolveWithin:
    def test_confines_to_base(self, tmp_path):
        result = resolve_within(str(tmp_path), "a/b.txt")
        assert result == str((tmp_path / "a" / "b.txt").resolve())

    def test_traversal_rejected(self, tmp_path):
        assert resolve_within(str(tmp_path), "../outside.txt") is None

    def test_symlink_escape_rejected(self, tmp_path):
        outside = tmp_path.parent / "outside"
        outside.mkdir(exist_ok=True)
        link = tmp_path / "link"
        link.symlink_to(outside, target_is_directory=True)
        assert resolve_within(str(tmp_path), "link/secret.txt") is None

    def test_internal_name_rejected(self, tmp_path):
        assert resolve_within(str(tmp_path), ".hsyncignore") is None


class TestWireRelpaths:
    """SSOT extraction of every path key carried by an event payload."""

    def test_single_keys(self):
        assert wire_relpaths({"filepath": "a/b.txt"}) == ["a/b.txt"]
        assert wire_relpaths({"path": "a"}) == ["a"]

    def test_both_keys_returned(self):
        # The smuggling case: both keys present — the caller must see both.
        assert wire_relpaths({"filepath": "ok.txt", "path": "../evil"}) == ["ok.txt", "../evil"]

    def test_empty_and_non_string_ignored(self):
        assert wire_relpaths({"filepath": "", "path": None}) == []
        assert wire_relpaths({"filepath": 123}) == []
        assert wire_relpaths({}) == []


class TestIsSafeSymlinkTarget:
    def test_relative_target_within_bucket(self, tmp_path):
        assert is_safe_symlink_target(str(tmp_path / "sub" / "ln"), "../f.txt", str(tmp_path))

    def test_absolute_target_within_bucket(self, tmp_path):
        target = tmp_path / "f.txt"
        assert is_safe_symlink_target(str(tmp_path / "ln"), str(target), str(tmp_path))

    def test_absolute_target_outside_bucket(self, tmp_path):
        assert not is_safe_symlink_target(str(tmp_path / "ln"), "/etc/passwd", str(tmp_path))

    def test_relative_target_escaping_bucket(self, tmp_path):
        assert not is_safe_symlink_target(str(tmp_path / "ln"), "../../outside.txt", str(tmp_path))

    def test_empty_target_rejected(self, tmp_path):
        assert not is_safe_symlink_target(str(tmp_path / "ln"), "", str(tmp_path))

    def test_malformed_target_returns_false_not_raises(self, tmp_path):
        # A remote symlink event with an unresolvable target (embedded NUL
        # byte) must be rejected, not blow up the event-apply path.
        assert not is_safe_symlink_target(str(tmp_path / "ln"), "x\x00y", str(tmp_path))
        assert not is_safe_symlink_target(str(tmp_path / "ln"), "\x00", str(tmp_path))
