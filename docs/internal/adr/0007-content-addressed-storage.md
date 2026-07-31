# ADR 0007 — SHA-256 content-addressed storage with flat filesystem

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

The server must store uploaded files, detect duplicates to avoid wasting disk
space, and serve them back by path to clients. The natural options are:

- **Database blob storage** — files as BLOB rows with metadata columns (path,
  size, mtime); rich querying, but the DB becomes a bottleneck for large files
  and complicates streaming/range requests.
- **Object storage (S3, MinIO)** — adds an external dependency, and HSYNC's
  target is self-contained deployment on a single machine.
- **Flat filesystem with content-addressed naming** — files stored by their
  SHA-256 hash; the path→hash mapping is maintained separately or derived from
  the filesystem tree.

HSYNC already computes SHA-256 for every file (integrity verification), so
content-addressing reuses existing computation rather than adding cost.

## Decision

We will store file content on disk using **content-addressed flat filesystem
storage** with SHA-256 deduplication:

- Each bucket has a directory tree mirroring the client's path structure.
- The server maintains an **in-memory SHA-256 cache** (`FILE_HASHES` in
  `hashes.py`) mapping `SHA256(filepath) → SHA256(content)` — the filepath is
  hashed for privacy, not stored in plaintext.
- Before writing a new upload, the server checks if the content hash already
  exists; if so, it creates a **hard link** instead of a second copy.
- File listing (`GET /files`) returns the logical path tree; content addressing
  is an internal optimisation invisible to clients.

Alternatives rejected:

- **Database BLOBs**: adds schema complexity, complicates streaming, and forces
  a DB dependency for a workload that is fundamentally filesystem-bound.
- **Object storage**: external service dependency contradicts the self-contained
  deployment goal.
- **Content-addressed flat store (hash-named files + index DB)**: the extra
  index is unnecessary when the path tree is already the index clients expect.

## Consequences

- Deduplication is **automatic and transparent** — identical files across
  different paths or buckets share disk blocks via hard links, with no client
  awareness needed.
- The in-memory cache is **volatile** — on server restart it is rebuilt by
  scanning the filesystem (acceptable for the target single-server scale).
- Hard links work only within the same filesystem; cross-volume buckets would
  require copying, but the single-volume deployment is the documented norm.
- No rich metadata querying (e.g. "find all files larger than X") — in exchange
  for simplicity. If needed later, an index can be layered on top.

## See also

- [ADR-0006](0006-master-authoritative-conflict-model.md) — the conflict model
  also relies on SHA-256 hashes.
- [ADR-0003](0003-tombstone-gossip.md) — tombstone keys are also SHA-256 hashed
  for privacy.
