# Benchmarks — hsync-common

One tier, **L1: pure in-process micro-benchmarks**. `hsync-common` is a library
with no process, no socket and no transport of its own, so the bootnode tier
split does not map onto it:

| Tier | Status here | Why |
|---|---|---|
| L1 — in-process micro-benchmark | **implemented** (this directory) | Measures the hot library calls every consumer runs per file/per event |
| L2/L3 — transport load + soak | n/a | Nothing to spawn: the transport belongs to the client/server/LAN layers, not to this package |
| L4 — profiling diagnostic | n/a (yet) | Added only when a specific anomaly needs a cost breakdown; use `--json-out` + a profiler meanwhile |
| L5 — CPU-saturation sweep | n/a | Single-process, single-threaded pure-Python calls: saturation belongs to the consuming process |

Each script is a **plain script, not a test**: it is never collected by pytest
(`testpaths = ["tests"]`), never runs in CI, and asserts only that the measured
operation really took the intended branch.

## Scripts

| Script | Measures |
|---|---|
| `bench_hashing.py` | `compute_sha256` / `compute_sha256_async` at 64 KB/1 MB/16 MB, plus the `is_sha256_hex` and `adaptive_chunk_size` helpers |
| `bench_compression.py` | `should_compress`, `compress_data` / `decompress_data` (text / binary / incompressible at 100 KB–10 MB), `compress_file_to_file`, `decompress_stream` |
| `bench_delta.py` | `compute_signatures`, `signatures_for_data`, `build_signature_index`, `find_matches_file` (0/10/50 % changed blocks), `apply_delta`, decision helpers |
| `bench_ignore.py` | `IgnoreMatcher` construction (default + extra patterns), per-path `matches` / `should_skip`, full-scan sweeps (bucket rules vs. default-only fallback) |
| `bench_models.py` | `File` / `Dir` / `Symlink` / `Event` encode/decode round-trips, `is_valid_cid`, `is_partial_file`, `File` construction |

## Running

```bash
cd hsync-common

# the whole suite (one script per concern)
.venv/bin/python bench/bench_hashing.py  --count 2000
.venv/bin/python bench/bench_compression.py --count 2000
.venv/bin/python bench/bench_delta.py    --count 2000
.venv/bin/python bench/bench_ignore.py   --count 2000
.venv/bin/python bench/bench_models.py   --count 2000

# machine-readable results (one JSON array per run)
.venv/bin/python bench/bench_hashing.py --count 2000 --json-out /tmp/hashing.json
```

`--count` is the number of timed samples for the cheap operations. Heavier
operations are capped per scenario (a 16 MB hash, a 50 %-changed match) so a
default run stays in the tens of seconds; the reported `n` column shows the
effective sample count.

## Methodology

* **Warmup outside the samples**: warmup iterations run before timing and are
  scaled to `min(200, count // 10)`, so a heavy scenario is not run hundreds of
  times just to warm up.
* **Setup outside the timed region**: fixtures (payload files, base/new pairs,
  signatures, compiled matchers) are prepared once per scenario.
* **Branch assertions inside the measured op**: every sample asserts the reply
  digest, output length, op-list size or skip count observed during setup —
  a silent drop, a truncated read or an ignored ignore-rule cannot be reported
  as a fast success.
* **One scenario, one fixture lifecycle**: each scenario builds its own state,
  so no scenario can be faster because a previous one warmed shared state.
  Temp files live in a `TemporaryDirectory` removed at exit; the process-wide
  ignore matcher is cleared in a `finally`.
* **Deterministic payloads**: seeded generators (`common.make_payload`) make a
  run reproducible on the same interpreter.
* **Comparisons are relative**: numbers are valid for this machine and warm OS
  page cache. They are used to compare implementations, chunk sizes and block
  sizes — never as production SLAs.

## Shared helpers

`bench/common.py` is stdlib-only and **never imports `hsync_common`**: the
harness must stay usable if the library internals are rewritten.

* measurement core — `BenchResult`, `measure`, `measure_async`, `percentile`,
  `print_table`, `add_json_out`, `maybe_write_json`;
* fixture builders — `make_payload` (text / semi-compressible binary /
  incompressible), `pseudorandom_bytes`, `write_bytes`, `size_label`;
* `scaled_warmup` — the warmup policy described above.
