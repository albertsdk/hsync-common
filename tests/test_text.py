# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for hsync_common.text helpers."""

from json import loads

from hsync_common.text import escape_loguru_braces, safe_json_for_log


class TestEscapeLoguruBraces:
    def test_doubles_curly_braces(self):
        assert escape_loguru_braces("a {b} c") == "a {{b}} c"

    def test_doubles_each_brace_independently(self):
        assert escape_loguru_braces("{a} and {b}") == "{{a}} and {{b}}"

    def test_passthrough_when_no_braces(self):
        assert escape_loguru_braces("no braces here") == "no braces here"

    def test_empty_string(self):
        assert escape_loguru_braces("") == ""


class TestSafeJsonForLog:
    def test_dict_is_serialized_and_escaped(self):
        result = safe_json_for_log({"key": "value"})
        assert "{{" in result
        assert "}}" in result

    def test_no_unescaped_braces_remain(self):
        result = safe_json_for_log({"a": {"b": 1}})
        # After removing the escaped form, no stray single braces should remain.
        assert "{" not in result.replace("{{", "")
        assert "}" not in result.replace("}}", "")

    def test_string_payload_is_quoted(self):
        # json.dumps("hello") yields '"hello"' which has no braces.
        assert safe_json_for_log("hello") == '"hello"'

    def test_unescaping_yields_valid_json(self):
        payload = {"a": 1, "b": [True, None, "x"]}
        result = safe_json_for_log(payload)
        roundtripped = loads(result.replace("{{", "{").replace("}}", "}"))
        assert roundtripped == payload
