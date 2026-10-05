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
| `bench/bench_path_validation.py` | `hsync_common/path_validation.py` scenarios |
| `bench/bench_stores.py` | `hsync_common/models/` store scenarios (`SyncStateStore`, `TombstoneStore`) |

## Scenario → code anchors

| Scenario | Public API measured |
| --- | --- |
| `sha256(64KB/1MB/16MB)`, `sha256_async(...)` | `hashing.compute_sha256` (`hsync_common/hashing.py:82`), `compute_sha256_async` (`:99`) |
| `is_sha256_hex`, `adaptive_chunk_size` | `hsync_common/hashing.py:37`, `:61` |
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
| `file_to_dict` / `file_from_dict(strip\|prepend\|rel_strip)` | `models/file.py:234`, `:289` via `models/_util.py:56` |
| `dir_*`, `symlink_*` | `models/dir.py:64`/`:79`, `models/symlink.py:96`/`:108` |
| `event_ctor(rename)`, `event_to_dict` | `models/event.py:108`, `:139` |
| `is_valid_cid`, `is_partial_file` | `models/event.py:30`, `models/file.py:131` |
| `validate_remote_relpath(valid\|escape)` | `path_validation.validate_remote_relpath` (`hsync_common/path_validation.py:481`) |
| `resolve_within(valid\|escape)` | `path_validation.resolve_within` (`hsync_common/path_validation.py:542`) |
| `wire_relpaths(2-key)` | `path_validation.wire_relpaths` (`hsync_common/path_validation.py:456`) |
| `SyncStateStore.record` / `get` / `retain` | `models/version_store.py:77`, `models/_store_base.py:55`, `models/version_store.py:99` |
| `SyncStateStore.save+load` | `models/_store_base.py` persistence skeleton (SQLite WAL) |
| `TombstoneStore.merge(dominant)` | `models/tombstone_store.py:152` (untrusted-payload sanitize + causal adopt) |

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

## Findings worth knowing (default run, `--count 2000`, current committed baseline)

* `compute_sha256` runs at ~1.5 GB/s (`sha256_async(16MB)` now matches the
  sync 16 MB rate: A3 replaced the 8 KB-chunk `aiofiles` loop with a single
  `asyncio.to_thread` hop).
* zstd direction-aware levels: on `binary-1MB` level 1 is **5.5x faster**
  than level 3 (1146 vs 208 ops/s) and even 3 % smaller
  (524461 B vs 540956 B); on `text-1MB` it is 1.2x faster for 13 % larger
  output — the upload/LAN tradeoff the `compression_level()` SSOT encodes.
* Compression gate: `should_compress` at ~0.0005 ms (~1.9M ops/s) — the
  skip-path `log.debug` calls switched to lazy loguru args (the f-string was
  formatted even at INFO level), a ~9 % win on the per-file gate
  (`hsync_common/compression.py:224`).
* Delta `find_matches` (A2 + B1): identical-file 1 MB at ~1.01 ms; 10 %
  changed at ~25.90 ms (was ~27.53 ms, −5.9 %: B1 replaced the two per-byte
  `%` divisions with conditional corrections + a 256-entry `(n*byte)%MOD`
  table, `delta/rolling_checksum.py:66`); 50 % changed at ~114.29 ms
  (was ~122.62 ms, −6.8 %); 4 MB 10 % at ~97.52 ms (was ~102.07 ms, −4.5 %);
  the front-insertion case (`10%+4KB`, ~27.12 ms) costs no more than plain
  10 % because the window re-synchronises after the shift.
* Ignore (A5 + B2): `matches` single-path at ~0.009 ms (~108k ops/s) with the
  prefix-strip fast path; a 5000-path bucket sweep costs ~43.76 ms with a
  realistic `.hsyncignore` (~23.90 ms with the default-only fallback). B2
  cached the `root + "/"` prefix at construction (`ignore.py`), made
  `should_skip` lock-free (direct `_active_matcher` read) and skipped the
  `\\`→`/` rewrite when absent — sweep noise dominates, single-path is
  unchanged.
* Path prepend: `file_from_dict(prepend)` at ~1.0 µs (was ~4.0 µs, **~4x**),
  `dir_from_dict(prepend)` at ~0.6 µs (was ~3.1 µs, **~5x**),
  `symlink_from_dict` at ~0.8 µs (was ~3.3 µs, **~4x**) —
  `_resolve_prefixed_path` (`models/_util.py:124`)
  now uses string concat instead of `Path(prefix) / rel` on the prepend
  branch (pinned by `test_prepend_matches_pathlib_join` in
  `tests/test_models_file.py`). `file_from_dict(strip)` unchanged at ~2.1 µs
  (C5, direct dict access in the same decode, was a semantic cleanup with no
  measurable gain).
* Path stripping: `relpath_in_bucket` at ~1.1 µs and
  `file_from_dict(strip)` at ~2.1 µs — up from 12.8 µs/14 µs
  (~9x/6.5x), so model decode is no longer path-normalisation dominated.
  (`Event` construction at ~1.8 µs still costs ~2x its own serialization
  (~0.9 µs) because it re-normalises the src/dst paths.)
* Steady-state reconcide micro-opts: a `hsync-client` cProfile of the
  in-sync reconcile showed the per-file cost spread flatly across the shared
  model/validation layer, so four behavior-preserving fast paths were added
  here — `to_epoch` returns an int verbatim (`time_utils.py:101`),
  `File.get` uses `os.stat` instead of `Path(...).stat()` (`models/file.py:259`,
  test switched to patch `os.stat`), `_resolve_prefixed_path` returns an
  already-relative path verbatim when the prefix is absolute
  (`models/_util.py:118`), and `validate_remote_relpath` guards the NFC
  normalize with `is_normalized` (`path_validation.py:509`). Measured effect:
  `file_round_trip` ~2.1→1.3 µs, `file_from_dict(strip)` ~2.1→1.9 µs,
  `file_ctor` ~0.7→0.6 µs; the production decode shape (relative listing path +
  strip) is now a dedicated `file_from_dict(rel_strip)` scenario at ~0.9 µs,
  ~2.3x cheaper than the absolute-strip branch. `validate_remote_relpath`
  unchanged (~1.9 µs: the NFC guard is a no-op on already-normalized ASCII).
  No wire/semantic change: consumers and the Kotlin mirrors are unaffected.
* Unchanged areas (same machine, each hot-path edit touched only its target):
  hashing (`sha256(1MB)` ~0.63 ms, ~1.5 GB/s), compression payloads
  (`compress_data(binary-1MB)` ~4.81 ms, `text-1MB` ~0.38 ms) and
  `signatures`/`apply_delta` are within run-to-run noise of the A1–A5
  baseline.
* New coverage: `resolve_within(valid)` at ~0.028 ms is ~15x the pure-lex
  `validate_remote_relpath(valid)` (~0.0016 ms) — the confining `Path.resolve()`
  syscall dominates the hit path; an escaping `../` path is rejected at
  ~0.0004 ms (lexical guards fire before any syscall). Store layer:
  `SyncStateStore.record` ~0.0032 ms, `get` ~0.0010 ms, `save+load` ~0.019 ms
  (SQLite WAL round-trip), `TombstoneStore.merge(dominant)` ~0.0040 ms.
* Hot-path micro-opts (`6ba2c34`, `bench_result.txt` 2026-09-23): single-pass
  `compare_vclocks`, regex-free `is_valid_cid`, merged forbidden/control scan
  in `validate_remote_relpath`, LRU-1 prefix cache in `_strip_prefix_components`,
  frozenset fast path in `File.from_dict`. Measured on the committed baseline:
  `relpath_in_bucket(in)` ~0.0008 ms, `validate_remote_relpath(valid)` ~0.0016 ms,
  `TombstoneStore.merge(dominant)` ~0.0040 ms,
  `decompress_data(text-100KB)`/`compress_data(text-100KB)` ~0.0155/0.0375 ms.
  `sha256_async(1MB)` (~0.86 ms p50) and `file_round_trip` (~0.0015 ms) were
  flagged by the A/B comparator but both sit at/below the timer-noise floor
  on re-run — tracked as noise, not regressions.

* Model-decode fast paths (`perf` pass, `models/file.py` + `path_validation.py`):
  `File.__init__` returns a plain-`int` `ctime`/`mtime` verbatim instead of
  routing it through `_parse_time` → `to_epoch` (the wire shape is epoch
  seconds), and `validate_remote_relpath` measures the path with `len()` when it
  is ASCII instead of allocating its UTF-8 bytes (`path_validation.py:547`).
  Measured A/B on this machine (`--count 5000`, stash/restore):
  `file_from_dict(prepend)` 1.2→1.0 µs (+14.8 %),
  `file_from_dict(rel_strip)` 1.1→1.0 µs (+14.3 %), `file_ctor` 0.6→0.5 µs
  (+10.3 %), `file_round_trip` 1.5→1.4 µs (+7.8 %),
  `validate_remote_relpath(valid)` 1.6→1.5 µs (+4.6 %).
  `Dir`/`Symlink` decode (no timestamp parse) and the hashing, compression,
  delta, ignore and store scenarios are unchanged within run-to-run noise. No
  signature or wire/semantic change: consumers and the Kotlin mirrors are
  unaffected.

## Running

```bash
cd hsync-common
.venv/bin/python bench/bench_hashing.py  --count 2000 [--json-out FILE]
.venv/bin/python bench/bench_compression.py --count 2000 [--json-out FILE]
.venv/bin/python bench/bench_delta.py    --count 2000 [--json-out FILE]
.venv/bin/python bench/bench_ignore.py   --count 2000 [--json-out FILE]
.venv/bin/python bench/bench_models.py   --count 2000 [--json-out FILE]
.venv/bin/python bench/bench_path_validation.py --count 2000 [--json-out FILE]
.venv/bin/python bench/bench_stores.py   --count 2000 [--json-out FILE]
```

Lint: `cd hsync-common && .venv/bin/python -m ruff check bench` — the directory
is covered by the project ruff config, so the Quality Gate applies to `bench/`
too.
