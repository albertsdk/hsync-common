# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Text helpers shared across HSYNC projects.

Currently exposes loguru-safe formatting primitives:

- :func:`escape_loguru_braces` doubles curly braces so a literal string can be
  safely interpolated into a loguru format template without being mistaken
  for a positional placeholder.
- :func:`safe_json_for_log` serializes any JSON-compatible object to a string
  via :func:`json.dumps` and then escapes its braces.
"""

from __future__ import annotations

from json import dumps
from typing import Any


def escape_loguru_braces(s: str) -> str:
    """Escape ``{`` and ``}`` in *s* so loguru does not treat them as placeholders."""
    return s.replace("{", "{{").replace("}", "}}")


def safe_json_for_log(obj: Any) -> str:
    """Serialize *obj* to JSON and escape braces for safe loguru logging."""
    return escape_loguru_braces(dumps(obj))
