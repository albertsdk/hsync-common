# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Bounded literal sink for the delta matcher.

``find_matches_file_to_sink`` / ``find_matches_to_sink`` stream the literal
payload to a sink and derive the data-op offsets from ``tell()``. On the serving
side the payload is parked in a temp file, so the sink is an on-disk writer;
this wrapper bounds how much it writes, because once the payload exceeds
``DELTA_MAX_LITERAL_SIZE`` the delta is refused anyway
(:func:`hsync_common.delta.is_delta_worthwhile`) — continuing to write would only
grow the temp file.

The sink deliberately does **not** raise. ``find_matches_file_to_sink`` runs the
match over an ``mmap`` guarded by a ``with`` block; raising from the sink would
leave the in-flight ``memoryview`` slice referenced by the propagated traceback
and ``mmap.close()`` would fail with ``BufferError``. Instead the sink stops
writing past the cap, keeps counting the true payload size, and flags
:attr:`BoundedLiteralSink.over_limit` for the caller. The emitted data ops stay
complete and correct because the matcher tracks run lengths itself; only the
parked payload is truncated.
"""

from __future__ import annotations

from typing import BinaryIO

from hsync_common.constants import DELTA_MAX_LITERAL_SIZE

__all__ = [
    "BoundedLiteralSink",
]


class BoundedLiteralSink:
    """Write-through literal sink that stops writing past a byte cap.

    Only ``write`` and ``tell`` are used by the matcher. After the match,
    ``total`` holds the true literal size and ``over_limit`` says whether the cap
    was exceeded (in which case the parked payload is truncated and the delta
    must be refused).
    """

    __slots__ = ("_file", "_limit", "over_limit", "total", "written")

    def __init__(self, file_obj: BinaryIO, limit: int = DELTA_MAX_LITERAL_SIZE) -> None:
        self._file = file_obj
        self._limit = limit
        self.over_limit = False
        self.total = 0  # true literal size (never capped)
        self.written = 0  # bytes actually written to the file (capped)

    def write(self, data: bytes) -> int:
        size = len(data)
        self.total += size
        room = self._limit - self.written
        if room <= 0:
            self.over_limit = True
        elif size <= room:
            self._file.write(data)
            self.written += size
        else:
            self._file.write(data[:room])
            self.written = self._limit
            self.over_limit = True
        return size

    def tell(self) -> int:
        return self.total
