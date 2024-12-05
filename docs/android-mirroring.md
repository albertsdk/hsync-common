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
| Data models | `hsync_common.models` | `com.hsync.android.data.model` | `File`, `Dir`, `Symlink`, `Event`, `SyncAction`, `TombstoneEntry` |
| Event types | `hsync_common.models.event.EventName` | `com.hsync.android.data.model.EventName` | `added`, `modified`, `renamed`, `deleted`, `symlink` |
| Sync actions | `hsync_common.models.sync_action.SyncActionName` | `com.hsync.android.data.model.SyncActionName` | `download`, `upload`, `delete`, `nothing` |
| Constants | `hsync_common.constants` | `com.hsync.android.util.Constants` | `VERSION`, sentinel filenames, chunk sizes |
| Compression | `hsync_common.compression` | `com.hsync.android.util.Compression` | Zstandard via `zstd-jni` |
| Protocol version | `hsync_common.protocol.handshake` | `com.hsync.android.network.Protocol` | `PROTOCOL_VERSION_REST` |
| Tombstone store | `hsync_common.models.tombstone` | `com.hsync.android.data.TombstoneStore` | JSON persistence, TTL pruning |
| Delta engine | `hsync_common.delta` | `com.hsync.android.util.DeltaEngine` | Rolling Adler32, block signatures, find_matches, apply_delta |
| Delta decision | `hsync_common.delta.decision` | `com.hsync.android.util.DeltaDecision` | Block size thresholds, worthwhileness gate |
| Delta transfer | `hsync_client.delta_transfer` | `com.hsync.android.util.DeltaTransfer` | Client-side upload/download delta orchestration |
| LAN delta | `hsync_client.lan_delta` | `com.hsync.android.p2p.LanDelta` | Master-side delta endpoints + token store |

### What is NOT mirrored

- **Path validation** — Android uses SAF (Storage Access Framework) which
  provides path safety at the OS level.
- **Ignore matcher** — Reimplemented with Android-specific optimizations
  because SAF file access patterns differ from POSIX.
- **SSL utilities** — Android uses its own `KeyStore` and `CertificateFactory`.
- **Logger/Env/Text utilities** — Platform-specific implementations.
- **SyncStateStore (three-way merge)** — Not yet mirrored; Android uses the
  legacy mtime/hash heuristic for conflict resolution.

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

# Python tests use: tests/test_fixtures.py
# Kotlin tests use: app/src/test/java/.../ProtocolFixturesTest.kt
```

Both test suites load the same JSON files and verify their implementations
produce identical results.

---

## Data models

### File model comparison

| Field | Python (`File`) | Kotlin (`File`) | Wire format |
|-------|-----------------|-----------------|-------------|
| `filepath` | `str \| None` | `String?` | `"filepath"` or omitted |
| `name` | `str \| None` | `String?` | `"name"` or omitted |
| `ctime` | `int \| None` | `Long?` | Unix timestamp |
| `mtime` | `int \| None` | `Long?` | Unix timestamp |
| `size` | `int` | `Long` | Integer bytes |
| `sha256sum` | `str \| None` | `String?` | Hex string |
| `permissions` | `str \| None` | `String?` | Symbolic string |

### Key differences

- **SHA-256 caching**: Python uses an in-memory LRU cache; Kotlin uses a
  simpler `LruCache` from Android's `android.util`.
- **Adaptive chunk sizes**: Same constants, different I/O primitives
  (Python `open()` vs Kotlin `FileInputStream`).
- **`FileDict`**: Python's `TypedDict` has no Kotlin equivalent; Kotlin uses
  a `data class` with `kotlinx.serialization`.

---

## Protocol constants

Constants must stay identical across all projects. The single source of truth
is `hsync_common/constants.py`:

```python
VERSION = "1.0.0"
HSYNCKEEP_FILENAME = ".hsynckeep"
HSYNCIGNORE_FILENAME = ".hsyncignore"
HSYNCTOMBSTONES_FILENAME = ".hsynctombstones"
TOMBSTONE_TTL_DAYS_DEFAULT = 30
CHUNK_SIZE_SMALL = 8192    # 8 KB
CHUNK_SIZE_MEDIUM = 65536  # 64 KB
CHUNK_SIZE_LARGE = 262144  # 256 KB
```

The Kotlin equivalent in `Constants.kt`:

```kotlin
object Constants {
    const val VERSION = "1.0.0"
    const val HSYNCKEEP_FILENAME = ".hsynckeep"
    const val HSYNCIGNORE_FILENAME = ".hsyncignore"
    const val HSYNCTOMBSTONES_FILENAME = ".hsynctombstones"
    const val TOMBSTONE_TTL_DAYS_DEFAULT = 30
    const val CHUNK_SIZE_SMALL = 8192L
    const val CHUNK_SIZE_MEDIUM = 65536L
    const val CHUNK_SIZE_LARGE = 262144L
}
```

### When to update

When changing any constant in `hsync-common`:

1. Update `hsync_common/constants.py`
2. Update the corresponding Kotlin constant in `Constants.kt`
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
| Pre-compressed extensions | `PRECOMPRESSED_EXTENSIONS` (frozenset) | `PrecompressedExtensions` (Set<String>) |
| Threshold | 10 KB (base), 32 KB (upload), 100 KB (LAN) | Same thresholds |

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
5. Update `docs/api.md`

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
poetry run pytest tests/ -k "fixture"
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
