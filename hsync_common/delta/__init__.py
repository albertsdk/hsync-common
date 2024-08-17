# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Delta-transfer (rsync-style) core shared by every HSYNC component.

Pure algorithm + decision logic only: no HTTP, no sync-state, no peer
handling — those live in the framework-specific layers (FastAPI server,
stdlib LAN server, client transfer engine) which delegate here.
"""

from hsync_common.delta.decision import (
    changed_block_ratio,
    is_delta_worthwhile,
    optimal_block_size,
)
from hsync_common.delta.rolling_checksum import (
    ADLER32_MOD,
    APPLY_BUFFER_SIZE,
    DeltaError,
    adler32_roll,
    apply_delta,
    build_signature_index,
    compute_signatures,
    find_matches,
    find_matches_file,
)

__all__ = [
    "ADLER32_MOD",
    "APPLY_BUFFER_SIZE",
    "DeltaError",
    "adler32_roll",
    "apply_delta",
    "build_signature_index",
    "changed_block_ratio",
    "compute_signatures",
    "find_matches",
    "find_matches_file",
    "is_delta_worthwhile",
    "optimal_block_size",
]
