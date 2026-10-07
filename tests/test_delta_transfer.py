# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Automated test suite for delta (differential) file transfer on large files.

Validates correct delta transfer for both client-server and LAN peer-to-peer
modes.  Covers initial full transfer, delta-transfer verification with three
modification positions (beginning, middle, end), byte-level accountability, and
topology-specific behaviour.

The suite uses a simulated transport layer that logs every segment exchanged,
enabling direct comparison between transferred deltas and expected changes.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import random
from dataclasses import dataclass, field
from hashlib import sha256

import pytest

from hsync_common.constants import (
    DELTA_BLOCK_SIZE_SMALL,
    DELTA_FILE_SIZE_SMALL,
)
from hsync_common.delta import (
    apply_delta,
    changed_block_ratio,
    compute_signatures,
    find_matches,
    is_delta_worthwhile,
    optimal_block_size,
)
from hsync_common.hashing import compute_sha256
from hsync_common.models.delta import (
    OP_TYPE_COPY,
    OP_TYPE_DATA,
    BlockSignature,
    DeltaOp,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Test-file sizing
# ---------------------------------------------------------------------------
# 512 KB: above DELTA_MIN_FILE_SIZE (256 KB), below DELTA_FILE_SIZE_SMALL (1 MB)
# so optimal_block_size returns DELTA_BLOCK_SIZE_SMALL (4 KB).
# 512 KB / 4 KB = 128 blocks — fast, yet exercises real segmentation.
FILE_SIZE = 512 * 1024
BLOCK_SIZE = DELTA_BLOCK_SIZE_SMALL
NUM_BLOCKS = FILE_SIZE // BLOCK_SIZE

# Edit payload sizes (all multiples of BLOCK_SIZE for clean block alignment).
EDIT_SMALL = 16  # within a single block
EDIT_MEDIUM = BLOCK_SIZE + 16  # spans two blocks
EDIT_LARGE = 2 * BLOCK_SIZE + 32  # spans three blocks


# ---------------------------------------------------------------------------
# Transfer-mode enum
# ---------------------------------------------------------------------------


class TransferMode(enum.Enum):
    """Network topology under which the delta protocol runs."""

    CLIENT_SERVER = "client-server"
    P2P = "p2p"


# ---------------------------------------------------------------------------
# Segment-level tracking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentRecord:
    """One data exchange between two endpoints."""

    msg_type: str  # signature | delta_instructions | literal_data | full_segment
    sender: str
    receiver: str
    byte_count: int
    block_index: int | None = None
    block_offset: int | None = None
    block_length: int | None = None
    op_type: str | None = None  # copy | data


@dataclass
class TransferTracker:
    """Accumulates :class:`SegmentRecord` entries for a single transfer."""

    records: list[SegmentRecord] = field(default_factory=list)

    def record(self, rec: SegmentRecord) -> None:
        self.records.append(rec)

    def total_bytes(self, msg_type: str | None = None) -> int:
        if msg_type is None:
            return sum(r.byte_count for r in self.records)
        return sum(r.byte_count for r in self.records if r.msg_type == msg_type)

    def records_by_type(self, msg_type: str) -> list[SegmentRecord]:
        return [r for r in self.records if r.msg_type == msg_type]

    def single_direction_bytes(self, msg_type: str, exclude_sender: str) -> int:
        """Sum bytes for one leg only (excludes relay-forwarded records)."""
        return sum(
            r.byte_count
            for r in self.records
            if r.msg_type == msg_type and r.sender != exclude_sender
        )

    def summary(self) -> dict[str, int | float]:
        return {
            "total_segments": len(self.records),
            "total_bytes": self.total_bytes(),
            "signature_bytes": self.total_bytes("signature"),
            "instructions_bytes": self.total_bytes("delta_instructions"),
            "literal_bytes": self.total_bytes("literal_data"),
            "full_segment_bytes": self.total_bytes("full_segment"),
        }


# ---------------------------------------------------------------------------
# Simulated transport
# ---------------------------------------------------------------------------


class TrackedTransport:
    """Simulated network channel that records every segment.

    In *CLIENT_SERVER* mode messages are relayed through a central server
    endpoint; in *P2P* mode they travel directly between peers.  The
    delta protocol is identical in both cases — only the routing differs.
    """

    def __init__(self, mode: TransferMode) -> None:
        self.mode = mode
        self.tracker = TransferTracker()
        self._server_endpoint = "server"
        self._peer_a = "peer-a"
        self._peer_b = "peer-b"

    def send(
        self,
        msg_type: str,
        sender: str,
        receiver: str,
        byte_count: int,
        **kwargs: int | str | None,
    ) -> None:
        if self.mode == TransferMode.CLIENT_SERVER:
            self.tracker.record(
                SegmentRecord(
                    msg_type=msg_type,
                    sender=sender,
                    receiver=self._server_endpoint,
                    byte_count=byte_count,
                    **kwargs,  # type: ignore[arg-type]
                )
            )
            self.tracker.record(
                SegmentRecord(
                    msg_type=msg_type,
                    sender=self._server_endpoint,
                    receiver=receiver,
                    byte_count=byte_count,
                    **kwargs,  # type: ignore[arg-type]
                )
            )
        else:
            self.tracker.record(
                SegmentRecord(
                    msg_type=msg_type,
                    sender=sender,
                    receiver=receiver,
                    byte_count=byte_count,
                    **kwargs,  # type: ignore[arg-type]
                )
            )

    def endpoints(self) -> tuple[str, str]:
        if self.mode == TransferMode.CLIENT_SERVER:
            return "client", "server-client"
        return self._peer_a, self._peer_b

    def wire_multiplier(self) -> int:
        """Number of record legs per logical message (2 for relay, 1 for P2P)."""
        return 2 if self.mode == TransferMode.CLIENT_SERVER else 1

    def single_direction_bytes(self, msg_type: str) -> int:
        """Sum bytes for one logical direction (excludes relay duplicates)."""
        return self.tracker.single_direction_bytes(msg_type, self._server_endpoint)


# ---------------------------------------------------------------------------
# Test-data helpers
# ---------------------------------------------------------------------------


def _generate_bytes(size: int, seed: int = 42) -> bytes:
    """Deterministic pseudo-random bytes (seeded Mersenne Twister)."""
    rng = random.Random(seed)
    return bytes(rng.getrandbits(8) for _ in range(size))


def _write_file(path: os.PathLike[str] | str, data: bytes) -> str:
    p = str(path)
    with open(p, "wb") as f:
        f.write(data)
    return p


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Block-index helpers
# ---------------------------------------------------------------------------


def _blocks_for_range(offset: int, length: int, block_size: int) -> set[int]:
    """Return the set of block indices covering ``[offset, offset+length)``."""
    first = offset // block_size
    last = (offset + length - 1) // block_size
    return set(range(first, last + 1))


def _output_blocks_covered_by_ops(
    ops: list[DeltaOp] | tuple[DeltaOp, ...],
    op_type: str,
    block_size: int,
) -> set[int]:
    """Output-file block indices covered by ops of the given type.

    Tracks the cumulative output offset so data ops (whose ``data_offset``
    refers to the literal buffer, not the output file) are mapped correctly.
    """
    covered: set[int] = set()
    out_off = 0
    for op in ops:
        if op.type == op_type:
            first = out_off // block_size
            last = (out_off + op.length - 1) // block_size
            covered.update(range(first, last + 1))
        out_off += op.length
    return covered


# ---------------------------------------------------------------------------
# Protocol simulation
# ---------------------------------------------------------------------------


def run_full_transfer(
    transport: TrackedTransport,
    file_data: bytes,
    output_path: str,
) -> str:
    """Simulate a full (non-delta) segmented transfer.

    The file is split into ``BLOCK_SIZE`` segments, each transmitted and
    logged.  Returns the SHA-256 hex digest of the reassembled file.
    """
    sender, receiver = transport.endpoints()
    file_size = len(file_data)
    segments: list[bytes] = []

    for i in range(0, file_size, BLOCK_SIZE):
        seg = file_data[i : i + BLOCK_SIZE]
        segments.append(seg)
        transport.send(
            "full_segment",
            sender,
            receiver,
            len(seg),
            block_index=i // BLOCK_SIZE,
            block_offset=i,
            block_length=len(seg),
        )

    reassembled = b"".join(segments)
    _write_file(output_path, reassembled)
    return compute_sha256(output_path)


def run_delta_transfer(
    transport: TrackedTransport,
    base_path: str,
    new_data: bytes,
    output_path: str,
) -> tuple[str, list[DeltaOp], bytes, list[BlockSignature]]:
    """Simulate a complete delta-transfer exchange.

    Steps (mirroring the real protocol):
      1. Receiver computes block signatures from the base file.
      2. Receiver sends signatures to the sender.
      3. Sender matches the new file against signatures -> ops + literals.
      4. Sender sends delta instructions (ops metadata) to receiver.
      5. Sender sends the literal payload to receiver.
      6. Receiver applies the delta to reconstruct the file.

    Returns ``(sha256_hex, ops, literal_data, signatures)``.
    """
    sender, receiver = transport.endpoints()

    sigs = compute_signatures(base_path, BLOCK_SIZE)
    # Wire bytes are the actual serialized wire models (BlockSignatureDict /
    # DeltaOpDict as JSON), not hand-made size formulas: the byte accounting
    # below then measures the real protocol payloads.
    sig_bytes = len(json.dumps([s.to_dict() for s in sigs], separators=(",", ":")).encode("utf-8"))
    transport.send("signature", receiver, sender, sig_bytes)

    ops, literal_data = find_matches(new_data, sigs, BLOCK_SIZE)

    instr_bytes = len(
        json.dumps([op.to_dict() for op in ops], separators=(",", ":")).encode("utf-8")
    )
    transport.send("delta_instructions", sender, receiver, instr_bytes)

    if literal_data:
        transport.send("literal_data", sender, receiver, len(literal_data))

    written = apply_delta(base_path, ops, literal_data, output_path)
    assert written == len(new_data)

    return compute_sha256(output_path), ops, literal_data, sigs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=[TransferMode.CLIENT_SERVER, TransferMode.P2P])
def mode(request: pytest.FixtureRequest) -> TransferMode:
    """Parametrized fixture: every test runs in both transfer modes."""
    return request.param


@pytest.fixture
def transport(mode: TransferMode) -> TrackedTransport:
    return TrackedTransport(mode)


@pytest.fixture
def base_data() -> bytes:
    """512 KB of deterministic pseudo-random data."""
    return _generate_bytes(FILE_SIZE, seed=42)


@pytest.fixture
def base_file(tmp_path: pytest.TempPathFactory, base_data: bytes) -> str:
    return _write_file(tmp_path / "base.bin", base_data)  # type: ignore[operator]


# ---------------------------------------------------------------------------
# 1. Initial full transfer
# ---------------------------------------------------------------------------
# The suite's FILE_SIZE (512 KB) sits above DELTA_MIN_FILE_SIZE (256 KB) and
# below DELTA_MIN_FILE_SIZE_P2P (1 MB) on purpose: the base file stays small
# enough to keep the suite fast while still exercising real segmentation.
# The production thresholds are configuration constants owned by their
# consumers; this simulated-transfer suite pins behaviour, not constant values.


class TestFullTransfer:
    """Validate segmented full transfer for files above the delta threshold."""

    def test_full_transfer_integrity(
        self,
        transport: TrackedTransport,
        base_data: bytes,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        out = str(tmp_path / "received.bin")  # type: ignore[operator]
        expected_hash = _sha256_bytes(base_data)
        actual_hash = run_full_transfer(transport, base_data, out)

        assert actual_hash == expected_hash
        with open(out, "rb") as f:
            assert f.read() == base_data

    def test_full_transfer_segmentation(
        self,
        transport: TrackedTransport,
        base_data: bytes,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        out = str(tmp_path / "received.bin")  # type: ignore[operator]
        run_full_transfer(transport, base_data, out)

        segs = transport.tracker.records_by_type("full_segment")
        mult = transport.wire_multiplier()
        assert len(segs) == NUM_BLOCKS * mult

        actual_payload = transport.single_direction_bytes("full_segment")
        assert actual_payload == FILE_SIZE

        unique_indices = sorted({r.block_index for r in segs if r.block_index is not None})
        assert unique_indices == list(range(NUM_BLOCKS))

    def test_full_transfer_logged(
        self,
        transport: TrackedTransport,
        base_data: bytes,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        out = str(tmp_path / "received.bin")  # type: ignore[operator]
        run_full_transfer(transport, base_data, out)

        assert len(transport.tracker.records) > 0
        summary = transport.tracker.summary()
        assert summary["total_bytes"] > 0
        actual_payload = transport.single_direction_bytes("full_segment")
        assert actual_payload == FILE_SIZE
        logger.info("Full transfer summary: %s", summary)


# ---------------------------------------------------------------------------
# 2. Delta-transfer verification
# ---------------------------------------------------------------------------


class TestDeltaTransfer:
    """Three modifications (beginning, middle, end) with delta assertions."""

    def _run_delta(
        self,
        transport: TrackedTransport,
        base_file: str,
        new_data: bytes,
        tmp_path: pytest.TempPathFactory,
        label: str,
    ) -> tuple[str, list[DeltaOp], bytes]:
        out = str(tmp_path / f"out_{label}.bin")  # type: ignore[operator]
        sha, ops, literals, sigs = run_delta_transfer(transport, base_file, new_data, out)
        assert sha == _sha256_bytes(new_data)
        with open(out, "rb") as f:
            assert f.read() == new_data
        return sha, ops, literals

    @pytest.mark.parametrize(
        ("label", "offset", "edit_size", "fill"),
        [
            ("begin", 2 * BLOCK_SIZE, EDIT_SMALL, b"B"),
            ("middle", (FILE_SIZE // 2 // BLOCK_SIZE) * BLOCK_SIZE, EDIT_MEDIUM, b"M"),
            ("end", (NUM_BLOCKS - 4) * BLOCK_SIZE, EDIT_LARGE, b"E"),
        ],
    )
    def test_localized_edit_reuses_unchanged_blocks(
        self,
        transport: TrackedTransport,
        base_data: bytes,
        base_file: str,
        tmp_path: pytest.TempPathFactory,
        label: str,
        offset: int,
        edit_size: int,
        fill: bytes,
    ) -> None:
        new = bytearray(base_data)
        new[offset : offset + edit_size] = fill * edit_size

        _, ops, literals = self._run_delta(transport, base_file, bytes(new), tmp_path, label)

        changed = _blocks_for_range(offset, edit_size, BLOCK_SIZE)
        unchanged = set(range(NUM_BLOCKS)) - changed

        copy_blocks = _output_blocks_covered_by_ops(ops, OP_TYPE_COPY, BLOCK_SIZE)
        data_blocks = _output_blocks_covered_by_ops(ops, OP_TYPE_DATA, BLOCK_SIZE)

        assert copy_blocks & unchanged == unchanged, "All unchanged blocks must be copy ops"
        assert copy_blocks & changed == set(), "Changed blocks must not be copy ops"
        assert data_blocks >= changed, "Changed blocks must be covered by data ops"
        # Rolling checksum emits entire blocks as literal when they don't match
        assert len(literals) == len(changed) * BLOCK_SIZE
        ratio = changed_block_ratio(ops, FILE_SIZE, BLOCK_SIZE)
        assert ratio < 0.05
        assert is_delta_worthwhile(ops, FILE_SIZE, len(literals), BLOCK_SIZE)

    def test_unchanged_segments_not_retransmitted(
        self,
        transport: TrackedTransport,
        base_data: bytes,
        base_file: str,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        new = bytearray(base_data)
        edit_offset = 5 * BLOCK_SIZE
        new[edit_offset : edit_offset + EDIT_SMALL] = b"X" * EDIT_SMALL

        _, ops, _ = self._run_delta(transport, base_file, bytes(new), tmp_path, "no_retransmit")

        changed = _blocks_for_range(edit_offset, EDIT_SMALL, BLOCK_SIZE)
        for op in ops:
            if op.type == OP_TYPE_COPY:
                first = op.offset // BLOCK_SIZE
                last = (op.offset + op.length - 1) // BLOCK_SIZE
                assert set(range(first, last + 1)) & changed == set(), (
                    f"Copy op [{first}..{last}] overlaps changed blocks {changed}"
                )

    def test_three_modifications_sequential(
        self,
        transport: TrackedTransport,
        base_data: bytes,
        base_file: str,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        modifications = [
            ("begin", 2 * BLOCK_SIZE, EDIT_SMALL, b"B"),
            ("middle", (FILE_SIZE // 2 // BLOCK_SIZE) * BLOCK_SIZE, EDIT_MEDIUM, b"M"),
            ("end", (NUM_BLOCKS - 4) * BLOCK_SIZE, EDIT_LARGE, b"E"),
        ]

        current = bytearray(base_data)
        prev_file = base_file
        for label, offset, size, fill in modifications:
            current[offset : offset + size] = fill * size
            out = str(tmp_path / f"out_{label}.bin")  # type: ignore[operator]
            sha, ops, literals, _ = run_delta_transfer(transport, prev_file, bytes(current), out)
            assert sha == _sha256_bytes(bytes(current))
            with open(out, "rb") as f:
                assert f.read() == bytes(current)

            changed = _blocks_for_range(offset, size, BLOCK_SIZE)
            copy_blocks = _output_blocks_covered_by_ops(ops, OP_TYPE_COPY, BLOCK_SIZE)
            assert copy_blocks & changed == set()
            assert len(literals) <= size + BLOCK_SIZE

            prev_file = out


# ---------------------------------------------------------------------------
# 3. Byte-level accountability
# ---------------------------------------------------------------------------


class TestByteLevelAccountability:
    """Network-level counters must match the expected delta sizes."""

    def test_delta_bytes_match_expected_change_size(
        self,
        transport: TrackedTransport,
        base_data: bytes,
        base_file: str,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        new = bytearray(base_data)
        edit_offset = 3 * BLOCK_SIZE
        edit_size = BLOCK_SIZE
        new[edit_offset : edit_offset + edit_size] = b"D" * edit_size

        out = str(tmp_path / "out.bin")  # type: ignore[operator]
        _, ops, literals, _ = run_delta_transfer(transport, base_file, bytes(new), out)

        assert len(literals) == edit_size

        literal_bytes = transport.single_direction_bytes("literal_data")
        instr_bytes = transport.single_direction_bytes("delta_instructions")
        sig_bytes = transport.single_direction_bytes("signature")

        assert literal_bytes == edit_size
        assert instr_bytes > 0
        assert sig_bytes > 0

        total_single = literal_bytes + instr_bytes + sig_bytes
        assert total_single < FILE_SIZE
        logger.info(
            "Delta byte accounting (single-direction): literal=%d, "
            "instructions=%d, signatures=%d, total=%d",
            literal_bytes,
            instr_bytes,
            sig_bytes,
            total_single,
        )

    def test_delta_sends_fewer_bytes_than_full(
        self,
        transport: TrackedTransport,
        base_data: bytes,
        base_file: str,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        new = bytearray(base_data)
        edit_offset = 10 * BLOCK_SIZE
        new[edit_offset : edit_offset + EDIT_SMALL] = b"F" * EDIT_SMALL

        out = str(tmp_path / "out.bin")  # type: ignore[operator]
        run_delta_transfer(transport, base_file, bytes(new), out)

        delta_payload = (
            transport.single_direction_bytes("literal_data")
            + transport.single_direction_bytes("delta_instructions")
            + transport.single_direction_bytes("signature")
        )
        assert delta_payload < FILE_SIZE // 2

    def test_literal_payload_size_bounded(
        self,
        transport: TrackedTransport,
        base_data: bytes,
        base_file: str,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        new = bytearray(base_data)
        edit_offset = 7 * BLOCK_SIZE
        edit_size = 2 * BLOCK_SIZE
        new[edit_offset : edit_offset + edit_size] = b"G" * edit_size

        out = str(tmp_path / "out.bin")  # type: ignore[operator]
        _, ops, literals, _ = run_delta_transfer(transport, base_file, bytes(new), out)

        assert len(literals) == edit_size
        assert len(literals) < FILE_SIZE // 10

    def test_protocol_overhead_measurable(
        self,
        transport: TrackedTransport,
        base_data: bytes,
        base_file: str,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        new = bytearray(base_data)
        edit_offset = 4 * BLOCK_SIZE
        new[edit_offset : edit_offset + EDIT_SMALL] = b"H" * EDIT_SMALL

        out = str(tmp_path / "out.bin")  # type: ignore[operator]
        run_delta_transfer(transport, base_file, bytes(new), out)

        overhead = transport.single_direction_bytes("signature") + transport.single_direction_bytes(
            "delta_instructions"
        )
        literal = transport.single_direction_bytes("literal_data")
        assert overhead > 0
        assert overhead < FILE_SIZE // 4
        assert literal > 0

    def test_segment_log_enables_direct_comparison(
        self,
        transport: TrackedTransport,
        base_data: bytes,
        base_file: str,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        new = bytearray(base_data)
        edit_offset = 6 * BLOCK_SIZE
        edit_size = BLOCK_SIZE
        new[edit_offset : edit_offset + edit_size] = b"I" * edit_size
        changed = _blocks_for_range(edit_offset, edit_size, BLOCK_SIZE)

        out = str(tmp_path / "out.bin")  # type: ignore[operator]
        _, ops, literals, _ = run_delta_transfer(transport, base_file, bytes(new), out)

        sig_recs = transport.tracker.records_by_type("signature")
        instr_recs = transport.tracker.records_by_type("delta_instructions")
        lit_recs = transport.tracker.records_by_type("literal_data")

        assert len(sig_recs) > 0
        assert len(instr_recs) > 0
        assert len(lit_recs) > 0

        literal_bytes = transport.single_direction_bytes("literal_data")
        assert literal_bytes == edit_size

        data_ops = [op for op in ops if op.type == OP_TYPE_DATA]
        copy_ops = [op for op in ops if op.type == OP_TYPE_COPY]

        data_total = sum(op.length for op in data_ops)
        copy_total = sum(op.length for op in copy_ops)

        assert data_total == len(literals)
        assert copy_total + data_total == FILE_SIZE

        data_blocks = _output_blocks_covered_by_ops(ops, OP_TYPE_DATA, BLOCK_SIZE)
        assert data_blocks >= changed

        for rec in transport.tracker.records:
            logger.debug(
                "[%s] %s -> %s: %d bytes (type=%s, block=%s)",
                transport.mode.value,
                rec.sender,
                rec.receiver,
                rec.byte_count,
                rec.msg_type,
                rec.block_index,
            )


# ---------------------------------------------------------------------------
# 4. Mode-specific behaviour
# ---------------------------------------------------------------------------


class TestModeSpecific:
    """Topology differences between client-server and p2p."""

    def test_client_server_has_double_segments(
        self, base_data: bytes, base_file: str, tmp_path: pytest.TempPathFactory
    ) -> None:
        new = bytearray(base_data)
        edit_offset = 8 * BLOCK_SIZE
        new[edit_offset : edit_offset + EDIT_SMALL] = b"J" * EDIT_SMALL

        cs = TrackedTransport(TransferMode.CLIENT_SERVER)
        out_cs = str(tmp_path / "out_cs.bin")  # type: ignore[operator]
        run_delta_transfer(cs, base_file, bytes(new), out_cs)

        p2p = TrackedTransport(TransferMode.P2P)
        out_p2p = str(tmp_path / "out_p2p.bin")  # type: ignore[operator]
        run_delta_transfer(p2p, base_file, bytes(new), out_p2p)

        cs_count = len(cs.tracker.records)
        p2p_count = len(p2p.tracker.records)
        assert cs_count == p2p_count * 2

    def test_both_modes_produce_identical_delta(
        self, base_data: bytes, base_file: str, tmp_path: pytest.TempPathFactory
    ) -> None:
        new = bytearray(base_data)
        edit_offset = 9 * BLOCK_SIZE
        new[edit_offset : edit_offset + EDIT_SMALL] = b"K" * EDIT_SMALL

        cs = TrackedTransport(TransferMode.CLIENT_SERVER)
        out_cs = str(tmp_path / "out_cs.bin")  # type: ignore[operator]
        _, ops_cs, lit_cs, _ = run_delta_transfer(cs, base_file, bytes(new), out_cs)

        p2p = TrackedTransport(TransferMode.P2P)
        out_p2p = str(tmp_path / "out_p2p.bin")  # type: ignore[operator]
        _, ops_p2p, lit_p2p, _ = run_delta_transfer(p2p, base_file, bytes(new), out_p2p)

        assert ops_cs == ops_p2p
        assert lit_cs == lit_p2p

    def test_both_modes_reconstruct_identical_file(
        self, base_data: bytes, base_file: str, tmp_path: pytest.TempPathFactory
    ) -> None:
        new = bytearray(base_data)
        edit_offset = 11 * BLOCK_SIZE
        new[edit_offset : edit_offset + EDIT_MEDIUM] = b"L" * EDIT_MEDIUM

        cs = TrackedTransport(TransferMode.CLIENT_SERVER)
        out_cs = str(tmp_path / "out_cs.bin")  # type: ignore[operator]
        sha_cs, _, _, _ = run_delta_transfer(cs, base_file, bytes(new), out_cs)

        p2p = TrackedTransport(TransferMode.P2P)
        out_p2p = str(tmp_path / "out_p2p.bin")  # type: ignore[operator]
        sha_p2p, _, _, _ = run_delta_transfer(p2p, base_file, bytes(new), out_p2p)

        assert sha_cs == sha_p2p == _sha256_bytes(bytes(new))

    def test_client_server_routes_through_server(
        self, base_data: bytes, base_file: str, tmp_path: pytest.TempPathFactory
    ) -> None:
        new = bytearray(base_data)
        edit_offset = 12 * BLOCK_SIZE
        new[edit_offset : edit_offset + EDIT_SMALL] = b"N" * EDIT_SMALL

        transport = TrackedTransport(TransferMode.CLIENT_SERVER)
        out = str(tmp_path / "out.bin")  # type: ignore[operator]
        run_delta_transfer(transport, base_file, bytes(new), out)

        for rec in transport.tracker.records:
            assert rec.sender == "server" or rec.receiver == "server"

    def test_p2p_direct_between_peers(
        self, base_data: bytes, base_file: str, tmp_path: pytest.TempPathFactory
    ) -> None:
        new = bytearray(base_data)
        edit_offset = 13 * BLOCK_SIZE
        new[edit_offset : edit_offset + EDIT_SMALL] = b"O" * EDIT_SMALL

        transport = TrackedTransport(TransferMode.P2P)
        out = str(tmp_path / "out.bin")  # type: ignore[operator]
        run_delta_transfer(transport, base_file, bytes(new), out)

        for rec in transport.tracker.records:
            assert rec.sender in ("peer-a", "peer-b")
            assert rec.receiver in ("peer-a", "peer-b")
            assert rec.sender != rec.receiver

    def test_block_size_adaptive(
        self, base_data: bytes, base_file: str, tmp_path: pytest.TempPathFactory
    ) -> None:
        assert optimal_block_size(FILE_SIZE) == DELTA_BLOCK_SIZE_SMALL
        assert optimal_block_size(DELTA_FILE_SIZE_SMALL) > DELTA_BLOCK_SIZE_SMALL

    def test_delta_worthwhile_for_small_changes(
        self, base_data: bytes, base_file: str, tmp_path: pytest.TempPathFactory
    ) -> None:
        new = bytearray(base_data)
        edit_offset = 14 * BLOCK_SIZE
        new[edit_offset : edit_offset + EDIT_SMALL] = b"P" * EDIT_SMALL

        transport = TrackedTransport(TransferMode.P2P)
        out = str(tmp_path / "out.bin")  # type: ignore[operator]
        _, ops, literals, _ = run_delta_transfer(transport, base_file, bytes(new), out)

        assert is_delta_worthwhile(ops, FILE_SIZE, len(literals), BLOCK_SIZE)
        ratio = changed_block_ratio(ops, FILE_SIZE, BLOCK_SIZE)
        assert ratio < 0.05

    def test_multiple_sequential_deltas(
        self, base_data: bytes, base_file: str, tmp_path: pytest.TempPathFactory
    ) -> None:
        current = bytearray(base_data)
        prev_file = base_file

        for i in range(5):
            edit_offset = (20 + i * 10) * BLOCK_SIZE
            edit_size = BLOCK_SIZE
            current[edit_offset : edit_offset + edit_size] = bytes([i + 0x41]) * edit_size

            transport = TrackedTransport(TransferMode.P2P)
            out = str(tmp_path / f"out_{i}.bin")  # type: ignore[operator]
            sha, ops, literals, _ = run_delta_transfer(transport, prev_file, bytes(current), out)

            assert sha == _sha256_bytes(bytes(current))
            assert len(literals) == edit_size
            assert is_delta_worthwhile(ops, FILE_SIZE, len(literals), BLOCK_SIZE)

            prev_file = out
