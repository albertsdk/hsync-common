# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for the shared --capabilities-json document."""

import json

from hsync_common.protocol.capabilities import (
    CAPABILITIES_SCHEMA_VERSION,
    build_capabilities,
    parse_capabilities,
    supports_cli_option,
)
from hsync_common.protocol.events import EVENTS_SCHEMA_VERSION
from hsync_common.protocol.handshake import (
    ALL_CAPABILITIES,
    PROTOCOL_VERSION_LAN,
    PROTOCOL_VERSION_REST,
    PROTOCOL_VERSION_WS,
    Capability,
    encode_capabilities,
)


class TestBuildCapabilities:
    def test_assembles_from_protocol_ssot(self):
        doc = build_capabilities(app_version="1.2.3", cli_options=["--never-master", "--lan-mode"])
        assert doc["schema_version"] == CAPABILITIES_SCHEMA_VERSION
        assert doc["app_version"] == "1.2.3"
        assert doc["protocol_version"] == {
            "rest": PROTOCOL_VERSION_REST,
            "ws": PROTOCOL_VERSION_WS,
            "lan": PROTOCOL_VERSION_LAN,
        }
        assert doc["events_schema_version"] == EVENTS_SCHEMA_VERSION

    def test_defaults_to_all_capabilities(self):
        doc = build_capabilities(app_version="1.0.0", cli_options=[])
        assert doc["capabilities"] == encode_capabilities(ALL_CAPABILITIES)
        assert Capability.never_master.value in doc["capabilities"]

    def test_explicit_capabilities_are_encoded(self):
        doc = build_capabilities(
            app_version="1.0.0",
            cli_options=[],
            capabilities={Capability.compression, "https"},
        )
        assert doc["capabilities"] == ["compression", "https"]

    def test_cli_options_are_sorted_and_deduped(self):
        doc = build_capabilities(
            app_version="1.0.0",
            cli_options=["--lan-mode", "--never-master", "--lan-mode"],
        )
        assert doc["cli_options"] == ["--lan-mode", "--never-master"]


class TestParseCapabilities:
    def test_round_trip(self):
        doc = build_capabilities(app_version="9.9.9", cli_options=["--lan-mode"])
        parsed = parse_capabilities(json.dumps(doc))
        assert parsed == doc

    def test_rejects_blank(self):
        assert parse_capabilities("   ") is None

    def test_rejects_malformed_json(self):
        assert parse_capabilities("{not json") is None

    def test_rejects_non_object(self):
        assert parse_capabilities("[1, 2, 3]") is None

    def test_rejects_unknown_schema_version(self):
        doc = build_capabilities(app_version="1.0.0", cli_options=[])
        doc["schema_version"] = CAPABILITIES_SCHEMA_VERSION + 1
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_missing_required_key(self):
        doc = build_capabilities(app_version="1.0.0", cli_options=[])
        del doc["cli_options"]  # type: ignore[reportGeneralTypeIssues]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_string_cli_options(self):
        # Key presence alone is not enough: a plain-string cli_options would
        # make supports_cli_option match substrings instead of flags.
        doc = build_capabilities(app_version="1.0.0", cli_options=[])
        doc["cli_options"] = "--never-master"  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_non_list_capabilities(self):
        doc = build_capabilities(app_version="1.0.0", cli_options=[])
        doc["capabilities"] = "compression"  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_non_string_list_entries(self):
        doc = build_capabilities(app_version="1.0.0", cli_options=[])
        doc["cli_options"] = [42]  # type: ignore[list-item]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_malformed_protocol_version(self):
        doc = build_capabilities(app_version="1.0.0", cli_options=[])
        doc["protocol_version"] = {"rest": 1, "ws": "ws/1"}  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_wrong_scalar_types(self):
        doc = build_capabilities(app_version="1.0.0", cli_options=[])
        doc["app_version"] = 123  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc)) is None
        doc2 = build_capabilities(app_version="1.0.0", cli_options=[])
        doc2["events_schema_version"] = True  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc2)) is None


class TestSupportsCliOption:
    def test_present_flag(self):
        doc = build_capabilities(app_version="1.0.0", cli_options=["--never-master"])
        assert supports_cli_option(doc, "--never-master") is True

    def test_absent_flag(self):
        doc = build_capabilities(app_version="1.0.0", cli_options=["--lan-mode"])
        assert supports_cli_option(doc, "--never-master") is False

    def test_none_document_is_conservatively_supported(self):
        assert supports_cli_option(None, "--never-master") is True
