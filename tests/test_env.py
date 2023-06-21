"""Tests for hsync_common.env (load_env_file)."""

import os

import pytest

from hsync_common.env import load_env_file


class TestLoadEnvFileMissing:
    def test_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_env_file(tmp_path / "nonexistent.env")


class TestLoadEnvFileBasic:
    def test_loads_key_value(self, tmp_path, monkeypatch):
        env_file = tmp_path / "test.env"
        env_file.write_text("TEST_VAR_UNIQUE=hello123\n")
        monkeypatch.delenv("TEST_VAR_UNIQUE", raising=False)
        load_env_file(env_file)
        assert os.environ.get("TEST_VAR_UNIQUE") == "hello123"

    def test_ignores_comments(self, tmp_path, monkeypatch):
        env_file = tmp_path / "test.env"
        env_file.write_text("# This is a comment\nVAR_NO_COMMENT=yes\n")
        monkeypatch.delenv("VAR_NO_COMMENT", raising=False)
        load_env_file(env_file)
        assert os.environ.get("VAR_NO_COMMENT") == "yes"

    def test_does_not_override_existing_env(self, tmp_path, monkeypatch):
        env_file = tmp_path / "test.env"
        env_file.write_text("EXISTING_VAR=from_file\n")
        monkeypatch.setenv("EXISTING_VAR", "from_env")
        load_env_file(env_file)
        assert os.environ.get("EXISTING_VAR") == "from_env"

    def test_accepts_path_object(self, tmp_path, monkeypatch):
        env_file = tmp_path / "test.env"
        env_file.write_text("PATH_OBJ_VAR=works\n")
        monkeypatch.delenv("PATH_OBJ_VAR", raising=False)
        load_env_file(env_file)
        assert os.environ.get("PATH_OBJ_VAR") == "works"

    def test_accepts_string_path(self, tmp_path, monkeypatch):
        env_file = tmp_path / "test.env"
        env_file.write_text("STR_PATH_VAR=ok\n")
        monkeypatch.delenv("STR_PATH_VAR", raising=False)
        load_env_file(str(env_file))
        assert os.environ.get("STR_PATH_VAR") == "ok"


class TestLoadEnvFileCallback:
    def test_on_loaded_callback_called(self, tmp_path):
        env_file = tmp_path / "test.env"
        env_file.write_text("X=1\n")
        called = []
        load_env_file(env_file, on_loaded=lambda: called.append(True))
        assert called == [True]

    def test_on_loaded_not_called_when_none(self, tmp_path):
        env_file = tmp_path / "test.env"
        env_file.write_text("Y=2\n")
        # Should not raise even when on_loaded is None
        load_env_file(env_file, on_loaded=None)

    def test_on_loaded_not_called_on_file_not_found(self, tmp_path):
        called = []
        with pytest.raises(FileNotFoundError):
            load_env_file(tmp_path / "missing.env", on_loaded=lambda: called.append(True))
        assert called == []


class TestLoadEnvFileEdgeCases:
    def test_empty_file(self, tmp_path):
        env_file = tmp_path / "empty.env"
        env_file.write_text("")
        # Should not raise
        load_env_file(env_file)

    def test_quoted_values(self, tmp_path, monkeypatch):
        env_file = tmp_path / "test.env"
        env_file.write_text('QUOTED_VAR="hello world"\n')
        monkeypatch.delenv("QUOTED_VAR", raising=False)
        load_env_file(env_file)
        assert os.environ.get("QUOTED_VAR") == "hello world"
