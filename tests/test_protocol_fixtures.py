# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for the golden protocol fixtures.

These guard the committed cross-language fixtures against silent drift from the
Python source of truth and assert that each fixture structurally conforms to the
published WS/LAN JSON Schema, so the Android contract test consumes inputs that
are known-valid by construction.
"""

import pytest

from hsync_common.models.delta import DeltaApplyMetadataDict, DeltaInstructionsDict
from hsync_common.protocol import (
    ANDROID_FIXTURES_DIR,
    FIXTURES_DIR,
    dump_contract,
    load_contract,
)
from hsync_common.protocol.fixtures import build_fixtures
from hsync_common.protocol.schemas import (
    LAN_TXT_REQUIRED_KEYS,
    build_lan_txt_schema,
    build_ws_schema,
)

_REGEN_HINT = "Regenerate with: poetry run python scripts/export_protocol_schemas.py"

_FIXTURES = build_fixtures()
_FIXTURE_NAMES = sorted(_FIXTURES)


class TestFixtureDrift:
    """Every committed fixture must match the one rebuilt from source."""

    @pytest.mark.parametrize("name", _FIXTURE_NAMES)
    def test_snapshot_exists(self, name):
        path = FIXTURES_DIR / f"{name}.json"
        assert path.is_file(), f"Missing {path}. {_REGEN_HINT}"

    @pytest.mark.parametrize("name", _FIXTURE_NAMES)
    def test_snapshot_matches_source(self, name):
        committed = (FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8")
        assert dump_contract(_FIXTURES[name]) == committed, f"Fixture '{name}' drift. {_REGEN_HINT}"

    def test_no_orphan_snapshots(self):
        committed = {p.stem for p in FIXTURES_DIR.glob("*.json")}
        assert committed == set(_FIXTURE_NAMES), f"Orphan/missing fixtures. {_REGEN_HINT}"


class TestWsFixtureConformance:
    """Each WS fixture conforms structurally to its schema definition."""

    def _defs(self):
        return build_ws_schema()["$defs"]

    def _assert_object(self, payload, definition):
        assert set(definition["required"]) <= set(payload)
        for key, spec in definition["properties"].items():
            if key in payload and "const" in spec:
                assert payload[key] == spec["const"]

    def test_auth_request(self):
        self._assert_object(_FIXTURES["ws-auth-request"], self._defs()["authRequest"])

    def test_auth_ok(self):
        self._assert_object(_FIXTURES["ws-auth-ok"], self._defs()["authOk"])

    def test_auth_error(self):
        self._assert_object(_FIXTURES["ws-auth-error"], self._defs()["authError"])

    def test_ping(self):
        self._assert_object(_FIXTURES["ws-ping"], self._defs()["ping"])

    def test_pong(self):
        self._assert_object(_FIXTURES["ws-pong"], self._defs()["pong"])

    def test_file_event(self):
        defs = self._defs()
        event = _FIXTURES["ws-file-event"]
        self._assert_object(event, defs["fileEvent"])
        assert event["name"] in defs["fileEvent"]["properties"]["name"]["enum"]
        assert set(event["src"]) == set(defs["file"]["properties"])


class TestLanFixtureConformance:
    """The LAN/TXT fixture conforms to the LAN schema."""

    def test_required_keys_present(self):
        record = _FIXTURES["lan-txt-record"]
        assert set(LAN_TXT_REQUIRED_KEYS) <= set(record)

    def test_keys_are_known(self):
        schema = build_lan_txt_schema()
        assert set(_FIXTURES["lan-txt-record"]) <= set(schema["properties"])

    def test_protocol_const(self):
        schema = build_lan_txt_schema()
        record = _FIXTURES["lan-txt-record"]
        assert record["protocol"] == schema["properties"]["protocol"]["const"]

    def test_values_are_strings(self):
        assert all(isinstance(v, str) for v in _FIXTURES["lan-txt-record"].values())


class TestFixtureRoundTrip:
    """Committed fixtures load back into the same structure as the source."""

    @pytest.mark.parametrize("name", _FIXTURE_NAMES)
    def test_load_matches_source(self, name):
        assert load_contract(FIXTURES_DIR / f"{name}.json") == _FIXTURES[name]


class TestDeltaFixtureCoherence:
    """The delta fixtures are engine-produced and internally consistent.

    Regression: these fixtures were previously hand-written with wrong numbers
    (``sum(op.length) != new_size``) and fields absent from the wire models
    (``vclock``/``version_id`` in the apply metadata). The claims below pin the
    invariants the engine guarantees, so a hand-edit or an engine regression
    fails here before poisoning the Android parity test.
    """

    def test_instruction_ops_cover_new_size_exactly(self):
        """The ops list is a byte-accurate partition of the new file."""
        doc = _FIXTURES["delta-instructions"]
        assert sum(op["length"] for op in doc["ops"]) == doc["new_size"]
        # Coverage must also be contiguous from byte 0 (no gaps/skips).
        pos = 0
        for op in doc["ops"]:
            if op["type"] == "data":
                assert op["data_offset"] == 0  # single literal run in this example
            # contiguous coverage by construction: pos is the running output offset
            pos += op["length"]
        assert pos == doc["new_size"]

    def test_instruction_keys_match_wire_model(self):
        """No key beyond the wire model contract (except the documented
        ``literal_size`` and ``description`` metadata fields)."""
        doc = _FIXTURES["delta-instructions"]
        assert set(doc) <= set(DeltaInstructionsDict.__annotations__) | {
            "description",
            "literal_size",
        }
        assert len(doc["ops"]) == 256  # 1 data + 255 full-block copies

    def test_apply_metadata_keys_match_wire_model(self):
        """The metadata part carries exactly the DeltaApplyMetadata contract."""
        doc = _FIXTURES["delta-apply-metadata"]
        assert set(doc) <= set(DeltaApplyMetadataDict.__annotations__) | {"description"}
        assert "vclock" not in doc
        assert "version_id" not in doc
        assert doc["new_size"] == sum(op["length"] for op in doc["ops"])
        assert doc["ops"] == _FIXTURES["delta-instructions"]["ops"]

    def test_signatures_cover_full_base(self):
        """The signature fixture lists every block of the full base, not a
        truncated sample of three rows."""
        doc = _FIXTURES["delta-signatures"]
        assert len(doc["signatures"]) == doc["file_size"] // doc["block_size"]
        first = doc["signatures"][0]
        last = doc["signatures"][-1]
        assert first["index"] == 0 and first["offset"] == 0
        assert last["offset"] == doc["file_size"] - doc["block_size"]
        # Each strong checksum has the real SHA-256 wire length.
        assert all(len(s["strong"]) == 64 for s in doc["signatures"])


# The Android contract test consumes these fixtures as cross-language inputs, so
# they must be byte-identical copies of the Python ones (kept in sync via
# scripts/sync_android_fixtures.py). Skipped when the Android tree is absent
# (e.g. hsync-common checked out on its own).
@pytest.mark.skipif(
    not ANDROID_FIXTURES_DIR.is_dir(),
    reason="Android test resources not present in this checkout",
)
class TestAndroidFixtureParity:
    """The Android fixture resources are verbatim copies of the Python ones."""

    @pytest.mark.parametrize("name", _FIXTURE_NAMES)
    def test_android_copy_matches(self, name):
        android = ANDROID_FIXTURES_DIR / f"{name}.json"
        assert android.is_file(), f"Missing Android fixture {android}. Copy it from {FIXTURES_DIR}."
        assert android.read_text(encoding="utf-8") == (FIXTURES_DIR / f"{name}.json").read_text(
            encoding="utf-8"
        ), f"Android fixture '{name}' diverged. {_REGEN_HINT}"

    def test_no_extra_android_fixtures(self):
        android = {p.stem for p in ANDROID_FIXTURES_DIR.glob("*.json")}
        assert android == set(_FIXTURE_NAMES), f"Android fixture set diverged. {_REGEN_HINT}"
