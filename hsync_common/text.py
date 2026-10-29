# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

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
- :func:`compact_json_str` / :func:`compact_json_bytes` serialize any
  JSON-compatible object to the canonical compact wire form used across the
  LAN/peer protocol (the ``str`` variant feeds text-frame transports such as
  ``aiohttp`` ``send_str``).
"""

from __future__ import annotations

from json import dumps
from typing import Any

# Single-pass translation table: each source char maps to its escaped form in
# one C-level ``str.translate`` call instead of three ``str.replace`` passes
# (three intermediate allocations). Inserted characters are never rescanned,
# so the output is identical to the sequential replace chain.
_LOGURU_ESCAPE_TABLE = str.maketrans({"{": "{{", "}": "}}", "<": "\\<"})


def escape_loguru_markup(s: str) -> str:
    """Escape loguru markup in *s* so it is rendered verbatim.

    Doubles ``{`` / ``}`` so they are not read as format placeholders and
    backslash-escapes ``<`` so it does not open a color tag. ``>`` is harmless
    on its own and is left untouched.
    """
    return s.translate(_LOGURU_ESCAPE_TABLE)


def safe_json_for_log(obj: Any) -> str:
    """Serialize *obj* to JSON and escape loguru markup for safe logging."""
    return escape_loguru_markup(dumps(obj))


def compact_json_str(obj: Any) -> str:
    """Serialize *obj* to the canonical compact JSON wire form, as ``str``.

    ``ensure_ascii=False``, ``allow_nan=False`` and ``separators=(",", ":")``
    are the single canonical wire encoding: every LAN/peer payload must use it
    so peers never diverge on serialization.

    Consumers: ``hsync-client`` (LAN master and slave, text frames over
    ``aiohttp``/``websockets``), shared fixtures/tests. Use
    :func:`compact_json_bytes` for byte-oriented transports.
    """
    return dumps(
        obj,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def compact_json_bytes(obj: Any) -> bytes:
    """Serialize *obj* to the canonical compact UTF-8 JSON wire form.

    Byte-oriented counterpart of :func:`compact_json_str`; one encoding rule,
    two transports.

    Consumers: ``hsync-server`` (streamed listing body), ``hsync-client`` (LAN
    master responses, rendezvous requests), ``hsync-common``
    (``protocol.peer_download._fits_encoded_limit``), shared fixtures/tests.
    """
    return compact_json_str(obj).encode("utf-8")
