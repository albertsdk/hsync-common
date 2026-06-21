"""Tests for hsync_common.permissions."""

import pytest

from hsync_common.permissions import (
    REMOTE_PERMISSION_MASK,
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
