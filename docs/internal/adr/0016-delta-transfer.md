# ADR 0016 — Delta Transfer (rsync-style block sync)

- **Status:** Accepted
- **Date:** 2026-07-28

## Context

HSYNC traditionally transfers files **in their entirety**: when a file changes
on one peer, the new version is uploaded to the server (or p2p master) and
downloaded by every other peer. For small files this is acceptable, but for
large files with minor changes (e.g. a 100 MB video with a 1 MB edit, or a
multi-GB database dump with a few modified records) the bandwidth cost is
disproportionate to the actual data change.

### Problem statement

- **Bandwidth waste**: transferring 100 MB to update 1 MB of content is
  inefficient, especially on metered connections or slow links.
- **Latency**: large transfers take longer, delaying synchronization and
  increasing the window for conflicts.
- **Cost**: on cloud-hosted servers with egress billing, unnecessary data
  transfer directly increases operational cost.

### Existing alternatives

| Alternative | Rejected because |
|-------------|-----------------|
| **Manual rsync** | Requires users to run a separate tool outside HSYNC; breaks the unified sync model; no real-time event propagation |
| **Content-addressed deduplication** ([ADR-0007](0007-content-addressed-storage.md)) | Deduplicates identical files across peers, but does not help when a single file changes incrementally |
| **Chunked upload with server-side dedup** | Server must store every chunk ever uploaded; complex metadata; doesn't reduce download bandwidth for other peers |
| **Binary diff (bsdiff/xdelta)** | Requires the server to hold both old and new versions; not suitable for streaming; CPU-intensive on the server |
| **rsync-style rolling checksum (chosen)** | Client-side computation, server only stores signatures; works with existing file storage; transparent fallback to full transfer |

### Why rsync-style?

The rsync algorithm (Tridgell & Mackerras, 1996) is the industry standard for
efficient delta synchronization. It uses a **rolling checksum** (Adler32) for
fast block matching and a **strong hash** (SHA-256 in HSYNC's case) for
verification. The algorithm is:

1. **Receiver** (the peer with the old version) computes block signatures
   (weak + strong hash) of its local file and sends them to the sender.
2. **Sender** (the peer with the new version) scans its file with a rolling
   window, matching against the signatures. Unmatched regions become literal
   data; matched regions become copy operations (offset + length).
3. **Receiver** applies the delta instructions (copy/data ops) to reconstruct
   the new file from the old base + literal data.

This approach has three key properties that make it ideal for HSYNC:

- **Client-side computation**: the server/master only stores signatures and
  serves literal data; no special server-side logic or storage.
- **Transparent fallback**: if delta transfer fails at any step (hash mismatch,
  network error, peer doesn't support delta), the client falls back to a full
  transfer. The user never has to choose manually.
- **Protocol compatibility**: delta transfer is an **optional capability**
  negotiated via the existing capability system ([ADR-0005](0005-protocol-versioning.md)). Older peers that
  don't support delta continue to work with full transfers.

## Decision

We will implement **rsync-style delta transfer** as an optional optimization for
large files with small changes. The implementation spans all five repositories
(`hsync-common`, `hsync-server`, `hsync-client`, `hsync-android`, `hsync-desktop`)
and integrates transparently into the existing sync engine.

### Core algorithm

The delta engine lives in `hsync_common.delta` and provides:

- **`compute_signatures(file, block_size)`**: computes Adler32 (weak) + SHA-256
  (strong) signatures for every block of the file. Block size is adaptive:
  4 KB for files < 1 MB, 16 KB for 1–10 MB, 64 KB for 10–100 MB, 256 KB for
  > 100 MB.
- **`find_matches(new_file, signatures, block_size)`**: scans the new file with
  a rolling Adler32 window, matching against the signatures. Returns a list of
  **delta operations**: `copy(offset, length)` for matched blocks, `data(literal)`
  for unmatched regions.
- **`apply_delta(base_file, ops, literal_data, output_file)`**: reconstructs the
  new file by executing the copy/data operations against the base file + literal
  data.

### Wire protocol

Four new REST endpoints under `/api/v1/buckets/{bucket}/files/delta/`:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/delta/signatures` | GET | Receiver fetches block signatures of the server's base file (upload delta) |
| `/delta/signatures` | POST | Receiver sends its block signatures; server returns delta instructions + data URL (download delta) |
| `/delta/apply` | POST | Receiver uploads literal data + metadata; server rebuilds the file (upload delta) |
| `/delta/data/{token}` | GET | Receiver downloads the literal payload parked by the server (download delta) |

The `data_url` is a **single-use, time-limited token** (TTL 300 s) that points
to a temporary file on the server. This avoids holding large literal payloads in
memory and allows the server to stream the data efficiently.

### Capability negotiation

Delta transfer is advertised as a **capability token** (`delta`) in the REST
handshake ([ADR-0005](0005-protocol-versioning.md)) and as a **TXT record key** (`delta=true`) in p2p mDNS
rendezvous. Peers only attempt delta transfer when **both** sides support it.

### Size thresholds

Delta transfer is only attempted for files above a minimum size:

- **Server mode**: ≥ 256 KB (`DELTA_MIN_FILE_SIZE`)
- **p2p mode**: ≥ 1 MB (`DELTA_MIN_FILE_SIZE_P2P`)

Below these thresholds, the overhead of computing signatures and matching blocks
outweighs the bandwidth savings. The thresholds are configurable via environment
variables (`HSYNC_DELTA_MIN_FILE_SIZE`, `HSYNC_DELTA_MIN_FILE_SIZE_P2P`).

### Fallback behavior

Delta transfer failures are **transparent**: if any step fails (network error,
hash mismatch, base file changed mid-transfer, peer doesn't support delta), the
client falls back to a full file transfer. The retry policy is unchanged — delta
failures do not consume retry attempts.

### Base hash tracking

Delta transfer requires a **recorded base hash** in the per-folder state DB
(ADR-0025). The base hash is recorded after every successful
sync (download or upload) and is used to determine whether delta transfer is
applicable:

- **Upload delta**: local file changed (`local_sha256 != base_hash`)
- **Download delta**: local file is still the base (`local_sha256 == base_hash`)
  and remote file changed (`remote_sha256 != base_hash`)

If no base hash exists (first sync, or the folder UUID has no recorded
version), delta transfer is skipped and a full transfer is performed.

### Concurrency

The server's delta apply endpoint uses a **per-file lock** to serialize
concurrent delta applies on the same file. This prevents race conditions where
multiple clients would write to the same `.delta.part` file simultaneously.

## Consequences

### Benefits

- **Bandwidth savings**: delta transfer can reduce transfer size by 90%+ for
  files with small changes (e.g. a 100 MB video with a 1 MB edit transfers only
  ~1 MB instead of 100 MB).
- **Faster sync**: smaller transfers complete faster, reducing the window for
  conflicts and improving user experience.
- **Cost reduction**: on cloud-hosted servers with egress billing, delta
  transfer directly reduces operational cost.
- **Transparent**: users never have to choose between delta and full transfer;
  the system automatically selects the optimal strategy based on file size,
  change ratio, and peer capabilities.
- **Backward compatible**: older peers that don't support delta continue to work
  with full transfers. The capability negotiation ensures delta is only used when
  both sides support it.

### Costs and limits

- **CPU overhead**: computing block signatures and matching blocks adds CPU cost
  on the client side. For most files this is negligible compared to network I/O,
  but for very large files (multi-GB) the CPU cost can become noticeable on
  low-power devices (e.g. Raspberry Pi, NAS).
- **Memory usage**: block signatures are held in memory during the matching
  phase. For a 1 GB file with 256 KB blocks, this is ~16 MB of signatures
  (16 bytes per block: 4 bytes Adler32 + 12 bytes SHA-256 prefix). This is
  acceptable for most use cases but could be a concern on memory-constrained
  devices.
- **Complexity**: delta transfer adds significant complexity to the sync engine,
  the server endpoints, and the Android implementation. The code is well-tested
  (459 unit tests on Android, 561 on the server, 1194 on the client) but the
  increased surface area raises the maintenance burden.
- **First sync always full**: delta transfer requires a recorded base hash, so
  the first sync of a file (or after the recorded base is lost) always performs
  a full transfer. Subsequent syncs can use delta if the file changed
  incrementally.
- **Not suitable for completely different files**: if a file is completely
  rewritten (e.g. a new video replacing an old one), delta transfer provides no
  benefit and may even be slower than a full transfer due to the signature
  computation overhead. The worthwhileness gate (50% change ratio) detects this
  and falls back to full transfer.

### Follow-up obligations

- **Metrics**: Prometheus metrics for delta transfer success/failure rates,
  bytes saved, and transfer duration should be added to the server (see
  `hsync-server/docs/operations.md`).
- **Documentation**: user-facing documentation should explain delta transfer,
  its benefits, and the configuration options (see `hsync-client/docs/sync-flow.md`,
  `hsync-client/docs/configuration.md`, `hsync-client/docs/p2p-internals.md`).
- **Monitoring**: the `[DELTA]` log label should be documented in the log-legend
  so users can identify delta transfers in the logs.
- **Testing**: cross-language parity tests should verify that the Python and
  Kotlin implementations produce identical results for the same inputs (see
  `hsync-android/app/src/test/java/com/hsync/android/util/DeltaEngineTest.kt`).

### Interaction with content-addressed storage ([ADR-0007](0007-content-addressed-storage.md))

After a delta apply on the server (upload delta), the newly reconstructed file is
treated as a normal upload:

1. The server computes SHA-256 of the reconstructed file.
2. The content hash is stored in the in-memory cache (`FILE_HASHES`, keyed by
   `SHA256(filepath)`), enabling future idempotent-upload detection.
3. The file replaces any existing content at the target path via `os.replace()`.
4. Deduplication via hard links (when two different paths share the same content
   hash) is a server-side optimisation governed by [ADR-0007](0007-content-addressed-storage.md)
   and is transparent to the delta transfer layer.

## References

- [ADR-0005](0005-protocol-versioning.md) — Protocol Versioning & Capability Negotiation
- [ADR-0007](0007-content-addressed-storage.md) — Content-Addressed Storage
- [ADR-0009](0009-rest-websocket-transport.md) — REST/WebSocket Transport
- rsync algorithm: Tridgell, A. & Mackerras, P. (1996). "The rsync algorithm."
  *Australian Computer Science Communication*, 18(1), 101-106.
- Implementation: `hsync_common/delta/` in `hsync-common/hsync_common/delta/`
- Server endpoints: `hsync_server/api/files/delta/` in `hsync-server/hsync_server/api/files/delta/`
- Client integration: `hsync_client/delta_transfer.py` in `hsync-client/hsync_client/delta_transfer.py`
- Android implementation: `com.hsync.android.util.DeltaEngine` in `hsync-android/app/src/main/java/com/hsync/android/util/DeltaEngine.kt`
