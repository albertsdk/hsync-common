# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for the shared --capabilities-json document."""

import json

from hsync_common.protocol.bootnode import PROTOCOL_VERSION_BOOT
from hsync_common.protocol.capabilities import (
    CAPABILITIES_SCHEMA_VERSION,
    build_capabilities,
    parse_capabilities,
    supports_cli_option,
    supports_subcommand,
)
from hsync_common.protocol.events import EVENTS_SCHEMA_VERSION
from hsync_common.protocol.handshake import (
    PROTOCOL_VERSION_P2P,
    PROTOCOL_VERSION_REST,
    PROTOCOL_VERSION_WS,
    Capability,
)


def _doc(**overrides):
    """Build a valid capabilities document, optionally overriding fields."""
    doc = build_capabilities(
        app_version="1.0.0",
        subcommands=["p2p", "server"],
        cli_options_by_subcommand={
            "p2p": ["--force-master", "--never-master"],
            "server": ["--ca-cert", "--insecure"],
        },
    )
    doc.update(overrides)
    return doc


class TestBuildCapabilities:
    def test_assembles_from_protocol_ssot(self):
        doc = _doc(app_version="1.2.3")
        assert doc["schema_version"] == CAPABILITIES_SCHEMA_VERSION
        assert doc["app_version"] == "1.2.3"
        assert doc["protocol_version"] == {
            "rest": PROTOCOL_VERSION_REST,
            "ws": PROTOCOL_VERSION_WS,
            "p2p": PROTOCOL_VERSION_P2P,
            "boot": PROTOCOL_VERSION_BOOT,
        }
        assert doc["events_schema_version"] == EVENTS_SCHEMA_VERSION

    def test_defaults_to_all_capabilities(self):
        doc = build_capabilities(app_version="1.0.0", subcommands=[], cli_options_by_subcommand={})
        caps = doc["capabilities"]
        # Verify invariant properties rather than comparing against
        # encode_capabilities output (which would mask bugs in the encoder).
        assert isinstance(caps, list)
        assert len(caps) > 0
        assert all(isinstance(c, str) for c in caps)
        assert "compression" in caps
        assert Capability.never_master.value in caps

    def test_explicit_capabilities_are_encoded(self):
        doc = build_capabilities(
            app_version="1.0.0",
            subcommands=[],
            cli_options_by_subcommand={},
            capabilities={Capability.compression, "https"},
        )
        assert doc["capabilities"] == ["compression", "https"]

    def test_subcommands_are_sorted_and_deduped(self):
        doc = build_capabilities(
            app_version="1.0.0",
            subcommands=["server", "p2p", "server"],
            cli_options_by_subcommand={},
        )
        assert doc["subcommands"] == ["p2p", "server"]

    def test_cli_options_are_sorted_and_deduped_per_subcommand(self):
        doc = build_capabilities(
            app_version="1.0.0",
            subcommands=["p2p", "server"],
            cli_options_by_subcommand={
                "server": ["--insecure", "--ca-cert", "--insecure"],
                "p2p": ["--never-master", "--force-master"],
            },
        )
        assert doc["cli_options"] == {
            "p2p": ["--force-master", "--never-master"],
            "server": ["--ca-cert", "--insecure"],
        }


class TestParseCapabilities:
    def test_round_trip(self):
        doc = _doc(app_version="9.9.9")
        parsed = parse_capabilities(json.dumps(doc))
        assert parsed == doc

    def test_rejects_blank(self):
        assert parse_capabilities("   ") is None

    def test_rejects_malformed_json(self):
        assert parse_capabilities("{not json") is None

    def test_rejects_non_object(self):
        assert parse_capabilities("[1, 2, 3]") is None

    def test_rejects_unknown_schema_version(self):
        doc = _doc()
        doc["schema_version"] = CAPABILITIES_SCHEMA_VERSION + 1
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_missing_required_key(self):
        doc = _doc()
        del doc["subcommands"]  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_string_subcommands(self):
        # Key presence alone is not enough: a plain-string subcommands would
        # make supports_subcommand match substrings instead of names.
        doc = _doc()
        doc["subcommands"] = "p2p"  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_non_string_subcommand_entries(self):
        doc = _doc()
        doc["subcommands"] = ["p2p", 42]  # type: ignore[list-item]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_string_cli_options(self):
        doc = _doc()
        doc["cli_options"] = "--never-master"  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_non_list_cli_option_values(self):
        doc = _doc()
        doc["cli_options"] = {"p2p": "--never-master"}  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_non_string_cli_option_entries(self):
        doc = _doc()
        doc["cli_options"] = {"p2p": [42]}  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_non_list_capabilities(self):
        doc = _doc()
        doc["capabilities"] = "compression"  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_malformed_protocol_version(self):
        doc = _doc()
        doc["protocol_version"] = {"rest": 1, "ws": "ws/1"}  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_missing_boot_channel(self):
        # v3 added the ``boot`` channel: a document without it is not v3.
        doc = _doc()
        doc["protocol_version"] = {  # type: ignore[typeddict-item]
            "rest": PROTOCOL_VERSION_REST,
            "ws": PROTOCOL_VERSION_WS,
            "p2p": PROTOCOL_VERSION_P2P,
        }
        assert parse_capabilities(json.dumps(doc)) is None

    def test_rejects_wrong_scalar_types(self):
        doc = _doc()
        doc["app_version"] = 123  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc)) is None
        doc2 = _doc()
        doc2["events_schema_version"] = True  # type: ignore[typeddict-item]
        assert parse_capabilities(json.dumps(doc2)) is None


class TestSupportsCliOption:
    def test_present_flag_in_subcommand(self):
        doc = _doc()
        assert supports_cli_option(doc, "--force-master", subcommand="p2p") is True
        assert supports_cli_option(doc, "--ca-cert", subcommand="server") is True

    def test_absent_flag_in_subcommand(self):
        doc = _doc()
        assert supports_cli_option(doc, "--ca-cert", subcommand="p2p") is False
        assert supports_cli_option(doc, "--force-master", subcommand="server") is False

    def test_unknown_subcommand_is_absent(self):
        doc = _doc()
        assert supports_cli_option(doc, "--force-master", subcommand="unknown") is False

    def test_no_subcommand_checks_the_union(self):
        doc = _doc()
        assert supports_cli_option(doc, "--force-master") is True
        assert supports_cli_option(doc, "--ca-cert") is True
        assert supports_cli_option(doc, "--absent") is False

    def test_none_document_is_conservatively_supported(self):
        assert supports_cli_option(None, "--force-master") is True
        assert supports_cli_option(None, "--force-master", subcommand="p2p") is True


class TestSupportsSubcommand:
    def test_present_subcommand(self):
        assert supports_subcommand(_doc(), "p2p") is True
        assert supports_subcommand(_doc(), "server") is True

    def test_absent_subcommand(self):
        assert supports_subcommand(_doc(), "unknown") is False

    def test_none_document_is_conservatively_supported(self):
        assert supports_subcommand(None, "p2p") is True
