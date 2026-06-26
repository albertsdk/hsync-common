# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Text helpers shared across HSYNC projects.

Currently exposes loguru-safe formatting primitives:

- :func:`escape_loguru_markup` neutralizes every character loguru treats as
  markup in a literal string: curly braces (format placeholders) are doubled
  and the ``<`` that opens a color tag is backslash-escaped. This lets
  arbitrary third-party or user content be interpolated into a loguru format
  template without raising ``ValueError`` (e.g. ``<locals>`` in tenacity
  retry messages) or ``KeyError`` (e.g. JSON payloads).
- :func:`safe_json_for_log` serializes any JSON-compatible object to a string
  via :func:`json.dumps` and then escapes its markup.
"""

from __future__ import annotations

from json import dumps
from typing import Any


def escape_loguru_markup(s: str) -> str:
    """Escape loguru markup in *s* so it is rendered verbatim.

    Doubles ``{`` / ``}`` so they are not read as format placeholders and
    backslash-escapes ``<`` so it does not open a color tag. ``>`` is harmless
    on its own and is left untouched.
    """
    return s.replace("{", "{{").replace("}", "}}").replace("<", r"\<")


def safe_json_for_log(obj: Any) -> str:
    """Serialize *obj* to JSON and escape loguru markup for safe logging."""
    return escape_loguru_markup(dumps(obj))
