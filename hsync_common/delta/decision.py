# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Delta-transfer worthwhileness decisions (block size, abort thresholds).

Pure functions shared by every component: no I/O, no peer state. The
direction-aware ``should_use_delta`` gate lives in the client (it needs
``.hsyncstate`` and peer capabilities) and reuses these helpers for the
size/change-ratio part of the decision.
"""

from __future__ import annotations

from hsync_common.constants import (
    DELTA_BLOCK_SIZE_LARGE,
    DELTA_BLOCK_SIZE_MEDIUM,
    DELTA_BLOCK_SIZE_SMALL,
    DELTA_BLOCK_SIZE_XLARGE,
    DELTA_FILE_SIZE_LARGE,
    DELTA_FILE_SIZE_MEDIUM,
    DELTA_FILE_SIZE_SMALL,
    DELTA_MAX_CHANGE_RATIO,
    DELTA_MAX_LITERAL_SIZE,
)
from hsync_common.models.delta import OP_TYPE_COPY, DeltaOp

__all__ = [
    "changed_block_ratio",
    "is_delta_worthwhile",
    "optimal_block_size",
]


def optimal_block_size(file_size: int) -> int:
    """Pick the adaptive block size for a base file of *file_size* bytes.

    Both peers must derive the same value from the same base file size —
    signatures computed with mismatched block sizes are incompatible.
    """
    if file_size < DELTA_FILE_SIZE_SMALL:
        return DELTA_BLOCK_SIZE_SMALL
    if file_size < DELTA_FILE_SIZE_MEDIUM:
        return DELTA_BLOCK_SIZE_MEDIUM
    if file_size < DELTA_FILE_SIZE_LARGE:
        return DELTA_BLOCK_SIZE_LARGE
    return DELTA_BLOCK_SIZE_XLARGE


def changed_block_ratio(
    ops: list[DeltaOp] | tuple[DeltaOp, ...],
    base_size: int,
    block_size: int,
) -> float:
    """Fraction of base blocks *not* reused by copy ops (0.0 = identical).

    A base block is "reused" when at least one copy op references its byte
    range; everything else counts as changed. Returns 1.0 for an empty base
    (nothing reusable) or invalid inputs.
    """
    if base_size <= 0 or block_size <= 0:
        return 1.0
    total_blocks = (base_size + block_size - 1) // block_size
    if total_blocks == 0:
        return 1.0
    reused: set[int] = set()
    for op in ops:
        if op.type != OP_TYPE_COPY:
            continue
        first = op.offset // block_size
        last = (op.offset + op.length - 1) // block_size
        reused.update(range(first, last + 1))
    matched = min(len(reused), total_blocks)
    return 1.0 - (matched / total_blocks)


def is_delta_worthwhile(
    ops: list[DeltaOp] | tuple[DeltaOp, ...],
    base_size: int,
    literal_size: int,
    block_size: int,
    *,
    max_change_ratio: float = DELTA_MAX_CHANGE_RATIO,
    max_literal_size: int = DELTA_MAX_LITERAL_SIZE,
) -> bool:
    """Decide whether a computed delta beats a full transfer.

    Aborts (returns False) when the literal payload exceeds the hard cap or
    when more than ``max_change_ratio`` of the base blocks changed — in both
    cases a full transfer is cheaper than the delta overhead.
    """
    if literal_size > max_literal_size:
        return False
    return changed_block_ratio(ops, base_size, block_size) <= max_change_ratio
