# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Bucket listing primitives shared by every HSYNC serving surface.

The central server (FastAPI, ``api/files/list.py``) and the LAN master
(``hsync_client/p2p_server.py``) publish the *same* bucket listing to their
peers: hidden/ignored entries filtered out, symlinks emitted structurally and
never dereferenced, paths bucket-relative, entries in deterministic path order
and the body streamed as an incrementally framed JSON array.

Each of those rules used to be implemented twice. They live here so the two
surfaces cannot drift (a filter fixed on one side silently leaked on the other).

Consumers: ``hsync-server`` (``api/files/list.py``), ``hsync-client``
(``sync.iter_bucket_entries`` wrapper, ``p2p_server.py`` listing and dir
permission endpoints), shared tests/fixtures.
"""

from __future__ import annotations

import os
from collections.abc import Collection, Iterable, Iterator
from os import walk
from pathlib import Path

from loguru import logger as log

from hsync_common.labels import ActionLabel
from hsync_common.models.dir import Dir, is_hidden_dir
from hsync_common.models.file import File, is_hidden_file
from hsync_common.models.symlink import Symlink
from hsync_common.models.version import relpath_in_bucket
from hsync_common.path_validation import is_safe_symlink_target
from hsync_common.text import compact_json_bytes

__all__ = [
    "file_entry",
    "iter_bucket_entries",
    "iter_dir_entries",
    "iter_json_array",
    "symlink_entry",
]


def iter_json_array(items: Iterable[dict]) -> Iterator[bytes]:
    """Yield a JSON array body incrementally: ``[``, item, ``,``, item, ``]``.

    The listing endpoints do not know their body size without materialising the
    whole array, so they stream it: peak memory is O(one entry) instead of one
    dict per file, and the first entry reaches the peer without waiting for the
    walk to finish. A producer failure truncates the array — invalid JSON — so a
    consumer fails loudly instead of acting on a silently partial listing.

    Consumers: ``hsync-server`` ``get_files``/``get_dirs`` (``StreamingResponse``
    iterates the generator on a worker thread).
    """
    yield b"["
    first = True
    for item in items:
        if first:
            first = False
        else:
            yield b","
        yield compact_json_bytes(item)
    yield b"]"


def iter_dir_entries(bucket_root: str) -> Iterator[dict]:
    """Yield one ``{path, permissions}`` entry per directory, in walk order.

    Directories carry no content hash and never appear in the file listing, so
    this is the only surface that publishes their permissions (the "remote
    wins" download-only permission converge). Dir-symlinks are structural
    entries and are never listed as directories.

    The order is the deterministic per-directory walk order (siblings sorted,
    the tree not globally sorted) — the same contract as the file listing, so a
    nested tree can be streamed without materialising it.

    Consumers: ``hsync-server`` (``GET …/dirs``), ``hsync-client``
    (``p2p_server._handle_list_dirs``).
    """
    for root, dirs, _files in walk(bucket_root):
        # Sorted so the stream order is deterministic (filesystem order is not)
        # without buffering the tree. ``walk`` uses followlinks=False, so a
        # symlinked directory is listed here but never descended into.
        dirs[:] = sorted(d for d in dirs if not is_hidden_dir(f"{root}/{d}"))
        for name in dirs:
            full = f"{root}/{name}"
            if os.path.islink(full):
                continue
            dir_obj = Dir.get(full)
            if dir_obj is None or dir_obj.permissions is None:
                continue
            rel = os.path.relpath(full, bucket_root)
            if rel == ".":
                continue
            yield {"path": rel, "permissions": dir_obj.permissions}


def _resolve_entry_symlink(entry_path: str, bucket_root: str) -> tuple[bool, Symlink | None]:
    """Classify one directory entry: return ``(emit, symlink_or_none)``.

    ``emit`` is ``False`` for a symlink whose target escapes the bucket: such a
    link must never be dereferenced (``File.get`` would stat/hash the target and
    exfiltrate e.g. ``/etc/passwd`` to every peer), so it is skipped with a
    security log line.
    """
    if not Path(entry_path).is_symlink():
        return True, None
    try:
        link = Symlink.get(entry_path)
    except OSError:
        # A directory entry that vanished (or is not readable as a link) between
        # the walk and this call: skip it rather than abort the whole listing.
        return False, None
    if link is not None and not is_safe_symlink_target(entry_path, link.target, bucket_root):
        log.warning(
            f"{ActionLabel.SECURITY} Symlink target escapes bucket, "
            f'skipping: "{entry_path}" -> "{link.target}"'
        )
        return False, None
    return True, link


def iter_bucket_entries(
    bucket_root: str,
    *,
    start_dir: str | None = None,
    skip_suffixes: Collection[str] = (),
    include_dir_symlinks: bool = False,
) -> Iterator[tuple[str, Symlink | None]]:
    """Yield ``(abs_path, symlink_or_none)`` for every syncable bucket entry.

    Walks with ``followlinks=False`` (the default), skipping hidden/ignored
    directories and files; safe symlinks yield their :class:`Symlink` (never
    dereferenced), regular files and unreadable symlinks yield ``None``. Path
    order is deterministic (sorted), because a served listing must be stable.

    Args:
        bucket_root: Bucket root — the reference for symlink confinement and for
            the relative paths computed by the callers.
        start_dir: Subdirectory to scan (defaults to *bucket_root*). Symlink
            confinement still uses *bucket_root*.
        skip_suffixes: Filenames ending with one of these are not emitted (the
            server skips its upload-backup files).
        include_dir_symlinks: Also emit directory symlinks as entries. The
            server lists them (a peer recreates the link structurally); the
            client's sync scan does not.

    Consumers: ``hsync-client`` (``sync.iter_bucket_entries`` wrapper,
    ``p2p_server`` file listing), ``hsync-server``
    (``api/files/list.py._iter_file_entries``).
    """
    suffixes = tuple(skip_suffixes)
    for root, dirs, files in walk(start_dir or bucket_root):
        # Filtered by name, not by path: this is the form the client's ignore
        # matcher has always seen, so the set of files a running sync engine
        # picks up does not change.
        dirs[:] = sorted(d for d in dirs if not is_hidden_dir(d))

        for name in sorted(files):
            if is_hidden_file(name):
                continue
            if suffixes and name.endswith(suffixes):
                continue
            file_path = os.path.join(root, name)
            emit, link = _resolve_entry_symlink(file_path, bucket_root)
            if emit:
                yield file_path, link

        if include_dir_symlinks:
            for name in dirs:
                dir_path = os.path.join(root, name)
                emit, link = _resolve_entry_symlink(dir_path, bucket_root)
                if emit and link is not None:
                    yield dir_path, link


def file_entry(file_obj: File, bucket_root: str) -> dict:
    """Return the wire dict for one file, with a bucket-relative ``filepath``.

    A path outside *bucket_root* is kept verbatim (it is never advertised as a
    relative path); this mirrors what both listing surfaces did before the
    extraction, so the JSON shape is unchanged.

    Consumers: ``hsync-server`` (``api/files/list.py``), ``hsync-client``
    (``p2p_server._handle_list_files``).
    """
    entry = file_obj.to_dict()
    rel = relpath_in_bucket(file_obj.filepath or "", bucket_root)
    entry["filepath"] = (file_obj.filepath or "") if rel is None else rel
    return entry


def symlink_entry(link: Symlink, path: str, bucket_root: str) -> dict | None:
    """Return the wire dict for a symlink entry, or ``None`` when it escapes.

    Consumers: ``hsync-server`` (``api/files/list.py``), ``hsync-client``
    (``p2p_server._handle_list_files``).
    """
    if link.target is None or not is_safe_symlink_target(path, link.target, bucket_root):
        log.warning(
            f"{ActionLabel.SECURITY} Symlink target escapes bucket, "
            f'skipping: "{path}" -> "{link.target}"'
        )
        return None
    entry = link.to_dict()
    rel = relpath_in_bucket(path, bucket_root)
    entry["filepath"] = path if rel is None else rel
    return entry
