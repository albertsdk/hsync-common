# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for the strict LAN peer-download wire models (ADR-0028)."""

import json

import pytest

from hsync_common.constants import WS_MAX_MESSAGE_BYTES
from hsync_common.protocol.peer_download import (
    LAN_INVENTORY_MAX_ENTRIES,
    LAN_INVENTORY_MAX_FRAME_BYTES,
    LAN_SOURCES_MAX_BODY_BYTES,
    LAN_SOURCES_MAX_CANDIDATES,
    LAN_SOURCES_MAX_FILES,
    LAN_WIRE_INT_MAX,
    LanInventoryDeleteEntry,
    LanInventoryUpsertEntry,
    LanSourceCandidate,
    LanSourceFile,
    LanSourcesResponseFile,
    build_lan_inventory_ack,
    build_lan_inventory_frame,
    build_lan_sources_request,
    build_lan_sources_response,
    validate_lan_inventory_ack,
    validate_lan_inventory_frame,
    validate_lan_sources_request,
    validate_lan_sources_response,
)

_CID = "TestClientX1234567890"
_SEEDER_CID = "TestClientA1234567890"
_SHA256 = "a" * 64
_CERT_FP = "b" * 64
_URL = "https://192.0.2.10:8443/api/v1/buckets/bucket-1/files/download"


def _source(path: str = "docs/report.bin") -> dict[str, object]:
    return {"path": path, "sha256": _SHA256}


def _candidate(url: str = _URL) -> dict[str, object]:
    return {
        "cid": _SEEDER_CID,
        "download_url": url,
        "cert_fp": _CERT_FP,
        "compression": True,
    }


def _sources_response(url: str = _URL) -> dict[str, object]:
    return {
        "files": [
            {
                "path": "docs/report.bin",
                "sha256": _SHA256,
                "sources": [_candidate(url)],
            }
        ]
    }


def _inventory(
    *,
    mode: str = "snapshot",
    more: bool = False,
    entries: list[dict[str, object]] | None = None,
    gen: object = 1,
    seq: object = 0,
) -> dict[str, object]:
    return {
        "type": "inventory",
        "gen": gen,
        "seq": seq,
        "mode": mode,
        "more": more,
        "entries": entries if entries is not None else [_source() | {"size": 42}],
    }


def _max_length_path(index: int) -> str:
    """Build a unique valid 4096-byte path from bounded components."""
    first = f"{index:03d}" + "a" * 251
    return "/".join([first, *(["b" * 255] * 15), "c"])


def _compact_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class TestLimits:
    def test_contract_limits(self):
        assert LAN_SOURCES_MAX_FILES == 500
        assert LAN_SOURCES_MAX_CANDIDATES == 8
        assert LAN_INVENTORY_MAX_ENTRIES == 500
        assert LAN_WIRE_INT_MAX == (1 << 63) - 1
        assert LAN_SOURCES_MAX_BODY_BYTES == WS_MAX_MESSAGE_BYTES
        assert LAN_INVENTORY_MAX_FRAME_BYTES == WS_MAX_MESSAGE_BYTES


class TestSourcesRequest:
    def test_builder_emits_canonical_request(self):
        request = build_lan_sources_request(
            cid=_CID,
            files=[LanSourceFile(path="cafe\u0301/report.bin", sha256=_SHA256)],
        )
        assert request == {
            "cid": _CID,
            "files": [{"path": "caf\u00e9/report.bin", "sha256": _SHA256}],
        }

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"cid": _CID, "files": [_source()], "extra": True},
            {"cid": "bad", "files": [_source()]},
            {"cid": _CID, "files": []},
            {"cid": _CID, "files": (_source(),)},
            {"cid": _CID, "files": [{"path": "a.bin", "sha256": _SHA256, "extra": 1}]},
            {"cid": _CID, "files": [{"path": "../escape", "sha256": _SHA256}]},
            {"cid": _CID, "files": [{"path": "\ud800", "sha256": _SHA256}]},
            {"cid": _CID, "files": [{"path": "a.bin", "sha256": _SHA256.upper()}]},
            {"cid": _CID, "files": [_source("a.bin"), _source("/a.bin")]},
        ],
    )
    def test_rejects_invalid_request(self, payload):
        assert validate_lan_sources_request(payload) is None

    def test_rejects_duplicate_normalized_paths(self):
        request = {
            "cid": _CID,
            "files": [_source("caf\u00e9.bin"), _source("cafe\u0301.bin")],
        }
        assert validate_lan_sources_request(request) is None

    def test_rejects_more_than_500_files(self):
        request = {
            "cid": _CID,
            "files": [_source(f"files/{index}.bin") for index in range(LAN_SOURCES_MAX_FILES + 1)],
        }
        assert validate_lan_sources_request(request) is None

    def test_accepts_500_files(self):
        request = {
            "cid": _CID,
            "files": [_source(f"files/{index}.bin") for index in range(LAN_SOURCES_MAX_FILES)],
        }
        assert validate_lan_sources_request(request) is not None

    def test_accepts_maximum_path_length(self):
        request = {"cid": _CID, "files": [_source(_max_length_path(0))]}
        assert validate_lan_sources_request(request) is not None

    def test_builder_raises_for_invalid_request(self):
        with pytest.raises(ValueError, match="LAN sources request"):
            build_lan_sources_request(cid="bad", files=[LanSourceFile(path="a", sha256=_SHA256)])


class TestSourcesResponse:
    def test_builder_accepts_ipv6_endpoint(self):
        url = "https://[2001:db8::1]:8443/api/v1/buckets/bucket-1/files/download"
        response = build_lan_sources_response(
            files=[
                LanSourcesResponseFile(
                    path="docs/report.bin",
                    sha256=_SHA256,
                    sources=[
                        LanSourceCandidate(
                            cid=_SEEDER_CID,
                            download_url=url,
                            cert_fp=_CERT_FP,
                            compression=False,
                        )
                    ],
                )
            ]
        )
        assert response["files"][0]["sources"][0]["download_url"] == url

    @pytest.mark.parametrize("port", [1, 65535])
    def test_accepts_port_boundaries(self, port):
        url = f"https://192.0.2.10:{port}/api/v1/buckets/bucket-1/files/download"
        assert validate_lan_sources_response(_sources_response(url)) is not None

    def test_empty_candidate_list_is_valid(self):
        response = _sources_response()
        response["files"][0]["sources"] = []  # type: ignore[index]
        assert validate_lan_sources_response(response) is not None

    @pytest.mark.parametrize(
        "url",
        [
            "http://192.0.2.10:8443/api/v1/buckets/bucket-1/files/download",
            "https://192.0.2.10/api/v1/buckets/bucket-1/files/download",
            "https://peer.local:8443/api/v1/buckets/bucket-1/files/download",
            "https://[fe80::1%25eth0]:8443/api/v1/buckets/bucket-1/files/download",
            "https://192.0.2.10:0/api/v1/buckets/bucket-1/files/download",
            "https://192.0.2.10:65536/api/v1/buckets/bucket-1/files/download",
            "https://[2001:db8::1]:8443/api/v1/buckets/bucket-1/files/download?x=1",
            "https://192.0.2.10:8443/api/v1/buckets/bucket-1/files/download?",
            "https://192.0.2.10:8443/api/v1/buckets/bucket-1/files/download#",
            "https://192.0.2.10:8443/api/v1/buckets/bucket-1/files/\ndownload",
            "https://192.0.2.10:8443/api/v1/buckets/bucket-1/files",
        ],
    )
    def test_rejects_invalid_candidate_url(self, url):
        assert validate_lan_sources_response(_sources_response(url)) is None

    def test_rejects_more_than_eight_candidates(self):
        response = _sources_response()
        response["files"][0]["sources"] = [  # type: ignore[index]
            _candidate().copy() | {"cid": f"SeederClient{index:09d}"}
            for index in range(LAN_SOURCES_MAX_CANDIDATES + 1)
        ]
        assert validate_lan_sources_response(response) is None

    def test_accepts_eight_unique_candidates(self):
        response = _sources_response()
        response["files"][0]["sources"] = [  # type: ignore[index]
            _candidate().copy() | {"cid": f"SeederClient{index:09d}"}
            for index in range(LAN_SOURCES_MAX_CANDIDATES)
        ]
        assert validate_lan_sources_response(response) is not None

    def test_rejects_duplicate_candidate_cid(self):
        response = _sources_response()
        response["files"][0]["sources"] = [_candidate(), _candidate()]  # type: ignore[index]
        assert validate_lan_sources_response(response) is None

    def test_rejects_duplicate_normalized_response_paths(self):
        response = _sources_response()
        response["files"].append(  # type: ignore[union-attr]
            {
                "path": "cafe\u0301.bin",
                "sha256": _SHA256,
                "sources": [],
            }
        )
        response["files"][0]["path"] = "caf\u00e9.bin"  # type: ignore[index]
        assert validate_lan_sources_response(response) is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"files": []},
            {"files": [], "extra": True},
            {
                "files": [
                    {
                        "path": "a.bin",
                        "sha256": _SHA256,
                        "sources": [],
                        "extra": True,
                    }
                ]
            },
            {"files": [{"path": "\ud800", "sha256": _SHA256, "sources": []}]},
        ],
    )
    def test_rejects_invalid_response_shape(self, payload):
        assert validate_lan_sources_response(payload) is None

    def test_rejects_response_over_body_limit(self):
        response = {
            "files": [
                {
                    "path": _max_length_path(index),
                    "sha256": _SHA256,
                    "sources": [_candidate()],
                }
                for index in range(LAN_SOURCES_MAX_FILES)
            ]
        }
        assert _compact_size(response) > LAN_SOURCES_MAX_BODY_BYTES
        assert validate_lan_sources_response(response) is None

    @pytest.mark.parametrize(
        "field,value",
        [
            ("cid", "bad"),
            ("cert_fp", _CERT_FP.upper()),
            ("compression", 1),
        ],
    )
    def test_rejects_invalid_candidate_metadata(self, field, value):
        response = _sources_response()
        response["files"][0]["sources"][0][field] = value  # type: ignore[index]
        assert validate_lan_sources_response(response) is None


class TestInventoryFrame:
    def test_snapshot_builder(self):
        entry = LanInventoryUpsertEntry(path="a.bin", sha256=_SHA256, size=0)
        assert build_lan_inventory_frame(
            gen=1, seq=0, mode="snapshot", more=False, entries=[entry]
        ) == {
            "type": "inventory",
            "gen": 1,
            "seq": 0,
            "mode": "snapshot",
            "more": False,
            "entries": [{"path": "a.bin", "sha256": _SHA256, "size": 0}],
        }

    def test_empty_terminal_snapshot_is_valid(self):
        assert validate_lan_inventory_frame(_inventory(entries=[])) is not None

    @pytest.mark.parametrize(
        "frame",
        [
            _inventory(entries=[], more=True),
            _inventory(entries=[], seq=1),
        ],
    )
    def test_empty_snapshot_must_be_terminal_sequence_zero(self, frame):
        assert validate_lan_inventory_frame(frame) is None

    def test_delta_upsert_and_delete_are_valid(self):
        upsert = _source("new.bin") | {"size": 7}
        deleted = {"path": "old.bin", "deleted": True}
        frame = _inventory(mode="delta", entries=[upsert, deleted], seq=1)
        assert validate_lan_inventory_frame(frame) is not None

    def test_accepts_wire_integer_maximum(self):
        entry = _source() | {"size": LAN_WIRE_INT_MAX}
        frame = _inventory(gen=LAN_WIRE_INT_MAX, seq=LAN_WIRE_INT_MAX, entries=[entry])
        assert validate_lan_inventory_frame(frame) is not None

    @pytest.mark.parametrize(
        "field,value", [("gen", True), ("seq", -1), ("gen", LAN_WIRE_INT_MAX + 1)]
    )
    def test_rejects_invalid_wire_integer(self, field, value):
        frame = _inventory()
        frame[field] = value
        assert validate_lan_inventory_frame(frame) is None

    def test_rejects_snapshot_delete(self):
        frame = _inventory(entries=[{"path": "old.bin", "deleted": True}])
        assert validate_lan_inventory_frame(frame) is None

    def test_rejects_empty_or_chunked_delta(self):
        assert validate_lan_inventory_frame(_inventory(mode="delta", entries=[])) is None
        assert validate_lan_inventory_frame(_inventory(mode="delta", more=True)) is None

    def test_rejects_duplicate_path_in_one_frame(self):
        frame = _inventory(
            mode="delta",
            entries=[_source("a.bin") | {"size": 1}, {"path": "a.bin", "deleted": True}],
        )
        assert validate_lan_inventory_frame(frame) is None

    def test_rejects_too_many_entries(self):
        entries = [
            _source(f"files/{index}.bin") | {"size": index}
            for index in range(LAN_INVENTORY_MAX_ENTRIES + 1)
        ]
        assert validate_lan_inventory_frame(_inventory(entries=entries)) is None

    def test_accepts_500_entries(self):
        entries = [
            _source(f"files/{index}.bin") | {"size": index}
            for index in range(LAN_INVENTORY_MAX_ENTRIES)
        ]
        assert validate_lan_inventory_frame(_inventory(entries=entries)) is not None

    @pytest.mark.parametrize(
        "entry",
        [
            {"path": "../escape", "sha256": _SHA256, "size": 1},
            {"path": "\ud800", "sha256": _SHA256, "size": 1},
            {"path": "a", "sha256": _SHA256.upper(), "size": 1},
            {"path": "a", "sha256": _SHA256, "size": True},
            {"path": "a", "sha256": _SHA256, "size": -1},
            {"path": "a", "deleted": False},
            {"path": "a", "deleted": True, "sha256": _SHA256},
        ],
    )
    def test_rejects_invalid_entry(self, entry):
        mode = "delta" if "deleted" in entry else "snapshot"
        assert validate_lan_inventory_frame(_inventory(mode=mode, entries=[entry])) is None

    def test_builder_raises_for_invalid_delta(self):
        with pytest.raises(ValueError, match="LAN inventory frame"):
            build_lan_inventory_frame(gen=1, seq=1, mode="delta", more=True, entries=[])

    def test_rejects_frame_over_message_limit(self):
        frame = _inventory(
            entries=[
                {"path": _max_length_path(index), "sha256": _SHA256, "size": index}
                for index in range(LAN_INVENTORY_MAX_ENTRIES)
            ]
        )
        assert _compact_size(frame) > LAN_INVENTORY_MAX_FRAME_BYTES
        assert validate_lan_inventory_frame(frame) is None

    def test_rejects_unknown_frame_property(self):
        frame = _inventory()
        frame["extra"] = True
        assert validate_lan_inventory_frame(frame) is None


class TestInventoryAck:
    @pytest.mark.parametrize("status", ["ok", "resync"])
    def test_non_rejected_ack_has_no_reason(self, status):
        frame = build_lan_inventory_ack(gen=1, seq=7, status=status)
        assert frame == {"type": "inventory_ack", "gen": 1, "seq": 7, "status": status}

    def test_rejected_ack_requires_machine_reason(self):
        frame = build_lan_inventory_ack(gen=1, seq=7, status="rejected", reason="quota")
        assert frame["reason"] == "quota"  # type: ignore[reportTypedDictNotRequiredAccess]

    def test_rejected_ack_accepts_maximum_reason_length(self):
        reason = "a" + "0" * 63
        assert (
            build_lan_inventory_ack(gen=1, seq=7, status="rejected", reason=reason)["reason"]
            == reason
        )

    @pytest.mark.parametrize(
        "frame",
        [
            {"type": "inventory_ack", "gen": 1, "seq": 0, "status": "unknown"},
            {"type": "inventory_ack", "gen": True, "seq": 0, "status": "ok"},
            {"type": "inventory_ack", "gen": 1, "seq": -1, "status": "resync"},
            {"type": "inventory_ack", "gen": 1, "seq": 0, "status": "ok", "reason": "x"},
            {"type": "inventory_ack", "gen": 1, "seq": 0, "status": "rejected"},
            {
                "type": "inventory_ack",
                "gen": 1,
                "seq": 0,
                "status": "rejected",
                "reason": "not valid",
            },
            {
                "type": "inventory_ack",
                "gen": 1,
                "seq": 0,
                "status": "rejected",
                "reason": "a" * 65,
            },
            {
                "type": "inventory_ack",
                "gen": 1,
                "seq": 0,
                "status": "rejected",
                "reason": "invalid\n",
            },
        ],
    )
    def test_rejects_invalid_ack(self, frame):
        assert validate_lan_inventory_ack(frame) is None

    def test_builder_rejects_reason_on_ok(self):
        with pytest.raises(ValueError, match="LAN inventory acknowledgement"):
            build_lan_inventory_ack(gen=1, seq=0, status="ok", reason="invalid")

    def test_typed_delete_entry_builds_delta(self):
        entry = LanInventoryDeleteEntry(path="old.bin", deleted=True)
        frame = build_lan_inventory_frame(gen=1, seq=1, mode="delta", more=False, entries=[entry])
        assert frame["entries"] == [{"path": "old.bin", "deleted": True}]
