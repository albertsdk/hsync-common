# Android Mirroring

`hsync-common` is the shared Python library consumed by the server, client, and
desktop projects. The Android app (`hsync-android`) is written in Kotlin and
cannot use the Python library directly. Instead, critical portions of
`hsync-common` are **mirrored** — reimplemented in Kotlin following the same
contract.

This page explains what is mirrored, how to keep it in sync, and the
differences between the Python and Kotlin implementations.

> The *why* behind this approach is documented in the
> [Architecture Decision Records](internal/adr/README.md).

## Table of Contents

- [What is mirrored](#what-is-mirrored)
- [Mirroring strategy](#mirroring-strategy)
- [Data models](#data-models)
- [Protocol constants](#protocol-constants)
- [Compression](#compression)
- [Keeping in sync](#keeping-in-sync)
- [Testing across languages](#testing-across-languages)

---

## What is mirrored

| Module | Python | Kotlin | Notes |
|--------|--------|--------|-------|
| File model | `hsync_common.models.file.File` | `com.hsync.android.data.model.FileItem` | `filepath`, `name`, `ctime`, `mtime`, `size`, `sha256sum`, `permissions` |
| Sync actions | `hsync_common.models.sync_action.SyncActionName` | `com.hsync.android.data.model.SyncAction` | `NOTHING`, `DOWNLOAD`, `UPLOAD`, `DELETE`, `RENAME` |
| Protocol version | `hsync_common.protocol.handshake` | `com.hsync.android.data.api.Protocol` | `VERSION_REST`, `VERSION_WS`, `VERSION_LAN`, capability tokens |
| Compression | `hsync_common.compression` | `com.hsync.android.util.CompressionManager` | Zstandard via `zstd-jni`, level 3 |
| Tombstone store | `hsync_common.models.tombstone` | `com.hsync.android.util.TombstoneStore` (`Tombstones.kt`) | TTL pruning (storage GC), causal vclock merge; Android persistence mirrors ADR-0025 SQLite |
| Sync state (three-way merge) | `hsync_common.models.version` | `com.hsync.android.util.SyncStateStore` (`Version.kt`) | `FileVersion`, `resolveThreeWay`; Python store is SQLite (ADR-0025) |
| Delta engine | `hsync_common.delta` | `com.hsync.android.util.DeltaEngine` | Rolling Adler32, block signatures, find_matches, apply_delta |
| Delta decision | `hsync_common.delta.decision` | `com.hsync.android.util.DeltaDecision` | Block size thresholds, worthwhileness gate |
| Delta transfer | `hsync_client.delta_transfer` | `com.hsync.android.util.DeltaTransfer` | Client-side upload/download delta orchestration |
| LAN delta | `hsync_client.lan_delta` | `com.hsync.android.p2p.LanDelta` | Master-side delta endpoints + token store |
| LAN election | `hsync_common.protocol.lan` | `com.hsync.android.p2p.Election` | `electMaster`, `ranked` |
| LAN pairing | `hsync_common.protocol.pairing` | `com.hsync.android.p2p.Pairing` | `evaluatePin`, `lanWriteRequiresKey`, `requiresPairingConfirmation` |

### What is NOT mirrored

- **Path validation** — Android has its own `PathValidation.kt` adapted to SAF
  (Storage Access Framework) path semantics rather than POSIX paths.
- **Ignore matcher** — Reimplemented as `IgnoreMatcher.kt`/`IgnoreRule.kt` with
  Android-specific optimizations because SAF file access patterns differ from
  POSIX.
- **SSL utilities** — Android uses its own `SslHelper.kt` built on `KeyStore`
  and `CertificateFactory`.
- **Logger/Env/Text utilities** — Platform-specific implementations
  (`LogManager.kt`, `SecureStorage.kt`, etc.).
- **Dir / Symlink / Event models** — The Android app models filesystem state
  through `FileItem` and the SAF layer; the Python `Dir`, `Symlink` and `Event`
  wire models are not mirrored as standalone Kotlin classes.
- **`EventName` enum** — Android uses its own event vocabulary in
  `FileEventQueue.kt` rather than the Python `EventName` values.

---

## Mirroring strategy

The mirror follows a **contract-first** approach:

1. **Python is the source of truth** for data models and protocol constants.
2. **Kotlin mirrors the wire format**, not the implementation. A `File` in
   Python and a `File` in Kotlin must serialize to the same JSON.
3. **Cross-language test fixtures** in `hsync_common/protocol/fixtures/`
   define expected JSON output for each model. Both the Python and Kotlin
   test suites run against these shared fixtures to verify compatibility.

### Fixture-driven contract testing

```
hsync-common/
└── hsync_common/protocol/fixtures/
    ├── lan-election-scenarios.json   # Master election test vectors
    └── lan-pairing-scenarios.json    # Pairing/pinning test vectors

# Python tests use: tests/test_protocol_fixtures.py
# Kotlin tests use: app/src/test/java/.../LanElectionParityTest.kt, LanPairingParityTest.kt
```

Both test suites load the same JSON files and verify their implementations
produce identical results.

---

## Data models

### File model comparison

| Field | Python (`File`) | Kotlin (`FileItem`) | Wire format |
|-------|-----------------|---------------------|-------------|
| `filepath` | `str \| None` | `String` | `"filepath"` or omitted |
| `name` | `str \| None` | `String?` | `"name"` or omitted |
| `ctime` | `int \| None` | `Long?` | Unix timestamp |
| `mtime` | `int \| None` | `Long?` | Unix timestamp |
| `size` | `int` | `Long` | Integer bytes |
| `sha256sum` | `str \| None` | `String?` | Hex string |
| `permissions` | `str \| None` | `String?` | Symbolic string |
| `id` | — | `String` | Local UUID (not on the wire) |
| `action` | — | `SyncAction` | Local sync-queue state (not on the wire) |
| `status` | — | `FileStatus` | Local sync-queue state (not on the wire) |

### Key differences

- **SHA-256 caching**: Python uses an in-memory LRU cache keyed by
  `(filepath, mtime)`; Kotlin's `FileHashUtils` computes hashes on demand with
  a fixed 8 KB buffer and no caching.
- **Adaptive chunk sizes**: Python uses 8 KB / 64 KB / 256 KB depending on file
  size; Kotlin's `FileHashUtils` uses a single fixed 8 KB buffer.
- **`FileDict`**: Python's `TypedDict` has no Kotlin equivalent; Kotlin uses
  a `data class` (`FileItem`) serialized with Gson.
- **Serialization**: Python uses Pydantic/dataclass `to_dict()`; Kotlin uses
  Gson with `@SerializedName` annotations for snake_case wire fields.

---

## Protocol constants

Constants must stay identical across all projects. The single source of truth
is `hsync_common/constants.py`:

```python
HSYNC_VERSION = "1.0.0"
HEADER_CLIENT_NAME = "X-Client-Name"
HEADER_CLIENT_VERSION = "X-Client-Version"
HEADER_SERVER_VERSION = "X-Server-Version"
HEADER_PROTOCOL_VERSION = "X-Protocol-Version"
CLIENT_NAME_PATTERN = "^[a-z][a-z0-9-]*[a-z0-9]$"  # is_valid_client_name()
CONTENT_TYPE_OCTET_STREAM = "application/octet-stream"
CONTENT_TYPE_JSON = "application/json"
HSYNCKEEP_FILENAME = ".hsynckeep"
HSYNCIGNORE_FILENAME = ".hsyncignore"
HSYNCFOLDER_FILENAME = ".hsyncfolder"
HSYNCTOMBSTONES_FILENAME = ".hsynctombstones"  # legacy wire rejection only
TOMBSTONE_TTL_DAYS_DEFAULT = 90
CHUNK_SIZE_SMALL = 8192  # 8 KB
CHUNK_SIZE_MEDIUM = 65536  # 64 KB
CHUNK_SIZE_LARGE = 262144  # 256 KB
```

There is no single `Constants.kt` in the Android app; the constants are
distributed across the Kotlin files that mirror their Python counterparts:

| Constant | Kotlin location |
|----------|-----------------|
| `HSYNC_VERSION` | `BuildConfig.VERSION_NAME` (Gradle `versionName`; sent as the WS `app_version` and the REST `X-Client-Version` header) |
| `HEADER_*` | `com.hsync.android.data.api.Protocol` (`HEADER_PROTOCOL_VERSION`; `HEADER_CLIENT_NAME`/`HEADER_CLIENT_VERSION` added by `ProtocolHeaderInterceptor`) |
| `CLIENT_NAME_PATTERN` | `Protocol.CLIENT_NAME` slug + the server-side `is_valid_client_name` middleware check (Android sends a compliant slug) |
| `CONTENT_TYPE_*` | literals in `LanServer.kt` (`CONTENT_TYPE_OCTET`), `SafHelper.kt`, `SyncRepository.kt`, `DeltaTransfer.kt` |
| `HSYNCKEEP_FILENAME`, `HSYNCIGNORE_FILENAME` | `com.hsync.android.util.IgnoreMatcher` (companion object) |
| `HSYNCFOLDER_FILENAME` | Referenced as a string literal in `PathValidation.kt` |
| `HSYNCTOMBSTONES_FILENAME` | Referenced as a string literal in `PathValidation.kt` / `IgnoreMatcher.kt` (legacy rejection) |
| `TOMBSTONE_TTL_DAYS_DEFAULT` | `com.hsync.android.util.Tombstones.kt` (`TOMBSTONE_TTL_DAYS_DEFAULT = 90L`) |
| `CHUNK_SIZE_SMALL/MEDIUM/LARGE` | Not exposed as named constants; `FileHashUtils` uses a fixed 8 KB buffer |
| `DELTA_*` constants | `com.hsync.android.util.DeltaConfig` |

### When to update

When changing any constant in `hsync-common`:

1. Update `hsync_common/constants.py`
2. Update the corresponding Kotlin constant in its mirror file
3. Run both test suites to verify no regressions
4. Bump `PROTOCOL_VERSION_REST` if the change affects the wire protocol

---

## Compression

Both Python and Kotlin use **Zstandard (zstd)** with compression level 3.
Python uses the `zstandard` package; Kotlin uses `zstd-jni` via JNI bindings.

| Aspect | Python | Kotlin |
|--------|--------|--------|
| Library | `zstandard` (PyPI) | `com.github.luben:zstd-jni` (Maven) |
| Level | 3 | 3 |
| Pre-compressed extensions | `PRECOMPRESSED_EXTENSIONS` (frozenset, 95 entries) | `PRECOMPRESSED_EXTENSIONS` (Set<String>) in `CompressionManager` |
| Upload threshold | `MIN_SIZE_FOR_UPLOAD` = 32 KB | `MIN_SIZE_FOR_UPLOAD` = 32 KB |
| LAN threshold | `MIN_SIZE_FOR_LAN` = 100 KB | `MIN_SIZE_FOR_LAN` = 100 KB |
| Download threshold | `MIN_SIZE_FOR_COMPRESSION` = 10 KB | — (not exposed in `CompressionManager`) |

Both implementations must produce byte-identical compressed output for the
same input. The cross-language test fixtures include compression round-trip
vectors to verify this.

---

## Keeping in sync

### When adding a new model field

1. Add the field to the Python model (`hsync_common/models/`)
2. Update `hsync_common/protocol/fixtures/` with new test vectors
3. Add the field to the Kotlin model
4. Run both test suites
5. Update this document

### When adding a new endpoint

1. Implement the endpoint in `hsync-server`
2. Update `hsync_common/protocol/handshake.py` if protocol version changes
3. Implement the endpoint in the Kotlin networking layer
4. Add cross-language test fixtures
5. Update the relevant protocol documentation (`docs/protocol.md`, `docs/lan-protocol.md`)

### Checklist for protocol changes

- [ ] Python model updated in `hsync-common`
- [ ] Kotlin model updated in `hsync-android`
- [ ] Protocol version bumped if wire format changed
- [ ] Test fixtures updated with new vectors
- [ ] Python tests pass
- [ ] Kotlin tests pass
- [ ] This document updated

---

## Testing across languages

### Running Python tests

```bash
cd hsync-common
.venv/bin/python -m pytest tests/ -k "fixture"
```

### Running Kotlin tests

```bash
cd hsync-android
./gradlew test
```

### CI integration

Both test suites should run in CI when either project changes:

- **PR to hsync-common**: run Python tests + trigger Android tests
- **PR to hsync-android**: run Android tests (Python models are stable)

## See also

- [Architecture](internal/architecture.md) — `hsync-common` architecture overview.
- [Architecture Decision Records](internal/adr/README.md) — why the mirroring approach was chosen.
- [LAN Protocol](lan-protocol.md) — protocol specification.
