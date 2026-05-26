# HSYNC Common Library — Benchmarks (L1)

Internal micro-benchmark suite for the hot library paths. Developer tooling:
plain scripts under `bench/`, never collected by pytest, never run in CI, no
user-facing behaviour.

## Why only one tier

`hsync-common` is a dependency-light library imported by the runtime projects
and mirrored in Kotlin (`llm-wiki/architecture.md:3`): it has no process, no
socket and no transport of its own. The bootnode tier split therefore does not
map onto it — L2/L3 (spawn a binary over the wire) and L5 (node-process CPU
saturation) have no subject here. L4 (profiling) is added only when a concrete
anomaly needs a cost breakdown.

## Files

| Path | Role |
| --- | --- |
| `bench/README.md` | Tier table, per-script scope, run commands, methodology |
| `bench/common.py` | Stdlib-only measurement core + deterministic fixture builders; never imports `hsync_common` |
| `bench/bench_hashing.py` | `hsync_common/hashing.py` scenarios |
| `bench/bench_compression.py` | `hsync_common/compression.py` scenarios |
| `bench/bench_delta.py` | `hsync_common/delta/` scenarios |
| `bench/bench_ignore.py` | `hsync_common/ignore.py` scenarios |
| `bench/bench_models.py` | `hsync_common/models/` serialization scenarios |

## Scenario → code anchors

| Scenario | Public API measured |
| --- | --- |
| `sha256(64KB/1MB/16MB)`, `sha256_async(...)` | `hashing.compute_sha256` (`hsync_common/hashing.py:69`), `compute_sha256_async` (`:86`) |
| `is_sha256_hex`, `adaptive_chunk_size` | `hsync_common/hashing.py:37`, `:48` |
| `should_compress` | `hsync_common/compression.py:172` (threshold + `PRECOMPRESSED_EXTENSIONS` gate) |
| `compress_data` / `decompress_data` | `hsync_common/compression.py:219`, `:224` (capped streaming read) |
| `compress_file_to_file` | `hsync_common/compression.py:312` (streaming upload path) |
| `decompress_stream` | `hsync_common/compression.py:253` (anti decompression-bomb cap) |
| `signatures(...)`, `sig_for_data(...)` | `delta/rolling_checksum.py:123`, `:144` |
| `build_index(4096 sigs)` | `delta/rolling_checksum.py:180` |
| `match_file(size,chg%,bs)` | `delta/rolling_checksum.py:277` → `find_matches` (`:202`) |
| `apply_delta(1MB,lit=N%)` | `delta/rolling_checksum.py:301` |
| `optimal_block_size`, `changed_block_ratio`, `is_delta_worthwhile` | `delta/decision.py:38`, `:53`, `:71` |
| `matcher_ctor(extra=N)` | `ignore.IgnoreMatcher.__init__` / `reload` (`hsync_common/ignore.py:65`, `:80`) |
| `matches(single path)` | `hsync_common/ignore.py:150` |
| `should_skip(...)` | `hsync_common/ignore.py:217` (active matcher → fallback) |
| `sweep(N paths,bucket\|defaults)` | full-scan cost with bucket rules vs. default-only fallback |
| `file_to_dict` / `file_from_dict(strip\|prepend)` | `models/file.py:234`, `:289` via `models/_util.py:56` |
| `dir_*`, `symlink_*` | `models/dir.py:64`/`:79`, `models/symlink.py:96`/`:108` |
| `event_ctor(rename)`, `event_to_dict` | `models/event.py:108`, `:139` |
| `is_valid_cid`, `is_partial_file` | `models/event.py:30`, `models/file.py:131` |

## Methodology (must-read before trusting a number)

1. Warmup runs **outside** the timed samples, capped at `min(200, count // 10)`
   (`common.scaled_warmup`) so heavy scenarios stay cheap.
2. Fixtures are built once per scenario, outside the timed region (payload
   files, base/new pairs, signature lists, compiled matchers).
3. Every measured op **asserts the branch** observed during setup (digest
   equality, output length, op-list/literal length, skip count), so a silent
   drop or a truncated read can never look like a fast success.
4. Each scenario owns its fixture lifecycle; temp files live in a
   `TemporaryDirectory` and the process-wide ignore matcher is cleared in a
   `finally`. A benchmark must not leak state into the next scenario.
5. `bench_compression.py` silences loguru's sink (`logger.remove()`) so
   `should_compress` is measured at the production log level (INFO) without
   sink I/O — `hsync_common/compression.py:206` logs once per skipped file.
6. Payload generation is seeded (`common.make_payload`): text (highly
   compressible), binary (low-nibble entropy, semi-compressible),
   incompressible (raw PRNG bytes).
7. Numbers are **comparative** (this machine, warm page cache), never SLAs.

## Findings worth knowing (default run, `--count 2000`, after A1–A5 + B1–B3)

* `compute_sha256` runs at ~1.5 GB/s (`sha256_async(16MB)` now matches the
  sync 16 MB rate: A3 replaced the 8 KB-chunk `aiofiles` loop with a single
  `asyncio.to_thread` hop).
* zstd direction-aware levels (A4): on `binary-1MB` level 1 is **5.5x faster**
  than level 3 (1146 vs 208 ops/s) and even 3 % smaller
  (524461 B vs 540956 B); on `text-1MB` it is 1.2x faster for 13 % larger
  output — the upload/LAN tradeoff the `compression_level()` SSOT encodes.
* Delta `find_matches` (A2 + B1): identical-file 1 MB at ~1.01 ms; 10 %
  changed at ~25.98 ms (was ~27.53 ms, −5.6 %: B1 replaced the two per-byte
  `%` divisions with conditional corrections + a 256-entry `(n*byte)%MOD`
  table, `delta/rolling_checksum.py:66`); 50 % changed at ~115.13 ms
  (was ~122.62 ms, −6.1 %); 4 MB 10 % at ~97.04 ms (was ~102.07 ms, −4.9 %);
  the front-insertion case (`10%+4KB`, ~26.84 ms) costs no more than plain
  10 % because the window re-synchronises after the shift.
* Ignore (A5 + B2): `matches` single-path at ~0.009 ms (~111k ops/s) with the
  prefix-strip fast path; a 5000-path bucket sweep costs ~43.60 ms with a
  realistic `.hsyncignore` (~24.09 ms with the default-only fallback). B2
  cached the `root + "/"` prefix at construction (`ignore.py`), made
  `should_skip` lock-free (direct `_active_matcher` read) and skipped the
  `\\`→`/` rewrite when absent — sweep noise dominates, single-path is
  unchanged.
* Path prepend (B3): `file_from_dict(prepend)` at ~1.1 µs (was ~4.0 µs, **3.6x**),
  `dir_from_dict(prepend)` at ~0.5 µs (was ~3.1 µs, **~6x**),
  `symlink_from_dict` at ~0.8 µs (was ~3.3 µs, **~4x**) —
  `_resolve_prefixed_path` (`models/_util.py:124`)
  now uses string concat instead of `Path(prefix) / rel` on the prepend
  branch (pinned by `test_prepend_matches_pathlib_join` in
  `tests/test_models_file.py`). `file_from_dict(strip)` unchanged at ~2.1 µs.
* Path stripping (A1): `relpath_in_bucket` at ~1.1 µs and
  `file_from_dict(strip)` at ~2.1 µs — up from 12.8 µs/14 µs
  (~9x/6.5x), so model decode is no longer path-normalisation dominated.
  (`Event` construction at ~1.8 µs still costs ~2x its own serialization
  (~0.9 µs) because it re-normalises the src/dst paths.)
* Unchanged areas (same machine, B1–B3 touched only delta/ignore/models):
  hashing (`sha256(1MB)` ~0.63 ms, ~1.5 GB/s), compression
  (`compress_data(binary-1MB)` ~4.68 ms, `text-1MB` ~0.38 ms) and
  `signatures`/`apply_delta` are within run-to-run noise of the A1–A5
  baseline.

## Running

```bash
cd hsync-common
.venv/bin/python bench/bench_hashing.py  --count 2000 [--json-out FILE]
.venv/bin/python bench/bench_compression.py --count 2000 [--json-out FILE]
.venv/bin/python bench/bench_delta.py    --count 2000 [--json-out FILE]
.venv/bin/python bench/bench_ignore.py   --count 2000 [--json-out FILE]
.venv/bin/python bench/bench_models.py   --count 2000 [--json-out FILE]
```

Lint: `cd hsync-common && .venv/bin/python -m ruff check bench` — the directory
is covered by the project ruff config, so the Quality Gate applies to `bench/`
too.
