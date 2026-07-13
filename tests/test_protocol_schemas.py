# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for the WS + LAN/TXT JSON Schemas.

These guard the committed snapshots against silent drift from the Python source
of truth and assert that the handshake builders and shared models actually
conform to the published contract.
"""

import pytest

from hsync_common.models.event import CID_PATTERN, Event, EventName
from hsync_common.models.file import File, FileDict
from hsync_common.protocol import (
    LAN_SOURCES_SCHEMA_PATH,
    LAN_TXT_SCHEMA_PATH,
    LAN_WSS_SCHEMA_PATH,
    WS_SCHEMA_PATH,
    dump_contract,
)
from hsync_common.protocol.handshake import (
    PROTOCOL_VERSION_LAN,
    PROTOCOL_VERSION_WS,
    Capability,
    build_lan_auth,
    build_lan_auth_failed,
    build_lan_auth_ok,
    build_lan_auth_required,
    build_lan_hello,
    build_ws_auth_error,
    build_ws_auth_ok,
    build_ws_auth_request,
    encode_capabilities,
)
from hsync_common.protocol.peer_download import LAN_SERVE_SLOTS_MAX, LAN_SERVE_SLOTS_MIN
from hsync_common.protocol.schemas import (
    LAN_TXT_KEYS,
    LAN_TXT_REQUIRED_KEYS,
    build_lan_sources_schema,
    build_lan_txt_schema,
    build_lan_wss_schema,
    build_ws_schema,
)

_REGEN_HINT = "Regenerate with: poetry run python scripts/export_protocol_schemas.py"


class TestSnapshotDrift:
    """The committed schemas must match the ones rebuilt from source."""

    def test_ws_snapshot_exists(self):
        assert WS_SCHEMA_PATH.is_file(), f"Missing {WS_SCHEMA_PATH}. {_REGEN_HINT}"

    def test_lan_snapshot_exists(self):
        assert LAN_TXT_SCHEMA_PATH.is_file(), f"Missing {LAN_TXT_SCHEMA_PATH}. {_REGEN_HINT}"

    def test_lan_wss_snapshot_exists(self):
        assert LAN_WSS_SCHEMA_PATH.is_file(), f"Missing {LAN_WSS_SCHEMA_PATH}. {_REGEN_HINT}"

    def test_lan_sources_snapshot_exists(self):
        assert LAN_SOURCES_SCHEMA_PATH.is_file(), (
            f"Missing {LAN_SOURCES_SCHEMA_PATH}. {_REGEN_HINT}"
        )

    def test_ws_snapshot_matches_source(self):
        committed = WS_SCHEMA_PATH.read_text(encoding="utf-8")
        assert dump_contract(build_ws_schema()) == committed, f"WS schema drift. {_REGEN_HINT}"

    def test_lan_snapshot_matches_source(self):
        committed = LAN_TXT_SCHEMA_PATH.read_text(encoding="utf-8")
        assert dump_contract(build_lan_txt_schema()) == committed, (
            f"LAN/TXT schema drift. {_REGEN_HINT}"
        )

    def test_lan_wss_snapshot_matches_source(self):
        committed = LAN_WSS_SCHEMA_PATH.read_text(encoding="utf-8")
        assert dump_contract(build_lan_wss_schema()) == committed, (
            f"LAN/WSS schema drift. {_REGEN_HINT}"
        )

    def test_lan_sources_snapshot_matches_source(self):
        committed = LAN_SOURCES_SCHEMA_PATH.read_text(encoding="utf-8")
        assert dump_contract(build_lan_sources_schema()) == committed, (
            f"LAN sources schema drift. {_REGEN_HINT}"
        )


class TestWsSchemaSource:
    """The WS schema is derived from the handshake/model source of truth."""

    def test_protocol_version_const(self):
        defs = build_ws_schema()["$defs"]
        for name in ("authRequest", "authOk", "authError"):
            assert defs[name]["properties"]["protocol_version"]["const"] == PROTOCOL_VERSION_WS

    def test_capabilities_enum_matches_registry(self):
        defs = build_ws_schema()["$defs"]
        expected = encode_capabilities(Capability)
        for name in ("authRequest", "authOk"):
            assert defs[name]["properties"]["capabilities"]["items"]["enum"] == expected

    def test_event_name_enum_matches_model(self):
        defs = build_ws_schema()["$defs"]
        assert defs["fileEvent"]["properties"]["name"]["enum"] == [e.value for e in EventName]

    def test_file_required_keys_match_filedict(self):
        defs = build_ws_schema()["$defs"]
        # ``version`` is NotRequired: only the always-present keys are required.
        assert defs["file"]["required"] == sorted(FileDict.__required_keys__)


class TestLanSchemaSource:
    """The LAN/TXT schema is derived from the source-of-truth key registry."""

    def test_protocol_const(self):
        schema = build_lan_txt_schema()
        assert schema["properties"]["protocol"]["const"] == PROTOCOL_VERSION_LAN

    def test_required_keys(self):
        schema = build_lan_txt_schema()
        assert schema["required"] == list(LAN_TXT_REQUIRED_KEYS)

    def test_all_keys_present(self):
        schema = build_lan_txt_schema()
        assert set(schema["properties"]) == set(LAN_TXT_KEYS)

    def test_peer_download_flag_is_optional_true_only(self):
        schema = build_lan_txt_schema()
        assert "peer_download" not in schema["required"]
        assert schema["properties"]["peer_download"]["enum"] == ["true"]


class TestLanWssSchemaSource:
    """The LAN/WSS handshake schema pins the handshake frames (ADR-0024)."""

    def _defs(self):
        return build_lan_wss_schema()["$defs"]

    def test_protocol_version_is_lan(self):
        defs = self._defs()
        for name in ("authRequired", "auth", "authOk", "authFailed", "hello"):
            assert defs[name]["properties"]["protocol_version"]["const"] == PROTOCOL_VERSION_LAN

    def test_capabilities_enum_matches_registry(self):
        defs = self._defs()
        expected = encode_capabilities(Capability)
        for name in ("authRequired", "auth", "authOk", "hello"):
            assert defs[name]["properties"]["capabilities"]["items"]["enum"] == expected

    def test_auth_failed_carries_reason(self):
        assert self._defs()["authFailed"]["properties"]["status"]["const"] == "failed"
        assert "reason" in self._defs()["authFailed"]["required"]

    def test_inventory_extends_lan_one_additively(self):
        schema = build_lan_wss_schema()
        assert {"$ref": "#/$defs/inventory"} in schema["slaveToMaster"]["oneOf"]
        assert {"$ref": "#/$defs/inventoryAck"} in schema["masterToSlave"]["oneOf"]
        assert {"$ref": "#/$defs/fileEvent"} in schema["slaveToMaster"]["oneOf"]

    def test_inventory_limits_and_modes(self):
        defs = self._defs()
        snapshot = defs["inventorySnapshot"]
        delta = defs["inventoryDelta"]
        assert snapshot["properties"]["entries"]["maxItems"] == 500
        assert delta["properties"]["entries"]["maxItems"] == 500
        assert delta["properties"]["entries"]["minItems"] == 1
        assert delta["properties"]["more"]["const"] is False
        assert snapshot["properties"]["gen"]["maximum"] == (1 << 63) - 1

    def test_empty_snapshot_is_terminal_sequence_zero(self):
        empty_rule = self._defs()["inventorySnapshot"]["allOf"][0]
        assert empty_rule["if"]["properties"]["entries"]["maxItems"] == 0
        assert empty_rule["then"]["properties"]["seq"]["const"] == 0
        assert empty_rule["then"]["properties"]["more"]["const"] is False

    def test_inventory_ack_statuses(self):
        defs = self._defs()
        assert defs["inventoryAckOk"]["properties"]["status"]["const"] == "ok"
        assert defs["inventoryAckResync"]["properties"]["status"]["const"] == "resync"
        rejected = defs["inventoryAckRejected"]
        assert rejected["properties"]["status"]["const"] == "rejected"
        assert "reason" in rejected["required"]


class TestLanSourcesSchemaSource:
    """The sources schema pins strict objects and batch/candidate limits."""

    def _defs(self):
        return build_lan_sources_schema()["$defs"]

    def test_request_contract(self):
        schema = build_lan_sources_schema()
        request = schema["$defs"]["request"]
        assert schema["x-contentType"] == "application/json"
        assert schema["x-maxBodyBytes"] == 2 * 1024 * 1024
        assert request["additionalProperties"] is False
        assert request["properties"]["files"]["minItems"] == 1
        assert request["properties"]["files"]["maxItems"] == 500
        assert request["properties"]["cid"]["pattern"] == CID_PATTERN

    def test_response_contract(self):
        defs = self._defs()
        assert defs["response"]["additionalProperties"] is False
        assert defs["responseFile"]["properties"]["sources"]["maxItems"] == 8
        assert defs["sourceCandidate"]["additionalProperties"] is False
        download_url = defs["sourceCandidate"]["properties"]["download_url"]
        assert download_url["x-host"] == "ip-literal"
        assert download_url["x-explicitPort"] is True

    def test_hashes_are_canonical_lowercase(self):
        assert self._defs()["requestFile"]["properties"]["sha256"]["pattern"] == ("^[0-9a-f]{64}$")

    def test_paths_publish_utf8_byte_bound(self):
        path = self._defs()["requestFile"]["properties"]["path"]
        assert path["maxLength"] == 4096
        assert path["x-maxUtf8Bytes"] == 4096


class TestLanWssHandshakeConformance:
    """The LAN-WSS builders emit frames that match the handshake contract."""

    def _defs(self):
        return build_lan_wss_schema()["$defs"]

    def test_auth_required_conforms(self):
        frame = build_lan_auth_required(capabilities={Capability.compression})
        assert set(frame) == set(self._defs()["authRequired"]["required"])

    def test_auth_conforms(self):
        frame = build_lan_auth(token="t", cid="TestClientA1234567890", capabilities=set())
        assert set(frame) == set(self._defs()["auth"]["required"])

    def test_auth_ok_conforms(self):
        frame = build_lan_auth_ok(capabilities=set())
        assert set(frame) == set(self._defs()["authOk"]["required"])

    def test_auth_failed_conforms(self):
        frame = build_lan_auth_failed(reason="invalid_token")
        assert set(frame) == set(self._defs()["authFailed"]["required"])

    def test_hello_master_conforms(self):
        frame = build_lan_hello(capabilities=set())
        assert set(frame) == set(self._defs()["hello"]["required"])

    def test_hello_slave_conforms(self):
        frame = build_lan_hello(capabilities=set(), cid="TestClientA1234567890")
        assert "cid" in frame
        assert set(frame) - {"cid"} == set(self._defs()["hello"]["required"])

    def test_serve_slots_is_an_optional_declared_property(self):
        """A seeding node advertises its capacity inside the declared contract."""
        defs = self._defs()
        for name in ("auth", "hello"):
            prop = defs[name]["properties"]["serve_slots"]
            assert prop == {
                "type": "integer",
                "minimum": LAN_SERVE_SLOTS_MIN,
                "maximum": LAN_SERVE_SLOTS_MAX,
                "description": prop["description"],
            }
            assert "serve_slots" not in defs[name]["required"]
            assert defs[name]["additionalProperties"] is False

    def test_auth_with_serve_slots_conforms(self):
        frame = build_lan_auth(
            token="t",
            cid="TestClientA1234567890",
            capabilities={Capability.peer_download},
            serve_slots=LAN_SERVE_SLOTS_MAX,
        )
        assert frame["serve_slots"] == LAN_SERVE_SLOTS_MAX
        assert set(frame) - {"serve_slots"} == set(self._defs()["auth"]["required"])

    def test_hello_with_serve_slots_conforms(self):
        frame = build_lan_hello(
            capabilities={Capability.peer_download},
            cid="TestClientA1234567890",
            serve_slots=LAN_SERVE_SLOTS_MIN,
        )
        assert frame["serve_slots"] == LAN_SERVE_SLOTS_MIN
        assert set(frame) - {"serve_slots", "cid"} == set(self._defs()["hello"]["required"])

    def test_omitting_serve_slots_is_a_non_seeding_node(self):
        """The field is absent for a node that serves nothing: no empty sentinel."""
        assert "serve_slots" not in build_lan_hello(capabilities=set())
        assert "serve_slots" not in build_lan_auth(
            token="t", cid="TestClientA1234567890", capabilities=set()
        )

    @pytest.mark.parametrize("serve_slots", [0, -1, LAN_SERVE_SLOTS_MAX + 1, True, 2.5])
    def test_out_of_range_serve_slots_fails_at_the_sender(self, serve_slots):
        with pytest.raises(ValueError, match="serve_slots"):
            build_lan_auth(
                token="t", cid="TestClientA1234567890", capabilities=set(), serve_slots=serve_slots
            )


class TestHandshakeConformance:
    """The handshake builders emit frames that match the WS contract."""

    def test_auth_request_conforms(self):
        defs = build_ws_schema()["$defs"]["authRequest"]
        frame = build_ws_auth_request(
            token="t", app_version="1.0.0", capabilities={Capability.compression}
        )
        assert set(frame) == set(defs["required"])
        assert frame["protocol_version"] == PROTOCOL_VERSION_WS
        assert set(frame["capabilities"]) <= set(
            defs["properties"]["capabilities"]["items"]["enum"]
        )

    def test_auth_ok_conforms(self):
        defs = build_ws_schema()["$defs"]["authOk"]
        frame = build_ws_auth_ok(app_version="1.0.0", capabilities=set())
        assert set(frame) == set(defs["required"])

    def test_auth_error_conforms(self):
        defs = build_ws_schema()["$defs"]["authError"]
        frame = build_ws_auth_error(error="protocol_incompatible", client_protocol_version="ws/0")
        assert set(frame) == set(defs["required"])


class TestEventConformance:
    """A serialized Event matches the fileEvent contract."""

    def test_event_dict_conforms(self):
        defs = build_ws_schema()["$defs"]["fileEvent"]
        event = Event(
            cid="c1",
            localpath="/data",
            bucket="b1",
            name=EventName.added,
            src=File(filepath="/data/a.txt", size=3),
        )
        payload = event.to_dict()
        assert set(defs["required"]) <= set(payload)
        assert payload["name"] in defs["properties"]["name"]["enum"]
        assert set(payload["src"]) == set(FileDict.__required_keys__)
