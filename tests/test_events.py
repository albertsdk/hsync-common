"""Tests for hsync_common.protocol.events."""

import json

from hsync_common.protocol.events import (
    EVENTS_SCHEMA_VERSION,
    UiEventName,
    build_event,
    parse_event_line,
    serialize_event,
)


class TestBuildEvent:
    def test_sets_envelope_fields(self):
        ev = build_event(UiEventName.sync_complete)
        assert ev["schema_version"] == EVENTS_SCHEMA_VERSION
        assert ev["event"] == "sync_complete"
        assert isinstance(ev["ts"], str) and ev["ts"].endswith("Z")

    def test_accepts_plain_string_event(self):
        ev = build_event("status", status="connected")
        assert ev["event"] == "status"
        assert ev["status"] == "connected"  # type: ignore[reportTypedDictNotRequiredAccess]

    def test_explicit_ts_is_preserved(self):
        ev = build_event(UiEventName.peers, ts="2026-06-19T10:00:00Z", connected=3, total=5)
        assert ev["ts"] == "2026-06-19T10:00:00Z"
        assert ev["connected"] == 3  # type: ignore[reportTypedDictNotRequiredAccess]
        assert ev["total"] == 5  # type: ignore[reportTypedDictNotRequiredAccess]

    def test_drops_none_payload_values(self):
        ev = build_event(UiEventName.transfer, op="download", file="a.txt", size=None)
        assert "size" not in ev
        assert ev["op"] == "download"  # type: ignore[reportTypedDictNotRequiredAccess]
        assert ev["file"] == "a.txt"  # type: ignore[reportTypedDictNotRequiredAccess]

    def test_keeps_falsey_non_none_values(self):
        ev = build_event(UiEventName.role, is_master=False)
        assert ev["is_master"] is False  # type: ignore[reportTypedDictNotRequiredAccess]
        ev2 = build_event(UiEventName.progress, transferred=0, total=10)
        assert ev2["transferred"] == 0  # type: ignore[reportTypedDictNotRequiredAccess]

    def test_discovery_event_carries_the_active_plan(self):
        ev = build_event(UiEventName.discovery, plan="bootnode", bootnode="boot.example.net")
        assert ev["event"] == "discovery"
        assert ev["plan"] == "bootnode"  # type: ignore[reportTypedDictNotRequiredAccess]
        assert ev["bootnode"] == "boot.example.net"  # type: ignore[reportTypedDictNotRequiredAccess]
        # The mDNS plan omits the bootnode field (None payload values are dropped).
        mdns = build_event(UiEventName.discovery, plan="mdns")
        assert "bootnode" not in mdns

    def test_folder_size_event_carries_aggregate_bytes(self):
        ev = build_event(UiEventName.folder_size, local_bytes=1024, total_bytes=4096)
        assert ev["event"] == "folder_size"
        assert ev["local_bytes"] == 1024  # type: ignore[reportTypedDictNotRequiredAccess]
        assert ev["total_bytes"] == 4096  # type: ignore[reportTypedDictNotRequiredAccess]
        assert ev["schema_version"] == EVENTS_SCHEMA_VERSION

    def test_transfer_accepts_optional_source_cid(self):
        ev = build_event(
            UiEventName.transfer,
            op="download",
            file="a.bin",
            source_cid="TestClientA1234567890",
        )
        assert ev["source_cid"] == "TestClientA1234567890"  # type: ignore[reportTypedDictNotRequiredAccess]


class TestSerializeEvent:
    def test_round_trips_through_json(self):
        ev = build_event(UiEventName.transfer, op="upload", file="docs/a.txt")
        line = serialize_event(ev)
        assert "\n" not in line
        assert json.loads(line) == ev

    def test_is_compact(self):
        line = serialize_event(build_event(UiEventName.sync_complete, ts="t"))
        assert ", " not in line and ": " not in line

    def test_preserves_unicode(self):
        ev = build_event(UiEventName.transfer, op="download", file="café/ä.txt")
        assert "café/ä.txt" in serialize_event(ev)


class TestParseEventLine:
    def test_parses_built_event(self):
        ev = build_event(UiEventName.status, status="connected")
        assert parse_event_line(serialize_event(ev)) == ev

    def test_tolerates_surrounding_whitespace(self):
        ev = build_event(UiEventName.sync_complete, ts="t")
        assert parse_event_line("  " + serialize_event(ev) + "  \n") == ev

    def test_blank_line_is_none(self):
        assert parse_event_line("") is None
        assert parse_event_line("   \n") is None

    def test_non_json_log_line_is_none(self):
        assert parse_event_line("2026-06-19T10:00:00Z - [123] INFO: hello") is None

    def test_non_object_json_is_none(self):
        assert parse_event_line("[1, 2, 3]") is None
        assert parse_event_line('"a string"') is None

    def test_missing_event_field_is_none(self):
        assert parse_event_line(json.dumps({"schema_version": EVENTS_SCHEMA_VERSION})) is None

    def test_wrong_schema_version_is_none(self):
        payload = {"schema_version": EVENTS_SCHEMA_VERSION + 1, "event": "status"}
        assert parse_event_line(json.dumps(payload)) is None

    def test_missing_schema_version_is_none(self):
        assert parse_event_line(json.dumps({"event": "status"})) is None


class TestEventNameCoverage:
    def test_all_names_are_unique_values(self):
        values = [m.value for m in UiEventName]
        assert len(values) == len(set(values))

    def test_expected_names_present(self):
        """The full documented event set matches the enum exactly.

        ``conflict_resolved`` and ``security_rejected`` are part of the public
        channel; the equality check pins *every* drift (addition, removal or
        rename), not just the accidental omission of one member.
        """
        names = {m.value for m in UiEventName}
        expected = {
            "status",
            "ready",
            "peers",
            "role",
            "bucket",
            "group",
            "discovery",
            "session",
            "server",
            "transfer",
            "rename",
            "dir_created",
            "progress",
            "sync_complete",
            "error",
            "auth_error",
            "path_not_found",
            "master_conflict",
            "no_master",
            "no_peers",
            "sync_pending",
            "preview_start",
            "preview_end",
            "status_pass_start",
            "status_pass_end",
            "file_status",
            "rename_status",
            "fingerprint_changed",
            "auth_required",
            "pairing_needed",
            "duplicate_identity",
            "transfer_failed",
            "sync_paused",
            "conflict_resolved",
            "security_rejected",
            "folder_size",
        }
        assert expected == names
