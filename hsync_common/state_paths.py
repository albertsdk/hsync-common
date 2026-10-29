# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Installation state-directory resolution shared by every hsync process.

Kept as a leaf module (``os``/``pathlib`` + ``hsync_common.constants`` only):
the client CLI imports it at startup, where pulling the ``hsync_common.models``
package would break the lightweight-import contract
(``hsync-client/tests/test_startup_imports.py``).

Consumers: ``hsync-client`` (device identity, server/rendezvous trust stores, p2p
pins, verbose PATHS dump), ``hsync-server`` (per-bucket state), ``hsync-rendezvous``
(identity path), tests.
"""

from __future__ import annotations

import os
from pathlib import Path

from hsync_common.constants import HSYNC_STATE_DIR_ENV

__all__ = ["default_state_dir", "state_path"]


def default_state_dir() -> Path:
    """Return the installation state directory (not inside any bucket).

    Resolution order: ``HSYNC_STATE_DIR``, then ``$XDG_STATE_HOME/hsync``,
    then ``~/.local/state/hsync``. Consumers: ``hsync-client`` and
    ``hsync-server``; tests override via the env var.
    """
    override = os.environ.get(HSYNC_STATE_DIR_ENV)
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(Path.home(), ".local", "state")
    return Path(base) / "hsync"


def state_path(*parts: str, override_env: str | None = None) -> Path:
    """Return a path under the installation state dir, with a per-item override.

    ``$<override_env>`` wins when set; otherwise the path is
    ``<state dir>/<parts...>``. Keeping every state file under one root means
    ``HSYNC_STATE_DIR`` relocates the device identity, the trust stores and the
    p2p pins together instead of splitting them across two trees (the split the
    XDG-only fallback used to cause).

    Consumers: ``hsync-client`` (``identity.default_device_dir`` and the
    ``server_trust`` / ``rendezvous_trust`` / ``pinning`` default paths),
    ``hsync-rendezvous`` (``cli.default_identity_path``), tests.
    """
    if override_env:
        override = os.environ.get(override_env)
        if override:
            return Path(override)
    return default_state_dir().joinpath(*parts)
