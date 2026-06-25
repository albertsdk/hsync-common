# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Unit tests for the delta-transfer core (rolling checksum, matching, apply)."""

from __future__ import annotations

import os
import random
import zlib
from hashlib import sha256

import pytest

from hsync_common.constants import (
    DELTA_BLOCK_SIZE_LARGE,
    DELTA_BLOCK_SIZE_MEDIUM,
    DELTA_BLOCK_SIZE_SMALL,
    DELTA_BLOCK_SIZE_XLARGE,
)
from hsync_common.delta import (
    DeltaError,
    adler32_roll,
    apply_delta,
    build_signature_index,
    changed_block_ratio,
    compute_signatures,
    find_matches,
    find_matches_file,
    is_delta_worthwhile,
    optimal_block_size,
)
from hsync_common.models.delta import (
    OP_TYPE_COPY,
    OP_TYPE_DATA,
    BlockSignature,
    DeltaOp,
    sanitize_delta_op,
    sanitize_signature_list,
)

BLOCK = 64  # small block size keeps the fixtures fast and readable


def _write(path, data: bytes) -> str:
    path.write_bytes(data)
    return str(path)


def _base_bytes(seed: int = 42, size: int = BLOCK * 10) -> bytes:
    rng = random.Random(seed)
    return bytes(rng.randrange(256) for _ in range(size))


# ---------------------------------------------------------------------------
# Rolling Adler32
# ---------------------------------------------------------------------------


class TestAdler32Roll:
    def test_matches_zlib_on_every_shift(self):
        """Rolling checksum must equal fresh zlib.adler32 at every position."""
        data = _base_bytes(size=BLOCK * 5)
        first = zlib.adler32(data[:BLOCK])
        a, b = first & 0xFFFF, (first >> 16) & 0xFFFF
        for pos in range(1, len(data) - BLOCK + 1):
            weak, a, b = adler32_roll(a, b, BLOCK, data[pos - 1], data[pos + BLOCK - 1])
            assert weak == zlib.adler32(data[pos : pos + BLOCK]), f"drift at pos {pos}"

    def test_single_byte_window(self):
        data = bytes(range(256))
        first = zlib.adler32(data[:1])
        a, b = first & 0xFFFF, (first >> 16) & 0xFFFF
        for pos in range(1, len(data)):
            weak, a, b = adler32_roll(a, b, 1, data[pos - 1], data[pos])
            assert weak == zlib.adler32(data[pos : pos + 1])

    def test_mod_wraparound(self):
        """Windows full of 0xFF force the modular arithmetic to wrap."""
        data = b"\xff" * (BLOCK * 3)
        first = zlib.adler32(data[:BLOCK])
        a, b = first & 0xFFFF, (first >> 16) & 0xFFFF
        for pos in range(1, len(data) - BLOCK + 1):
            weak, a, b = adler32_roll(a, b, BLOCK, data[pos - 1], data[pos + BLOCK - 1])
            assert weak == zlib.adler32(data[pos : pos + BLOCK])


# ---------------------------------------------------------------------------
# compute_signatures
# ---------------------------------------------------------------------------


class TestComputeSignatures:
    def test_full_blocks_plus_partial_tail(self, tmp_path):
        data = _base_bytes(size=BLOCK * 4 + 17)  # 4 full blocks + 17-byte tail
        path = _write(tmp_path / "base.bin", data)
        sigs = compute_signatures(path, BLOCK)
        assert len(sigs) == 5
        for i, sig in enumerate(sigs[:-1]):
            assert sig.index == i
            assert sig.offset == i * BLOCK
            assert sig.length == BLOCK
            assert sig.weak == zlib.adler32(data[i * BLOCK : (i + 1) * BLOCK])
            assert sig.strong == sha256(data[i * BLOCK : (i + 1) * BLOCK]).hexdigest()
        tail = sigs[-1]
        assert tail.length == 17
        assert tail.offset == BLOCK * 4
        assert tail.strong == sha256(data[BLOCK * 4 :]).hexdigest()

    def test_exact_multiple_has_no_partial_tail(self, tmp_path):
        path = _write(tmp_path / "base.bin", _base_bytes(size=BLOCK * 3))
        sigs = compute_signatures(path, BLOCK)
        assert len(sigs) == 3
        assert all(s.length == BLOCK for s in sigs)

    def test_empty_file_yields_no_signatures(self, tmp_path):
        path = _write(tmp_path / "empty.bin", b"")
        assert compute_signatures(path, BLOCK) == []

    def test_invalid_block_size_rejected(self, tmp_path):
        path = _write(tmp_path / "base.bin", b"abc")
        with pytest.raises(DeltaError):
            compute_signatures(path, 0)

    def test_tail_excluded_from_match_index(self, tmp_path):
        data = _base_bytes(size=BLOCK + 10)
        path = _write(tmp_path / "base.bin", data)
        sigs = compute_signatures(path, BLOCK)
        table = build_signature_index(sigs, BLOCK)
        assert len(sigs) == 2  # 1 full + 1 tail
        assert sum(len(v) for v in table.values()) == 1  # only the full block


# ---------------------------------------------------------------------------
# find_matches
# ---------------------------------------------------------------------------


def _sigs_for(tmp_path, data: bytes, block_size: int = BLOCK) -> list[BlockSignature]:
    return compute_signatures(_write(tmp_path / "base.bin", data), block_size)


class TestFindMatches:
    def test_identical_file_is_all_copy(self, tmp_path):
        base = _base_bytes(size=BLOCK * 6)
        sigs = _sigs_for(tmp_path, base)
        ops, literals = find_matches(base, sigs, BLOCK)
        assert literals == b""
        assert all(op.type == OP_TYPE_COPY for op in ops)
        assert [(op.offset, op.length) for op in ops] == [(i * BLOCK, BLOCK) for i in range(6)]

    def test_completely_different_file_is_all_data(self, tmp_path):
        base = _base_bytes(seed=1, size=BLOCK * 4)
        new = _base_bytes(seed=999, size=BLOCK * 4)
        sigs = _sigs_for(tmp_path, base)
        ops, literals = find_matches(new, sigs, BLOCK)
        assert all(op.type == OP_TYPE_DATA for op in ops)
        assert literals == new
        # consecutive literal bytes coalesce into a single data op
        assert len(ops) == 1
        assert ops[0].length == len(new)
        assert ops[0].data_offset == 0

    def test_localized_change_produces_mix(self, tmp_path):
        base = bytearray(_base_bytes(size=BLOCK * 8))
        new = bytearray(base)
        new[2 * BLOCK : 2 * BLOCK + 10] = b"X" * 10  # 10 bytes inside block 2
        sigs = _sigs_for(tmp_path, bytes(base))
        ops, literals = find_matches(bytes(new), sigs, BLOCK)
        types = {op.type for op in ops}
        assert types == {OP_TYPE_COPY, OP_TYPE_DATA}
        copied = sum(op.length for op in ops if op.type == OP_TYPE_COPY)
        assert copied >= 6 * BLOCK  # untouched blocks reused
        assert literals  # the changed bytes travel literally

    def test_insertion_at_head_shifts_and_recovers(self, tmp_path):
        base = _base_bytes(size=BLOCK * 5)
        new = b"INSERTED!" + base  # 9 extra bytes shift everything
        sigs = _sigs_for(tmp_path, base)
        ops, literals = find_matches(new, sigs, BLOCK)
        reconstructed = bytearray()
        for op in ops:
            if op.type == OP_TYPE_COPY:
                reconstructed += base[op.offset : op.offset + op.length]
            else:
                reconstructed += literals[op.data_offset : op.data_offset + op.length]
        assert bytes(reconstructed) == new
        copy_bytes = sum(op.length for op in ops if op.type == OP_TYPE_COPY)
        assert copy_bytes >= 4 * BLOCK  # rolling window resyncs after insertion

    def test_append_at_tail(self, tmp_path):
        base = _base_bytes(size=BLOCK * 3)
        new = base + b"tail-bytes"
        sigs = _sigs_for(tmp_path, base)
        ops, literals = find_matches(new, sigs, BLOCK)
        assert ops[-1].type == OP_TYPE_DATA
        assert literals == b"tail-bytes"

    def test_partial_tail_in_new_file_is_literal(self, tmp_path):
        """A new file whose tail is < block_size emits those bytes as data."""
        base = _base_bytes(size=BLOCK * 4)
        new = base[: BLOCK * 2] + base[BLOCK * 2 : BLOCK * 2 + BLOCK // 2]
        sigs = _sigs_for(tmp_path, base)
        ops, literals = find_matches(new, sigs, BLOCK)
        assert ops[-1].type == OP_TYPE_DATA
        assert ops[-1].length == BLOCK // 2

    def test_new_file_shorter_than_block_is_single_data_op(self, tmp_path):
        base = _base_bytes(size=BLOCK * 3)
        sigs = _sigs_for(tmp_path, base)
        ops, literals = find_matches(b"tiny", sigs, BLOCK)
        assert ops == [DeltaOp.data(0, 4)]
        assert literals == b"tiny"

    def test_literal_offsets_reference_literal_buffer(self, tmp_path):
        base = _base_bytes(size=BLOCK * 4)
        new = b"AA" + base[:BLOCK] + b"BB" + base[BLOCK : 2 * BLOCK]
        sigs = _sigs_for(tmp_path, base)
        ops, literals = find_matches(new, sigs, BLOCK)
        data_ops = [op for op in ops if op.type == OP_TYPE_DATA]
        assert literals == b"AABB"
        for op in data_ops:
            assert literals[op.data_offset : op.data_offset + op.length]


# ---------------------------------------------------------------------------
# apply_delta round-trips
# ---------------------------------------------------------------------------


class TestApplyDelta:
    def _roundtrip(self, tmp_path, base: bytes, new: bytes, block_size: int = BLOCK):
        base_path = _write(tmp_path / "base.bin", base)
        out_path = str(tmp_path / "out.bin")
        sigs = compute_signatures(base_path, block_size)
        ops, literals = find_matches(new, sigs, block_size)
        written = apply_delta(base_path, ops, literals, out_path)
        assert written == len(new)
        assert open(out_path, "rb").read() == new  # noqa: SIM115
        assert sha256(open(out_path, "rb").read()).hexdigest() == sha256(new).hexdigest()  # noqa: SIM115

    def test_roundtrip_identical(self, tmp_path):
        data = _base_bytes(size=BLOCK * 7)
        self._roundtrip(tmp_path, data, data)

    def test_roundtrip_scattered_edits(self, tmp_path):
        base = bytearray(_base_bytes(size=BLOCK * 10))
        new = bytearray(base)
        new[5] ^= 0xFF
        new[3 * BLOCK + 20 : 3 * BLOCK + 40] = b"Z" * 20
        del new[8 * BLOCK : 8 * BLOCK + 30]  # deletion
        self._roundtrip(tmp_path, bytes(base), bytes(new))

    def test_roundtrip_with_growth_and_shrink(self, tmp_path):
        base = _base_bytes(size=BLOCK * 6)
        self._roundtrip(tmp_path, base, base + b"extra" * 100)
        self._roundtrip(tmp_path, base, base[: BLOCK * 2 + 7])

    def test_apply_from_literal_stream(self, tmp_path):
        """literal_data may be a seekable stream, not only bytes."""
        base = _base_bytes(size=BLOCK * 4)
        new = b"hdr" + base
        base_path = _write(tmp_path / "base.bin", base)
        sigs = compute_signatures(base_path, BLOCK)
        ops, literals = find_matches(new, sigs, BLOCK)
        lit_path = _write(tmp_path / "lit.bin", literals)
        out_path = str(tmp_path / "out.bin")
        with open(lit_path, "rb") as stream:
            apply_delta(base_path, ops, stream, out_path)
        assert open(out_path, "rb").read() == new  # noqa: SIM115

    def test_copy_past_base_end_raises(self, tmp_path):
        base_path = _write(tmp_path / "base.bin", b"short")
        with pytest.raises(DeltaError):
            apply_delta(base_path, [DeltaOp.copy(4, 10)], b"", str(tmp_path / "out.bin"))

    def test_data_past_literal_end_raises(self, tmp_path):
        base_path = _write(tmp_path / "base.bin", b"short")
        with pytest.raises(DeltaError):
            apply_delta(base_path, [DeltaOp.data(3, 10)], b"abc", str(tmp_path / "out.bin"))


# ---------------------------------------------------------------------------
# find_matches_file (mmap-backed)
# ---------------------------------------------------------------------------


class TestFindMatchesFile:
    def test_matches_in_memory_result(self, tmp_path):
        base = _base_bytes(size=BLOCK * 6)
        new = b"XX" + base[: 3 * BLOCK] + b"YY" + base[3 * BLOCK :]
        sigs = _sigs_for(tmp_path, base)
        new_path = _write(tmp_path / "new.bin", new)
        ops_file, lit_file = find_matches_file(new_path, sigs, BLOCK)
        ops_mem, lit_mem = find_matches(new, sigs, BLOCK)
        assert ops_file == ops_mem
        assert lit_file == lit_mem

    def test_empty_file(self, tmp_path):
        base = _base_bytes(size=BLOCK * 2)
        sigs = _sigs_for(tmp_path, base)
        new_path = _write(tmp_path / "new.bin", b"")
        ops, literals = find_matches_file(new_path, sigs, BLOCK)
        assert ops == []
        assert literals == b""


# ---------------------------------------------------------------------------
# decision helpers
# ---------------------------------------------------------------------------


class TestDecision:
    @pytest.mark.parametrize(
        ("size", "expected"),
        [
            (100, DELTA_BLOCK_SIZE_SMALL),
            (1024 * 1024 - 1, DELTA_BLOCK_SIZE_SMALL),
            (1024 * 1024, DELTA_BLOCK_SIZE_MEDIUM),
            (10 * 1024 * 1024 - 1, DELTA_BLOCK_SIZE_MEDIUM),
            (10 * 1024 * 1024, DELTA_BLOCK_SIZE_LARGE),
            (100 * 1024 * 1024 - 1, DELTA_BLOCK_SIZE_LARGE),
            (100 * 1024 * 1024, DELTA_BLOCK_SIZE_XLARGE),
            (10 * 1024 * 1024 * 1024, DELTA_BLOCK_SIZE_XLARGE),
        ],
    )
    def test_optimal_block_size_thresholds(self, size, expected):
        assert optimal_block_size(size) == expected

    def test_changed_ratio_all_copy_is_zero(self):
        ops = [DeltaOp.copy(0, BLOCK), DeltaOp.copy(BLOCK, BLOCK)]
        assert changed_block_ratio(ops, 2 * BLOCK, BLOCK) == 0.0

    def test_changed_ratio_all_data_is_one(self):
        ops = [DeltaOp.data(0, BLOCK * 2)]
        assert changed_block_ratio(ops, 2 * BLOCK, BLOCK) == 1.0

    def test_changed_ratio_partial_reuse(self):
        ops = [DeltaOp.copy(0, BLOCK), DeltaOp.data(0, BLOCK * 3)]
        assert changed_block_ratio(ops, 4 * BLOCK, BLOCK) == pytest.approx(0.75)

    def test_changed_ratio_degenerate_inputs(self):
        assert changed_block_ratio([], 0, BLOCK) == 1.0
        assert changed_block_ratio([], 100, 0) == 1.0

    def test_worthwhile_within_thresholds(self):
        ops = [DeltaOp.copy(i * BLOCK, BLOCK) for i in range(7)] + [DeltaOp.data(0, BLOCK)]
        assert is_delta_worthwhile(ops, 8 * BLOCK, BLOCK, BLOCK)

    def test_not_worthwhile_over_change_ratio(self):
        ops = [DeltaOp.copy(0, BLOCK), DeltaOp.data(0, 7 * BLOCK)]
        assert not is_delta_worthwhile(ops, 8 * BLOCK, 7 * BLOCK, BLOCK)

    def test_not_worthwhile_over_literal_cap(self):
        ops = [DeltaOp.copy(0, BLOCK)] * 8
        assert not is_delta_worthwhile(
            ops, 8 * BLOCK, 2 * 1024 * 1024 * 1024, BLOCK, max_literal_size=1024
        )


# ---------------------------------------------------------------------------
# wire-model sanitizers
# ---------------------------------------------------------------------------


class TestSanitizers:
    def test_signature_roundtrip(self):
        sig = BlockSignature(
            index=1, offset=64, length=64, weak=123, strong=sha256(b"x").hexdigest()
        )
        clean = sanitize_signature_list([sig.to_dict()])
        assert clean == [sig.to_dict()]

    def test_signature_rejects_bad_shapes(self):
        assert sanitize_signature_list("nope") is None
        assert sanitize_signature_list([{"index": -1}]) is None
        assert (
            sanitize_signature_list(
                [{"index": 0, "offset": 0, "length": 1, "weak": 2**32, "strong": "a" * 64}]
            )
            is None
        )  # weak out of 32-bit range
        assert (
            sanitize_signature_list(
                [{"index": 0, "offset": 0, "length": 1, "weak": 5, "strong": "not-hex"}]
            )
            is None
        )

    def test_op_roundtrip(self):
        assert sanitize_delta_op(DeltaOp.copy(10, 5).to_dict()) == {
            "type": "copy",
            "offset": 10,
            "length": 5,
            "data_offset": 0,
        }
        assert sanitize_delta_op(DeltaOp.data(2, 3).to_dict()) == {
            "type": "data",
            "offset": 0,
            "length": 3,
            "data_offset": 2,
        }

    def test_op_rejects_bad_shapes(self):
        assert (
            sanitize_delta_op({"type": "wat", "offset": 0, "length": 1, "data_offset": 0}) is None
        )
        assert (
            sanitize_delta_op({"type": "copy", "offset": 0, "length": 0, "data_offset": 0}) is None
        )
        assert (
            sanitize_delta_op({"type": "copy", "offset": -1, "length": 1, "data_offset": 0}) is None
        )
        assert (
            sanitize_delta_op({"type": "copy", "offset": True, "length": 1, "data_offset": 0})
            is None
        )


# ---------------------------------------------------------------------------
# end-to-end property: random mutations always rebuild byte-identically
# ---------------------------------------------------------------------------


class TestProperty:
    @pytest.mark.parametrize("seed", range(5))
    def test_random_mutations_roundtrip(self, tmp_path, seed):
        rng = random.Random(seed)
        base = bytearray(_base_bytes(seed=seed, size=BLOCK * 12))
        new = bytearray(base)
        for _ in range(6):  # apply random splice mutations
            start = rng.randrange(0, len(new))
            length = rng.randrange(1, BLOCK)
            new[start : start + length] = bytes(rng.randrange(256) for _ in range(length))
        base_path = _write(tmp_path / "base.bin", bytes(base))
        sigs = compute_signatures(base_path, BLOCK)
        ops, literals = find_matches(bytes(new), sigs, BLOCK)
        out_path = str(tmp_path / "out.bin")
        apply_delta(base_path, ops, literals, out_path)
        assert open(out_path, "rb").read() == bytes(new)  # noqa: SIM115
        # ops coverage is exact: total op length == new file size, contiguous
        assert sum(op.length for op in ops) == len(new)
        # sanity: ops reference valid ranges
        for op in ops:
            if op.type == OP_TYPE_COPY:
                assert op.offset + op.length <= len(base)
            else:
                assert op.data_offset + op.length <= len(literals)

    def test_large_file_memory_bounded(self, tmp_path):
        """A multi-MB file goes through the mmap path and rebuilds correctly."""
        size = 2 * 1024 * 1024 + 123  # 2 MB + partial tail
        base = os.urandom(size)
        new = bytearray(base)
        new[1024 * 1024 : 1024 * 1024 + 512] = b"M" * 512  # localized 512-byte edit
        base_path = _write(tmp_path / "base.bin", base)
        new_path = _write(tmp_path / "new.bin", bytes(new))
        block = optimal_block_size(size)
        sigs = compute_signatures(base_path, block)
        ops, literals = find_matches_file(new_path, sigs, block)
        out_path = str(tmp_path / "out.bin")
        apply_delta(base_path, ops, literals, out_path)
        assert open(out_path, "rb").read() == bytes(new)  # noqa: SIM115
        assert len(literals) < size // 2  # delta actually saved bandwidth
