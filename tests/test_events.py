"""Tests for hsync_common.protocol.events (P0-B structured event channel)."""

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
        assert ev["status"] == "connected"

    def test_explicit_ts_is_preserved(self):
        ev = build_event(UiEventName.peers, ts="2026-06-19T10:00:00Z", count=3)
        assert ev["ts"] == "2026-06-19T10:00:00Z"
        assert ev["count"] == 3

    def test_drops_none_payload_values(self):
        ev = build_event(UiEventName.transfer, op="download", file="a.txt", size=None)
        assert "size" not in ev
        assert ev["op"] == "download"
        assert ev["file"] == "a.txt"

    def test_keeps_falsey_non_none_values(self):
        ev = build_event(UiEventName.role, is_master=False)
        assert ev["is_master"] is False
        ev2 = build_event(UiEventName.progress, transferred=0, total=10)
        assert ev2["transferred"] == 0


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
        names = {m.value for m in UiEventName}
        expected = {
            "status",
            "peers",
            "role",
            "bucket",
            "group",
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
            "preview_start",
            "preview_end",
            "file_status",
            "rename_status",
            "fingerprint_changed",
            "auth_required",
            "pairing_needed",
            "transfer_failed",
            "sync_paused",
        }
        assert expected <= names
