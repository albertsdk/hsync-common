# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

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
from hsync_common.delta.literals import (
    BoundedLiteralSink,
)
from hsync_common.delta.reconstruct import (
    MISMATCH_HASH,
    MISMATCH_SIZE,
    ReconstructionMismatch,
    reconstruct_and_verify,
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
    find_matches_file_to_sink,
    find_matches_to_sink,
    signatures_for_data,
)
from hsync_common.delta.token_store import (
    DeltaTokenEntry,
    DeltaTokenStore,
    TokenStoreFull,
    TokenStoreStorageFull,
)

__all__ = [
    "ADLER32_MOD",
    "APPLY_BUFFER_SIZE",
    "BoundedLiteralSink",
    "DeltaError",
    "DeltaTokenEntry",
    "DeltaTokenStore",
    "MISMATCH_HASH",
    "MISMATCH_SIZE",
    "ReconstructionMismatch",
    "TokenStoreFull",
    "TokenStoreStorageFull",
    "adler32_roll",
    "apply_delta",
    "build_signature_index",
    "changed_block_ratio",
    "compute_signatures",
    "find_matches",
    "find_matches_file",
    "find_matches_file_to_sink",
    "find_matches_to_sink",
    "is_delta_worthwhile",
    "optimal_block_size",
    "reconstruct_and_verify",
    "signatures_for_data",
]
