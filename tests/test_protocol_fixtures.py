# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for the golden protocol fixtures (DESIGN_REVIEW §1 / P0-A, Fase 4).

These guard the committed cross-language fixtures against silent drift from the
Python source of truth and assert that each fixture structurally conforms to the
published WS/LAN JSON Schema, so the Android contract test consumes inputs that
are known-valid by construction.
"""

import pytest

from hsync_common.protocol import (
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


# Sibling Android test resources: the contract test consumes these as the cross-
# language inputs, so they must be byte-identical copies of the Python fixtures.
# Resolved relative to the monorepo root; skipped when the Android tree is absent
# (e.g. hsync-common checked out on its own).
_ANDROID_FIXTURES_DIR = (
    FIXTURES_DIR.parents[3]
    / "hsync-android"
    / "app"
    / "src"
    / "test"
    / "resources"
    / "protocol"
    / "fixtures"
)


@pytest.mark.skipif(
    not _ANDROID_FIXTURES_DIR.is_dir(),
    reason="Android test resources not present in this checkout",
)
class TestAndroidFixtureParity:
    """The Android fixture resources are verbatim copies of the Python ones."""

    @pytest.mark.parametrize("name", _FIXTURE_NAMES)
    def test_android_copy_matches(self, name):
        android = _ANDROID_FIXTURES_DIR / f"{name}.json"
        assert android.is_file(), f"Missing Android fixture {android}. Copy it from {FIXTURES_DIR}."
        assert android.read_text(encoding="utf-8") == (FIXTURES_DIR / f"{name}.json").read_text(
            encoding="utf-8"
        ), f"Android fixture '{name}' diverged. {_REGEN_HINT}"

    def test_no_extra_android_fixtures(self):
        android = {p.stem for p in _ANDROID_FIXTURES_DIR.glob("*.json")}
        assert android == set(_FIXTURE_NAMES), f"Android fixture set diverged. {_REGEN_HINT}"
