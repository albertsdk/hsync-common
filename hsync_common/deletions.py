# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""In-flight recursive-deletion registry.

A recursive delete (a ``DELETE … is_dir=true`` on a P2P master, a recursive
``deleted`` event on the server) removes a whole subtree. Until that removal
completes the subtree must be closed to any concurrent materialisation: a
create, an upload, a rename destination or an applied event landing inside it
recreates content the caller asked to remove, the ``rmtree`` then fails with
``ENOTEMPTY`` and the delete is abandoned with the tree half present — a
deletion that never converges, which the peer then recreates on the next
reconcile.

The window is the delete itself (``begin``…``end``); the TTL only bounds a
window a crashed or aborted request failed to close, and the entry count is
capped so a hostile peer cannot grow it without limit. The registry is
per-process state, exactly like the per-path locks each consumer already keeps
(``hsync_client`` p2p master, ``hsync_server`` ``file_lock_manager``): a
deployment that runs several server workers has one window per worker, no
tighter than the rest of its in-process concurrency control.

Consumers:
- ``hsync_client``: ``p2p_server.P2PEndpointMixin._handle_delete`` owns the
  window; the write endpoints and ``event_dispatch`` refuse paths inside it.
- ``hsync_server``: ``api/events_handlers/handlers.handle_deleted_event`` owns
  it; the REST write endpoints and the WS event handlers refuse paths inside it.
"""

from __future__ import annotations

import threading
from time import monotonic

# Long enough for an rmtree of a large tree, short enough that an aborted
# request cannot close a path for the rest of the process lifetime.
_TTL_S = 60.0
_MAX_ENTRIES = 256

_lock = threading.Lock()
_active: dict[str, float] = {}


def _prune(now: float) -> None:
    for path, expires in list(_active.items()):
        if expires <= now:
            del _active[path]


def begin_tree_delete(abs_path: str) -> None:
    """Close *abs_path* and its subtree against materialisation.

    Consumers: the P2P master's ``_handle_delete`` and the server's
    ``handle_deleted_event`` (each opens the window for the removal it owns).
    """
    now = monotonic()
    with _lock:
        _prune(now)
        if len(_active) >= _MAX_ENTRIES:
            del _active[min(_active, key=lambda key: _active[key])]
        _active[abs_path.rstrip("/")] = now + _TTL_S


def end_tree_delete(abs_path: str) -> None:
    """Reopen *abs_path* once its removal finished (or failed)."""
    with _lock:
        _active.pop(abs_path.rstrip("/"), None)


def covered_by_tree_delete(path: str) -> bool:
    """Return True when *path* equals or descends from an in-flight delete.

    Ancestor walk (O(depth)) instead of a scan of the registered roots: the
    check runs on every inbound event and every write request.
    """
    now = monotonic()
    with _lock:
        _prune(now)
        probe = path.rstrip("/")
        while True:
            if probe in _active:
                return True
            idx = probe.rfind("/")
            if idx <= 0:
                return False
            probe = probe[:idx]


def reset_tree_deletes() -> None:
    """Drop every window (tests start and end with an empty registry)."""
    with _lock:
        _active.clear()
