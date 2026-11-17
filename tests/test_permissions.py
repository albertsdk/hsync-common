"""Tests for hsync_common.permissions."""

import os

import pytest

from hsync_common.permissions import (
    REMOTE_PERMISSION_MASK,
    apply_remote_permissions,
    is_valid_octal_permissions,
    mode_to_octal,
    octal_to_mode,
    sanitize_remote_permissions,
)


class TestOctalConversion:
    def test_mode_roundtrip(self):
        assert mode_to_octal(0o644) == "644"
        assert octal_to_mode("644") == 0o644

    def test_special_bits_preserved_locally(self):
        # Local reads keep setuid/setgid/sticky bits (4-digit form).
        assert mode_to_octal(0o4755) == "4755"
        assert octal_to_mode("4755") == 0o4755


class TestSanitizeRemotePermissions:
    def test_strips_setuid(self):
        assert sanitize_remote_permissions("4755") == "755"

    def test_strips_setgid_and_sticky(self):
        assert sanitize_remote_permissions("2750") == "750"
        assert sanitize_remote_permissions("1777") == "777"
        assert sanitize_remote_permissions("7777") == "777"

    def test_plain_permissions_unchanged(self):
        assert sanitize_remote_permissions("644") == "644"
        assert sanitize_remote_permissions("755") == "755"
        assert sanitize_remote_permissions("600") == "600"

    def test_mask_is_rwx_only(self):
        assert REMOTE_PERMISSION_MASK == 0o777

    def test_invalid_input_raises(self):
        for bad in ("", "888", "abc", "12345", "4755 "):
            assert not is_valid_octal_permissions(bad)
            with pytest.raises(ValueError):
                sanitize_remote_permissions(bad)


class TestApplyRemotePermissions:
    """The single receiver-side applier shared by client and server."""

    def test_strips_special_bits_and_applies_the_mode(self, tmp_path):
        target = tmp_path / "f.txt"
        target.write_bytes(b"x")

        applied = apply_remote_permissions(str(target), "4755")

        assert applied == "755"
        assert mode_to_octal(target.stat().st_mode) == "755"

    def test_directory_mode_keeps_the_owner_floor(self, tmp_path):
        directory = tmp_path / "d"
        directory.mkdir()

        applied = apply_remote_permissions(str(directory), "000", directory=True)

        assert applied == "000"
        # A peer-supplied 000 must never lock the owner out of its own tree.
        assert mode_to_octal(directory.stat().st_mode) == "700"

    def test_skip_if_equal_reports_no_change(self, tmp_path):
        target = tmp_path / "f.txt"
        target.write_bytes(b"x")
        os.chmod(target, 0o644)

        assert apply_remote_permissions(str(target), "644", skip_if_equal=True) is None
        assert apply_remote_permissions(str(target), "600", skip_if_equal=True) == "600"

    def test_missing_path_surfaces_the_os_error(self, tmp_path):
        with pytest.raises(OSError):
            apply_remote_permissions(str(tmp_path / "absent"), "644")

    def test_invalid_octal_is_rejected_before_touching_the_file(self, tmp_path):
        target = tmp_path / "f.txt"
        target.write_bytes(b"x")
        os.chmod(target, 0o644)

        with pytest.raises(ValueError):
            apply_remote_permissions(str(target), "999")

        assert mode_to_octal(target.stat().st_mode) == "644"


class TestWindowsReadonlyMapping:
    """NTFS carries only the read-only attribute; the wire stays POSIX.

    The Windows branch is driven by the module's ``_IS_WINDOWS`` seam so it can
    be exercised on any host.
    """

    def test_get_permissions_reports_canonical_modes(self, tmp_path, monkeypatch):
        import hsync_common.permissions as perms

        monkeypatch.setattr(perms, "_IS_WINDOWS", True)
        target = tmp_path / "f.bin"
        target.write_bytes(b"x")
        os.chmod(target, 0o644)
        assert perms.get_permissions(str(target)) == "644"

        os.chmod(target, 0o444)
        assert perms.get_permissions(str(target)) == "444"

        directory = tmp_path / "d"
        directory.mkdir()
        assert perms.get_permissions(str(directory)) == "755"

    def test_apply_maps_owner_write_to_readonly(self, monkeypatch, tmp_path):
        import stat

        import hsync_common.permissions as perms

        calls: list[int] = []
        monkeypatch.setattr(perms, "_IS_WINDOWS", True)
        monkeypatch.setattr(perms, "chmod", lambda _p, mode: calls.append(mode))
        monkeypatch.setattr(perms, "get_permissions", lambda _p: "644")
        target = str(tmp_path / "f.bin")

        assert perms.apply_remote_permissions(target, "600") == "644"
        assert calls == [stat.S_IWRITE]

        calls.clear()
        assert perms.apply_remote_permissions(target, "444") == "444"
        assert calls == [stat.S_IREAD]

    def test_directories_are_never_made_read_only(self, monkeypatch, tmp_path):
        import stat

        import hsync_common.permissions as perms

        calls: list[int] = []
        monkeypatch.setattr(perms, "_IS_WINDOWS", True)
        monkeypatch.setattr(perms, "chmod", lambda _p, mode: calls.append(mode))
        monkeypatch.setattr(perms, "get_permissions", lambda _p: "755")

        assert perms.apply_remote_permissions(str(tmp_path / "d"), "444", directory=True) == "755"
        assert calls == [stat.S_IWRITE]

    @pytest.mark.parametrize(
        ("permissions", "expected"),
        [("600", True), ("644", True), ("444", False), ("555", False), ("bogus", False)],
    )
    def test_has_owner_write(self, permissions, expected):
        from hsync_common.permissions import has_owner_write

        assert has_owner_write(permissions) is expected
