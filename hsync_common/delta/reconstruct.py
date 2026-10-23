# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Verified delta reconstruction, shared by every delta receiver.

:func:`hsync_common.delta.apply_delta` only rebuilds bytes. A receiver must also
prove that the rebuild actually reproduces the content the sender announced
(``new_sha256``/``new_size``): a corrupted or hostile op list that stays within
the declared bounds would otherwise publish a silently wrong file. That
invariant used to be re-implemented by the server, the LAN master and the client
download path, so a change to it had to be applied three times.

This module owns the single implementation. Callers keep their own transport
concerns (temp-file naming, cleanup, HTTP status mapping) and translate
:class:`ReconstructionMismatch` into their own error surface.

Consumers: ``hsync-server`` (``api/files/delta/apply.py``), ``hsync-client``
(``p2p_delta.py`` LAN master, ``delta_transfer.py`` download path), shared
tests/fixtures.
"""

from __future__ import annotations

import os
from typing import BinaryIO

from hsync_common.delta.rolling_checksum import DeltaError, apply_delta
from hsync_common.hashing import compute_sha256
from hsync_common.models.delta import DeltaOp

__all__ = [
    "MISMATCH_HASH",
    "MISMATCH_SIZE",
    "ReconstructionMismatch",
    "reconstruct_and_verify",
]

# ``ReconstructionMismatch.details["reason"]`` values. They are part of the
# delta-apply contract (the server echoes them to the peer), so they are shared
# constants instead of three string literals.
MISMATCH_HASH = "reconstructed_file_hash_mismatch"
MISMATCH_SIZE = "reconstructed_file_size_mismatch"


class ReconstructionMismatch(DeltaError):
    """The rebuilt file does not match the content the sender announced.

    ``details["reason"]`` is :data:`MISMATCH_HASH` or :data:`MISMATCH_SIZE`; the
    hash case also carries ``expected_sha256``/``actual_sha256`` so a receiver
    can log both without re-hashing.

    Consumers: ``hsync-server`` ``delta/apply.py`` (HTTP 422 detail),
    ``hsync-client`` ``p2p_delta.py`` (HTTP 422 detail) and ``delta_transfer.py``
    (``DeltaTransferError`` message), shared tests.
    """

    error_code = "HSYNC-DELTA-0002"
    default_message = "Delta reconstruction produced unexpected content"


def reconstruct_and_verify(
    base_path: str,
    ops: list[DeltaOp] | tuple[DeltaOp, ...],
    literal_data: bytes | bytearray | memoryview | BinaryIO,
    output_path: str,
    *,
    expected_sha256: str,
    expected_size: int,
) -> str:
    """Rebuild *output_path* from *base_path* and verify content and size.

    Writes the rebuild to *output_path* (a ``*.part`` sibling chosen by the
    caller — never the base path), then re-reads it once to compare its SHA-256
    with *expected_sha256* and its size with *expected_size*.

    Args:
        base_path: Current file on disk the copy ops read from.
        ops: Copy/data operations validated by
            :func:`hsync_common.delta.validate_op_bounds`.
        literal_data: Literal payload, in memory or a seekable stream.
        output_path: Rebuild destination; the caller renames it over
            *base_path* once this returns.
        expected_sha256: SHA-256 announced by the sender.
        expected_size: Expected size of the rebuilt file.

    Returns:
        The rebuilt file's SHA-256 (equal to *expected_sha256*).

    Raises:
        ReconstructionMismatch: When the digest or the size differs. The
            partial output is left in place: the caller owns its cleanup.
        DeltaError: When the op list cannot be applied at all.
    """
    apply_delta(base_path, ops, literal_data, output_path)
    rebuilt_sha256 = compute_sha256(output_path)
    if rebuilt_sha256 != expected_sha256:
        raise ReconstructionMismatch(
            details={
                "reason": MISMATCH_HASH,
                "expected_sha256": expected_sha256,
                "actual_sha256": rebuilt_sha256,
            }
        )
    size = os.stat(output_path).st_size
    if size != expected_size:
        raise ReconstructionMismatch(
            details={
                "reason": MISMATCH_SIZE,
                "expected_size": expected_size,
                "actual_size": size,
            }
        )
    return rebuilt_sha256
