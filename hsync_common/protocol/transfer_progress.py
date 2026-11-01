# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Delivery-progress frame of the p2p control plane.

An upload's progress belongs to the **receiver**: the sender hands bytes to its
transport (the socket, TLS, a relay's buffers), which says nothing about what the
peer holds. The master therefore publishes the bytes it actually received for a
file a peer is pushing — unicast on that peer's WebSocket session, as the
``masterToSlave`` ``file_progress`` frame — and the uploading side renders them
instead of its own transport counter.

Consumers: ``hsync-client`` (the master's receive path and the uploading slave's
event loop), the Android protocol mirror, the generated JSON Schema and golden
fixtures, and the shared protocol contract tests.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from hsync_common.path_validation import validate_remote_relpath
from hsync_common.protocol.peer_download import P2P_WIRE_INT_MAX

__all__ = [
    "P2P_FILE_PROGRESS_TYPE",
    "P2PFileProgressFrame",
    "build_p2p_file_progress",
    "validate_p2p_file_progress",
]

# Frame discriminator on the master⇄slave WebSocket control plane.
P2P_FILE_PROGRESS_TYPE = "file_progress"

_FILE_PROGRESS_KEYS = frozenset({"type", "file", "transferred", "total"})


class P2PFileProgressFrame(TypedDict):
    """Bytes the master has received for a file a peer is uploading.

    ``total`` is the *wire* total the sender declared, or ``0`` when the receiver
    cannot know it (a streamed body carries no per-part length): the sender keeps
    its own total then.
    """

    type: Literal["file_progress"]
    file: str
    transferred: int
    total: int


def _is_byte_count(value: object) -> bool:
    """True for a non-negative wire integer (never a bool or a float)."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= P2P_WIRE_INT_MAX


def validate_p2p_file_progress(value: object) -> P2PFileProgressFrame | None:
    """Strictly validate a ``file_progress`` frame, or return ``None``.

    ``file`` is a bucket-relative path (the uploader's own key), validated like
    any other peer-supplied path; the byte counts are non-negative wire
    integers, and a known ``total`` must bound ``transferred``.
    """
    if not isinstance(value, dict) or set(value) != _FILE_PROGRESS_KEYS:
        return None
    if value.get("type") != P2P_FILE_PROGRESS_TYPE:
        return None
    raw_file = value.get("file")
    if not isinstance(raw_file, str):
        return None
    file = validate_remote_relpath(raw_file)
    if file is None:
        return None
    transferred = value.get("transferred")
    total = value.get("total")
    if not _is_byte_count(transferred) or not _is_byte_count(total):
        return None
    if total and transferred > total:
        return None
    return P2PFileProgressFrame(
        type=P2P_FILE_PROGRESS_TYPE, file=file, transferred=transferred, total=total
    )


def build_p2p_file_progress(*, file: str, transferred: int, total: int = 0) -> P2PFileProgressFrame:
    """Build a canonical ``file_progress`` frame or raise ``ValueError``."""
    frame = validate_p2p_file_progress(
        {"type": P2P_FILE_PROGRESS_TYPE, "file": file, "transferred": transferred, "total": total}
    )
    if frame is None:
        raise ValueError("invalid p2p file progress frame")
    return frame
