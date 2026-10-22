# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""State-directory resolution: one root for every persistent hsync artifact.

``HSYNC_STATE_DIR`` must move the device identity, the trust stores and the p2p
pins together; each item keeps its own override. The module is also a leaf
import (no ``hsync_common.models``), which the client CLI relies on.
"""

from __future__ import annotations

from hsync_common.constants import HSYNC_STATE_DIR_ENV
from hsync_common.models import folder
from hsync_common.state_paths import default_state_dir, state_path


class TestStatePath:
    def test_joins_under_the_state_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv(HSYNC_STATE_DIR_ENV, str(tmp_path / "state"))
        assert state_path("device") == tmp_path / "state" / "device"
        assert state_path("bootnode", "identity.pem") == (
            tmp_path / "state" / "bootnode" / "identity.pem"
        )

    def test_per_item_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv(HSYNC_STATE_DIR_ENV, str(tmp_path / "state"))
        monkeypatch.setenv("HSYNC_TEST_OVERRIDE", str(tmp_path / "custom.pem"))
        assert state_path("device", override_env="HSYNC_TEST_OVERRIDE") == tmp_path / "custom.pem"

    def test_without_override_env_uses_the_state_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv(HSYNC_STATE_DIR_ENV, str(tmp_path / "state"))
        assert state_path("pins.json") == tmp_path / "state" / "pins.json"

    def test_falls_back_to_xdg(self, tmp_path, monkeypatch):
        monkeypatch.delenv(HSYNC_STATE_DIR_ENV, raising=False)
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
        assert state_path("pins.json") == tmp_path / "xdg" / "hsync" / "pins.json"

    def test_state_dir_override_is_honoured(self, tmp_path, monkeypatch):
        monkeypatch.setenv(HSYNC_STATE_DIR_ENV, str(tmp_path / "state"))
        assert default_state_dir() == tmp_path / "state"


class TestReExports:
    def test_folder_module_reexports_the_same_objects(self):
        """Existing ``hsync_common.models.folder`` imports must not fork."""
        assert folder.state_path is state_path
        assert folder.default_state_dir is default_state_dir
