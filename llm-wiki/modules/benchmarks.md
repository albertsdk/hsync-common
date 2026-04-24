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

## Findings worth knowing (default run, `--count 2000`)

* `compute_sha256` runs at ~1.5 GB/s and is size-tier agnostic (C-level
  `file_digest`), while `compute_sha256_async` defaults to `CHUNK_SIZE_SMALL`
  (8 KB) and is ~7x slower per byte on 16 MB (12.5 ops/s vs 90.4 ops/s): the
  async path pays per-chunk `aiofiles` overhead, so the caller-supplied
  `chunk_size` matters far more there than on the sync path.
* zstd level 3 is ~25x slower on *semi-compressible* binary input than on
  already-incompressible input (`binary-1MB` 5.05 ms vs `incompressible-1MB`
  0.17 ms): the compressor works hardest when there is structure to find.
* The delta literal path dominates: `match_file(1MB,10%)` 63.6 ms and
  `match_file(1MB,50%)` 212 ms versus 1.58 ms for an identical file, because
  unmatched bytes are coalesced byte-by-byte in Python — the reason
  `DELTA_MAX_CHANGE_RATIO` aborts above 50 % (`delta/decision.py:71`).
* Ignore sweeps cost ~52 ms per 5000-path bucket scan with a realistic
  `.hsyncignore` and ~26 ms with the default-pattern fallback; matcher
  construction is ~0.18 ms but grows ~8x with 300 extra user patterns
  (gitignore patterns are compiled on every `reload`).
* Model serialization is not the bottleneck (`File.to_dict` 0.5 µs,
  `File.from_dict` 14 µs); `Event` construction (~20 µs) costs 20x its own
  serialization (~1 µs) because it re-normalises the src/dst paths.

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
