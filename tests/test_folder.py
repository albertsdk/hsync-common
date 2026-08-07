"""Tests for folder-ID marker and state-dir helpers (ADR-0025)."""

import os
import uuid

import pytest

from hsync_common.constants import (
    HSYNC_STATE_DIR_ENV,
    HSYNCFOLDER_FILENAME,
    SYNCSTATE_DB_FILENAME,
)
from hsync_common.models.folder import (
    default_state_dir,
    default_syncstate_db_path,
    ensure_folder_marker,
    is_folder_id,
    read_folder_marker,
    write_folder_marker,
)


class TestIsFolderId:
    def test_accepts_uuidv4(self):
        assert is_folder_id(str(uuid.uuid4())) is True

    def test_rejects_empty_and_garbage(self):
        assert is_folder_id("") is False
        assert is_folder_id("not-a-uuid") is False
        assert is_folder_id(None) is False

    def test_rejects_non_v4(self):
        # Version nibble is 1, not 4.
        assert is_folder_id("11111111-1111-1111-8111-111111111111") is False


class TestFolderMarker:
    def test_ensure_creates_and_rereads(self, tmp_path):
        folder_id = ensure_folder_marker(tmp_path)
        assert is_folder_id(folder_id)
        marker = tmp_path / HSYNCFOLDER_FILENAME
        assert marker.is_file()
        assert marker.read_text(encoding="utf-8") == f"{folder_id}\n"
        assert read_folder_marker(tmp_path) == folder_id
        assert ensure_folder_marker(tmp_path) == folder_id

    def test_write_is_atomic_and_rejects_invalid(self, tmp_path):
        folder_id = str(uuid.uuid4())
        assert write_folder_marker(tmp_path, folder_id) == folder_id
        with pytest.raises(ValueError):
            write_folder_marker(tmp_path, "nope")

    def test_invalid_marker_is_treated_as_absent(self, tmp_path):
        (tmp_path / HSYNCFOLDER_FILENAME).write_text("garbage\n", encoding="utf-8")
        assert read_folder_marker(tmp_path) is None
        new_id = ensure_folder_marker(tmp_path)
        assert is_folder_id(new_id)
        assert read_folder_marker(tmp_path) == new_id

    def test_missing_bucket_is_absent(self, tmp_path):
        assert read_folder_marker(tmp_path / "missing") is None


class TestStateDir:
    def test_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv(HSYNC_STATE_DIR_ENV, str(tmp_path / "state"))
        assert default_state_dir() == tmp_path / "state"
        assert default_syncstate_db_path() == tmp_path / "state" / SYNCSTATE_DB_FILENAME

    def test_xdg_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv(HSYNC_STATE_DIR_ENV, raising=False)
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
        assert default_state_dir() == tmp_path / "xdg" / "hsync"

    def test_home_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv(HSYNC_STATE_DIR_ENV, raising=False)
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        monkeypatch.setattr("hsync_common.models.folder.Path.home", lambda: tmp_path / "home")
        assert default_state_dir() == tmp_path / "home" / ".local" / "state" / "hsync"
        assert os.environ.get(HSYNC_STATE_DIR_ENV) is None
