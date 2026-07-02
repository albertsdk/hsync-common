# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""L1 — shared-model serialization micro-benchmark (pure, no I/O).

``File``/``Dir``/``Symlink``/``Event`` round-trips sit on the hottest path of a
sync cycle: every scanned entry is serialized for listings, events and the wire,
and every remote entry is decoded back into a model. This benchmark measures
those conversions plus the two per-entry wire validators
(``is_valid_cid`` on events, ``is_partial_file`` on scanned names).

Methodology specifics:

* Both decode directions are measured, because they are different branches of
  the shared prefix contract: ``strip`` (absolute wire path → bucket-relative)
  and ``prepend`` (bucket-relative → absolute local path).
* Measured ops assert a field of the decoded/encoded object, so a conversion
  that silently drops data cannot be reported as fast.
* The path prefix is a realistic bucket directory, so the
  ``Path.relative_to`` / ``Path.__truediv__`` work is included.
* No filesystem access and no temp files: the benchmark is a pure CPU measure.

Usage:
    cd hsync-common && .venv/bin/python bench/bench_models.py [--count N] [--json-out FILE]
"""

from __future__ import annotations

import argparse

from common import (
    BenchResult,
    add_json_out,
    maybe_write_json,
    measure,
    print_table,
)

from hsync_common.models.dir import Dir
from hsync_common.models.event import Event, EventName, is_valid_cid
from hsync_common.models.file import File, is_partial_file
from hsync_common.models.symlink import Symlink
from hsync_common.models.tombstone import relpath_in_bucket

_BUCKET_ROOT = "/srv/hsync/buckets/media"
_CID = "A1b2C3d4E5f6G7h8I9j0K"
_SHA256 = "a" * 64
_MTIME = 1_700_000_500

# Absolute wire-shaped File dict (as a producer emits it) and its
# bucket-relative counterpart (as a consumer decodes it with prepend).
_FILE_DICT_ABS = {
    "filepath": f"{_BUCKET_ROOT}/photos/2024/album/photo-001.jpg",
    "name": "photo-001.jpg",
    "ctime": 1_700_000_000,
    "mtime": _MTIME,
    "size": 4 * 1024 * 1024,
    "sha256sum": _SHA256,
    "permissions": "644",
    "version": {
        "vclock": {_CID: 7},
        "version_id": "3f2a1b0c9d8e7f6051423321110fedcb",
        "origin_cid": _CID,
        "ts": _MTIME,
        "corrected_mtime": _MTIME,
    },
}
_FILE_DICT_REL = dict(_FILE_DICT_ABS, filepath="photos/2024/album/photo-001.jpg")


def _bench_file(count: int) -> list[BenchResult]:
    """Encode/decode round-trips of the per-file wire model."""
    info = File.from_dict(_FILE_DICT_ABS, _BUCKET_ROOT, strip_dir_prefix=True)
    assert info.name == "photo-001.jpg"
    # Decoding with strip must yield a bucket-relative path.
    assert not str(info.filepath).startswith(_BUCKET_ROOT), info.filepath

    def op_to_dict() -> None:
        assert info.to_dict()["size"] == _FILE_DICT_ABS["size"]

    def op_from_dict_strip() -> None:
        assert File.from_dict(_FILE_DICT_ABS, _BUCKET_ROOT, True).name == "photo-001.jpg"

    def op_from_dict_prepend() -> None:
        assert File.from_dict(_FILE_DICT_REL, _BUCKET_ROOT, False).size > 0

    def op_from_dict_rel_strip() -> None:
        # The production decode shape: the listing path is already
        # bucket-relative, so strip is a verbatim no-op (fast path).
        decoded = File.from_dict(_FILE_DICT_REL, _BUCKET_ROOT, True)
        assert decoded.filepath == "photos/2024/album/photo-001.jpg"

    def op_round_trip() -> None:
        assert File.from_dict(info.to_dict(), _BUCKET_ROOT, True).sha256sum == _SHA256

    return [
        measure("file_to_dict", op_to_dict, count=count),
        measure("file_from_dict(strip)", op_from_dict_strip, count=count),
        measure("file_from_dict(prepend)", op_from_dict_prepend, count=count),
        measure("file_from_dict(rel_strip)", op_from_dict_rel_strip, count=count),
        measure("file_round_trip", op_round_trip, count=count),
    ]


def _bench_dir(count: int) -> list[BenchResult]:
    """Encode/decode of the directory event model (incl. recursive flag)."""
    directory = Dir(path=f"{_BUCKET_ROOT}/photos", permissions="755", recursive=True)
    data = directory.to_dict()
    assert data["recursive"] is True

    def op_to_dict() -> None:
        assert Dir(path=directory.path, permissions=directory.permissions).to_dict()["path"]

    def op_from_dict() -> None:
        decoded = Dir.from_dict(dict(data, path="photos"), _BUCKET_ROOT, False)
        assert decoded.recursive is True

    return [
        measure("dir_to_dict", op_to_dict, count=count),
        measure("dir_from_dict(prepend)", op_from_dict, count=count),
    ]


def _bench_symlink(count: int) -> list[BenchResult]:
    """Encode/decode of the symlink event model."""
    link = Symlink(
        filepath=f"{_BUCKET_ROOT}/latest",
        target="releases/v42",
        ctime=1_700_000_000,
        mtime=_MTIME,
    )
    data = link.to_dict()
    assert data["type"] == "symlink"

    def op_to_dict() -> None:
        assert link.to_dict()["target"] == "releases/v42"

    def op_from_dict() -> None:
        decoded = Symlink.from_dict(dict(data, filepath="latest"), _BUCKET_ROOT, False)
        assert decoded.name == "latest"

    return [
        measure("symlink_to_dict", op_to_dict, count=count),
        measure("symlink_from_dict(prepend)", op_from_dict, count=count),
    ]


def _bench_event(count: int) -> list[BenchResult]:
    """Per-change event construction and serialization (rename carrying a dst)."""
    src = File(
        filepath=f"{_BUCKET_ROOT}/docs/report.pdf",
        mtime=_MTIME,
        size=1024,
        sha256sum=_SHA256,
        permissions="644",
    )
    dst = File(
        filepath=f"{_BUCKET_ROOT}/docs/report-final.pdf",
        mtime=_MTIME,
        size=1024,
        sha256sum=_SHA256,
        permissions="644",
    )
    event = Event(
        cid=_CID,
        localpath=_BUCKET_ROOT,
        bucket="media",
        name=EventName.renamed,
        src=src,
        dst=dst,
    )
    assert event.to_dict()["dst"]["name"] == "report-final.pdf"

    def op_ctor() -> None:
        # ``src``/``dst`` are already bucket-relative after the first Event
        # (paths are rewritten in place), so repeated construction is stable.
        built = Event(
            cid=_CID,
            localpath=_BUCKET_ROOT,
            bucket="media",
            name=EventName.renamed,
            src=src,
            dst=dst,
        )
        assert built.name == "renamed"

    def op_to_dict() -> None:
        assert event.to_dict()["src"]["size"] == 1024

    return [
        measure("event_ctor(rename)", op_ctor, count=count),
        measure("event_to_dict", op_to_dict, count=count),
    ]


def _bench_path_helpers(count: int) -> list[BenchResult]:
    """Bucket-relative resolution: the per-path call of every scan.

    ``relpath_in_bucket`` is invoked once per scanned (and per event-handled)
    path by ``hsync-client`` (``sync_state``, ``tombstones``, ``arbitration``,
    ``transfer``), so its per-call cost multiplies by the bucket size — it is
    the direct signal for the path-normalisation work measured indirectly by
    ``file_from_dict(strip)`` and ``event_ctor``.
    """
    inside = f"{_BUCKET_ROOT}/photos/2024/album/photo-001.jpg"
    outside = "/srv/hsync/other/photos/2024/album/photo-001.jpg"
    assert relpath_in_bucket(inside, _BUCKET_ROOT) == "photos/2024/album/photo-001.jpg"
    assert relpath_in_bucket(outside, _BUCKET_ROOT) is None
    assert relpath_in_bucket(_BUCKET_ROOT, _BUCKET_ROOT) == ""

    def op_inside() -> None:
        assert relpath_in_bucket(inside, _BUCKET_ROOT)

    def op_outside() -> None:
        assert relpath_in_bucket(outside, _BUCKET_ROOT) is None

    return [
        measure("relpath_in_bucket(in)", op_inside, count=count),
        measure("relpath_in_bucket(out)", op_outside, count=count),
    ]


def _bench_micro(count: int) -> list[BenchResult]:
    """Per-entry wire/scan validators plus model construction."""
    cids = [_CID, _CID.lower(), "too-short", "has-hyphen-in-it-123", "z" * 21]
    cid_expected = [is_valid_cid(value) for value in cids]
    assert cid_expected == [True, True, False, False, True], cid_expected
    names = ["photo.jpg", "archive.zip.part", "movie.mkv.delta.part.lit", "notes.txt", "x.part"]
    partial_expected = [is_partial_file(name) for name in names]
    assert partial_expected == [False, True, True, False, True], partial_expected
    cid_state = {"i": 0}
    name_state = {"i": 0}

    def op_is_valid_cid() -> None:
        index = cid_state["i"] % len(cids)
        cid_state["i"] += 1
        assert is_valid_cid(cids[index]) is cid_expected[index]

    def op_is_partial_file() -> None:
        index = name_state["i"] % len(names)
        name_state["i"] += 1
        assert is_partial_file(names[index]) is partial_expected[index]

    def op_file_ctor() -> None:
        file = File(
            filepath=f"{_BUCKET_ROOT}/a/b/c.txt",
            mtime=_MTIME,
            size=1,
            sha256sum=_SHA256,
            permissions="644",
        )
        assert file.name == "c.txt"

    return [
        measure("is_valid_cid(mixed)", op_is_valid_cid, count=count),
        measure("is_partial_file(mixed)", op_is_partial_file, count=count),
        measure("file_ctor", op_file_ctor, count=count),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=2000)
    add_json_out(parser)
    args = parser.parse_args()

    count = args.count
    results: list[BenchResult] = []
    results.extend(_bench_file(count))
    results.extend(_bench_dir(count))
    results.extend(_bench_symlink(count))
    results.extend(_bench_event(count))
    results.extend(_bench_path_helpers(count))
    results.extend(_bench_micro(count))

    print(f"models micro-benchmark (ops={count}, pure CPU, no filesystem)")
    print_table(results)
    maybe_write_json(args.json_out, results)


if __name__ == "__main__":
    main()
