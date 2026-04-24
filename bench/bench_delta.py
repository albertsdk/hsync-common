# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""L1 — delta-transfer micro-benchmark (pure, no sockets, deterministic).

Measures the rsync-style engine on the paths a delta round-trip executes:

* ``compute_signatures`` / ``signatures_for_data`` — base-file signatureing at
  the sizes that select each ``optimal_block_size`` tier (4 KB / 16 KB / 64 KB);
* ``build_signature_index`` — the weak-checksum index built per match request;
* ``find_matches_file`` — the sliding-window matcher at 0%, 10% and 50% changed
  blocks (the last one is the literal-heavy worst case bounded by
  ``DELTA_MAX_CHANGE_RATIO``);
* ``apply_delta`` — base reconstruction (copy ops + literal payload);
* ``optimal_block_size`` / ``changed_block_ratio`` / ``is_delta_worthwhile`` —
  the per-negotiation decision helpers.

Methodology specifics:

* Change ratios are produced by a deterministic index selector (every n-th full
  block is replaced with fresh bytes), so runs are reproducible and the changed
  blocks genuinely cannot match a base signature.
* Alignment is preserved for the unchanged blocks: the benchmark isolates the
  matching/literal-coalescing cost, it does not model shifted/inserted content.
* Measured ops assert the op-list and literal-payload lengths observed during
  setup, so a short-circuiting matcher cannot be reported as valid.
* ``apply_delta`` writes into a temp directory removed at exit (clean exit).

Usage:
    cd hsync-common && .venv/bin/python bench/bench_delta.py [--count N] [--json-out FILE]
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from common import (
    BenchResult,
    add_json_out,
    make_payload,
    maybe_write_json,
    measure,
    print_table,
    pseudorandom_bytes,
    size_label,
    write_bytes,
)

from hsync_common.delta import (
    apply_delta,
    build_signature_index,
    changed_block_ratio,
    compute_signatures,
    find_matches,
    find_matches_file,
    is_delta_worthwhile,
    optimal_block_size,
    signatures_for_data,
)

_MB = 1024 * 1024

# (size, sample cap): one size per optimal_block_size tier.
_SIGNATURE_SCENARIOS: tuple[tuple[int, int], ...] = (
    (512 * 1024, 500),
    (4 * _MB, 100),
    (12 * _MB, 20),
)

# (size, every n-th block changed, ratio label, sample cap).
_MATCH_SCENARIOS: tuple[tuple[int, int, str, int], ...] = (
    (_MB, 0, "0%", 200),
    (_MB, 10, "10%", 200),
    (_MB, 2, "50%", 50),
    (4 * _MB, 10, "10%", 50),
)


def _changed_copy(base: bytes, block_size: int, every: int, seed: int) -> bytes:
    """Return ``base`` with every ``every``-th full block replaced by fresh bytes.

    ``every=0`` returns the base untouched (0% changed); the replacement bytes
    are seeded per block, so a run is reproducible while no replaced block can
    match any base signature (they become literal payload).
    """
    if every <= 0:
        return base
    out = bytearray(base)
    for index in range(0, len(base) // block_size, every):
        start = index * block_size
        out[start : start + block_size] = pseudorandom_bytes(block_size, seed + index)
    return bytes(out)


def _bench_decisions(count: int) -> list[BenchResult]:
    """The pure decision helpers called once per delta negotiation."""
    base = make_payload(256 * 1024, "binary", seed=11)
    block_size = optimal_block_size(len(base))
    signatures = signatures_for_data(base, block_size)
    ops, literals = find_matches(_changed_copy(base, block_size, 10, 11), signatures, block_size)
    assert ops
    base_size = len(base)
    literal_size = len(literals)
    sizes = [0, 1, 256 * 1024, 12 * _MB, 200 * _MB]
    size_state = {"i": 0}

    def op_optimal_block_size() -> None:
        size = sizes[size_state["i"] % len(sizes)]
        size_state["i"] += 1
        assert optimal_block_size(size) > 0

    def op_changed_block_ratio() -> None:
        assert 0.0 <= changed_block_ratio(ops, base_size, block_size) <= 1.0

    def op_is_delta_worthwhile() -> None:
        is_delta_worthwhile(ops, base_size, literal_size, block_size)

    return [
        measure("optimal_block_size", op_optimal_block_size, count=count),
        measure("changed_block_ratio", op_changed_block_ratio, count=count),
        measure("is_delta_worthwhile", op_is_delta_worthwhile, count=count),
    ]


def _bench_signatures(workdir: str, size: int, count: int) -> BenchResult:
    """Time streamed signatureing of a base file (one op = whole file)."""
    block_size = optimal_block_size(size)
    path = write_bytes(
        workdir, f"base-{size_label(size)}.bin", make_payload(size, "binary", seed=size)
    )
    expected = compute_signatures(path, block_size)
    assert expected

    def op() -> None:
        signatures = compute_signatures(path, block_size)
        assert len(signatures) == len(expected), len(signatures)

    return measure(f"signatures({size_label(size)},bs={block_size // 1024}KB)", op, count=count)


def _bench_signatures_for_data(size: int, block_size: int, count: int) -> BenchResult:
    """Time the in-memory twin used by fixture builders."""
    data = make_payload(size, "binary", seed=size)
    expected = len(signatures_for_data(data, block_size))

    def op() -> None:
        assert len(signatures_for_data(data, block_size)) == expected

    return measure(f"sig_for_data({size_label(size)},bs={block_size // 1024}KB)", op, count=count)


def _bench_signature_index(count: int) -> BenchResult:
    """Time the weak-checksum index build over 4096 signatures."""
    signatures = signatures_for_data(make_payload(16 * _MB, "binary", seed=7), 4096)
    assert len(signatures) == 4096, len(signatures)

    def op() -> None:
        index = build_signature_index(signatures, 4096)
        assert index

    return measure("build_index(4096 sigs)", op, count=count)


def _bench_match(workdir: str, size: int, every: int, ratio: str, count: int) -> BenchResult:
    """Time the mmap-backed matcher on a base/new fixture pair."""
    block_size = optimal_block_size(size)
    base = make_payload(size, "binary", seed=size)
    base_path = write_bytes(workdir, f"match-base-{size_label(size)}.bin", base)
    new_path = write_bytes(
        workdir,
        f"match-new-{size_label(size)}-{ratio}.bin",
        _changed_copy(base, block_size, every, seed=size),
    )
    signatures = compute_signatures(base_path, block_size)
    expected_ops, expected_literals = find_matches_file(new_path, signatures, block_size)
    if every == 0:
        # An identical file must reuse every block: no literal payload at all.
        assert not expected_literals, len(expected_literals)

    def op() -> None:
        ops, literals = find_matches_file(new_path, signatures, block_size)
        assert len(ops) == len(expected_ops), len(ops)
        assert len(literals) == len(expected_literals), len(literals)

    name = f"match_file({size_label(size)},{ratio},bs={block_size // 1024}KB)"
    return measure(name, op, count=count)


def _bench_apply(workdir: str, size: int, every: int, count: int) -> BenchResult:
    """Time base reconstruction (copy ops streamed + literal payload)."""
    block_size = optimal_block_size(size)
    base = make_payload(size, "binary", seed=size)
    base_path = write_bytes(workdir, f"apply-base-{size_label(size)}.bin", base)
    new_data = _changed_copy(base, block_size, every, seed=size)
    new_path = write_bytes(workdir, f"apply-new-{size_label(size)}.bin", new_data)
    signatures = compute_signatures(base_path, block_size)
    ops, literals = find_matches_file(new_path, signatures, block_size)
    assert literals
    output_path = str(Path(workdir) / f"apply-out-{size_label(size)}.bin")

    def op() -> None:
        written = apply_delta(base_path, ops, literals, output_path)
        assert written == size, written

    literal_pct = round(100 * len(literals) / size)
    return measure(f"apply_delta({size_label(size)},lit={literal_pct}%)", op, count=count)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=2000)
    add_json_out(parser)
    args = parser.parse_args()

    count = args.count
    results = _bench_decisions(count)
    with tempfile.TemporaryDirectory(prefix="hsync-common-bench-") as tmp:
        for size, cap in _SIGNATURE_SCENARIOS:
            results.append(_bench_signatures(tmp, size, min(count, cap)))
        results.append(_bench_signatures_for_data(_MB * 4, 4 * 1024, min(count, 200)))
        results.append(_bench_signature_index(min(count, 2000)))
        for size, every, ratio, cap in _MATCH_SCENARIOS:
            results.append(_bench_match(tmp, size, every, ratio, min(count, cap)))
        results.append(_bench_apply(tmp, _MB, 10, min(count, 100)))

    print(f"delta micro-benchmark (ops={count}, base/new fixture pairs on disk)")
    print_table(results)
    maybe_write_json(args.json_out, results)


if __name__ == "__main__":
    main()
