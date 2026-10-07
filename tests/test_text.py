# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for hsync_common.text helpers."""

from json import loads

from hsync_common.text import escape_loguru_markup, safe_json_for_log


class TestEscapeLoguruMarkup:
    def test_doubles_curly_braces(self):
        assert escape_loguru_markup("a {b} c") == "a {{b}} c"

    def test_doubles_each_brace_independently(self):
        assert escape_loguru_markup("{a} and {b}") == "{{a}} and {{b}}"

    def test_escapes_opening_angle_bracket(self):
        assert escape_loguru_markup("foo.<locals>.bar") == r"foo.\<locals>.bar"

    def test_escapes_braces_and_angle_brackets_together(self):
        assert escape_loguru_markup("{a}<b>") == r"{{a}}\<b>"

    def test_passthrough_when_no_markup(self):
        assert escape_loguru_markup("no markup here") == "no markup here"

    def test_empty_string(self):
        assert escape_loguru_markup("") == ""


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
