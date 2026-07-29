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

from hsync_common.models.event import Event, EventName
from hsync_common.models.file import File, FileDict
from hsync_common.protocol import (
    LAN_TXT_SCHEMA_PATH,
    WS_SCHEMA_PATH,
    dump_contract,
)
from hsync_common.protocol.handshake import (
    PROTOCOL_VERSION_LAN,
    PROTOCOL_VERSION_WS,
    Capability,
    build_ws_auth_error,
    build_ws_auth_ok,
    build_ws_auth_request,
    encode_capabilities,
)
from hsync_common.protocol.schemas import (
    LAN_TXT_KEYS,
    LAN_TXT_REQUIRED_KEYS,
    build_lan_txt_schema,
    build_ws_schema,
)

_REGEN_HINT = "Regenerate with: poetry run python scripts/export_protocol_schemas.py"


class TestSnapshotDrift:
    """The committed schemas must match the ones rebuilt from source."""

    def test_ws_snapshot_exists(self):
        assert WS_SCHEMA_PATH.is_file(), f"Missing {WS_SCHEMA_PATH}. {_REGEN_HINT}"

    def test_lan_snapshot_exists(self):
        assert LAN_TXT_SCHEMA_PATH.is_file(), f"Missing {LAN_TXT_SCHEMA_PATH}. {_REGEN_HINT}"

    def test_ws_snapshot_matches_source(self):
        committed = WS_SCHEMA_PATH.read_text(encoding="utf-8")
        assert dump_contract(build_ws_schema()) == committed, f"WS schema drift. {_REGEN_HINT}"

    def test_lan_snapshot_matches_source(self):
        committed = LAN_TXT_SCHEMA_PATH.read_text(encoding="utf-8")
        assert dump_contract(build_lan_txt_schema()) == committed, (
            f"LAN/TXT schema drift. {_REGEN_HINT}"
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
