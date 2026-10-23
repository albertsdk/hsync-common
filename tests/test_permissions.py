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
