# ADR 0011 — Resumable uploads with atomic commit

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

Uploading large files over potentially unstable connections (mobile, Wi-Fi)
requires resilience to interruption. Without resume support, a connection drop
at 95% progress forces a full re-upload — wasting bandwidth and battery.
HSYNC targets mobile clients (Android) and unreliable home networks, so
resumable upload is a hard requirement.

Options:

- **Tus protocol** — an open standard for resumable uploads over HTTP with
  `Upload-Offset` and `PATCH`. Well-designed but adds a separate protocol
  layer and is overkill for a single-server deployment.
- **Custom `Content-Range` + temp files** — use standard HTTP `Content-Range`
  header to resume partial uploads, write to a temporary file, and atomically
  rename on completion. Simpler, uses existing HTTP infrastructure.
- **Chunked upload with separate endpoint** — split into chunks, upload each,
  then a final "assemble" call. Adds state management and an extra endpoint.

## Decision

We will support **resumable uploads via `Content-Range` with atomic file rename**,
implemented in `api/files/upload.py`:

- The client sends `Content-Range: bytes X-Y/Z` to resume from offset X.
- The server writes to a **temporary file** (`{filename}.partial`) in the
  bucket directory, appending to it if it already exists (resume).
- On receiving the final chunk (range end ≥ file size), the server computes
  SHA-256, verifies it matches the client-provided checksum, and **atomically
  renames** `.partial` → final filename via `os.replace()`.
- If the checksum doesn't match, the `.partial` file is deleted and the client
  must restart.
- The server enforces a maximum upload size (`HSYNC_MAX_UPLOAD_SIZE`,
  default 10 GB) and minimum free disk space (`HSYNC_MIN_FREE_DISK_SPACE`)
  before accepting any upload.

Alternatives rejected:

- **Tus protocol**: well-designed but adds a separate protocol with its own
  state machine, extension negotiation, and server-side metadata storage.
  HSYNC's needs are simpler.
- **Chunked upload with assemble step**: adds client state (which chunks are
  done), server state (assembling chunks), and an extra API call. More failure
  modes for no benefit over a single resumable stream.
- **No resume support**: unacceptable for mobile clients and large files.

## Consequences

- **Resume is transparent to the HTTP layer** — standard `Content-Range` header,
  no new endpoints or protocols.
- **`.partial` files are cleanup responsibility** — interrupted uploads leave
  orphaned `.partial` files. The server does not garbage-collect them
  automatically (they serve as resume state). A manual cleanup or future GC
  policy may be added.
- **Atomic rename guarantees consistency** — clients never see a partially
  written file; it either appears complete or not at all.
- **Checksum verification is the integrity gate** — the server trusts the
  client-provided SHA-256, computes its own, and rejects on mismatch. This
  catches both transmission errors and malicious uploads.

## See also

- [hsync_server/api/files/upload.py](https://github.com/albertobasso/hsync-server/blob/main/hsync_server/api/files/upload.py) —
  implementation.
- [ADR-0007](0007-content-addressed-storage.md) — SHA-256 hashing for
  deduplication.
