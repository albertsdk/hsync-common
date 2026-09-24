# ADR 0007 — SHA-256 integrity verification and idempotent upload

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

The server must store uploaded files, verify their integrity, and serve them
back by path to clients. The natural options for the storage backend are:

- **Database blob storage** — files as BLOB rows with metadata columns (path,
  size, mtime); rich querying, but the DB becomes a bottleneck for large files
  and complicates streaming/range requests.
- **Object storage (S3, MinIO)** — adds an external dependency, and HSYNC's
  target is self-contained deployment on a single machine.
- **Flat filesystem mirroring the client's path tree** — each upload lands at
  its logical bucket-relative path, verified by SHA-256. No indirection.

HSYNC already computes SHA-256 for every file (integrity verification), so the
hash is available at no extra cost.

## Decision

We will store file content on disk using a **flat filesystem tree mirroring the
client's path structure**, with SHA-256 integrity verification and idempotent
upload:

- Each bucket has a directory tree mirroring the client's path structure.
- The server maintains an **in-memory SHA-256 cache** (`FILE_HASHES` in
  `hashes.py`) mapping `SHA256(filepath) → SHA256(content)` — the filepath is
  hashed for privacy, not stored in plaintext.
- **Integrity verification**: every upload is SHA-256 verified before the temp
  file is atomically renamed to its final location. A checksum mismatch
  rejects the upload (400).
- **Idempotent upload**: if a file already exists at the target path AND its
  stored SHA-256 matches the new upload, the server returns `409 Conflict`
  and skips the transfer — no data is rewritten. This protects against
  accidental re-uploads of unchanged content.
- **No deduplication across paths**: each file path is an independent artifact
  reflecting the exact state of the client that uploaded it. Hard links and
  content-addressed storage are explicitly rejected (see below).

### Why not hard-link deduplication?

Content-addressed deduplication via hard links is rejected because:

1. **Sync fidelity over storage efficiency**: HSYNC's core guarantee is that
   every client converges to the same file tree. If two clients independently
   upload the same content to different paths, those are two distinct files in
   the logical bucket — sharing disk blocks via hard links would couple their
   lifecycles in ways invisible to clients (e.g. a `chmod` on one path would
   affect the other).

2. **Unnecessary for the target scale**: HSYNC is designed for single-user /
   small-family deployments (a few devices, not thousands). The disk savings
   from deduplication are negligible at this scale and do not justify the
   added complexity.

3. **`os.replace()` breaks hard links anyway**: the upload flow writes to a
   temp file and then calls `os.replace(tmp, final_path)`, which atomically
   replaces the directory entry. Even if a hard link existed, the replace
   would break it — so deduplication would require a fundamentally different
   (and more complex) write path.

Alternatives rejected:

- **Database BLOBs**: adds schema complexity, complicates streaming, and forces
  a DB dependency for a workload that is fundamentally filesystem-bound.
- **Object storage**: external service dependency contradicts the self-contained
  deployment goal.
- **Content-addressed flat store (hash-named files + index DB)**: the extra
  indirection is unnecessary when the path tree is already the index clients
  expect, and hard links couple independent files.

## Consequences

- **Integrity is mandatory**: no file is ever committed to the storage tree
  without passing SHA-256 verification. Transmission errors and tampered
  uploads are detected before they affect any client.
- **Idempotence prevents wasted transfers**: re-syncing an unchanged file
  consumes no disk I/O beyond the initial hash lookup.
- **The in-memory cache is volatile**: on server restart it is rebuilt by
  scanning the filesystem (acceptable for the target single-server scale).
- **No cross-path deduplication**: if two clients upload the same content to
  different paths, two independent copies exist on disk. This is the intended
  behaviour — the server reflects the clients' file trees exactly.
- No rich metadata querying (e.g. "find all files larger than X") — in exchange
  for simplicity. If needed later, an index can be layered on top.

## See also

- [ADR-0022](0022-causal-vector-clock-conflict-model.md) — the conflict model
  also relies on SHA-256 hashes.
- [ADR-0003](0003-tombstone-gossip.md) — tombstone keys are also SHA-256 hashed
  for privacy.
- [ADR-0011](0011-resumable-upload.md) — resumable upload also uses SHA-256
  verification before atomic rename.
