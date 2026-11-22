# ADR 0053 — A compressed p2p serve is streamed and unbounded

- **Status:** Accepted
- **Date:** 2026-11-23

## Context

A p2p client downloads a file either byte-addressed (resume, `Range`) or as a
`Content-Encoding: zstd` body. The compressed branch was built by staging the
whole frame first: the master compressed the file into a temporary file, learned
its length, and only then sent the headers with a `Content-Length`. Staging costs
a copy of the payload on disk and ties the branch to a size worth staging, so both
masters capped it — 256 MiB in the Python client, and the Android master staged the
frame in its cache directory — leaving larger compressible files to travel
uncompressed on the very link compression exists for.

## Decision

We will produce the frame into the response instead of staging it: a chunked body
(`Transfer-Encoding: chunked`, no `Content-Length`) written while the source is
read, through a compressor that is flushed at the end of the stream. Consequences
that define the contract:

- A compressed response and a byte-addressed response are mutually exclusive. A
  request carrying `Range` is answered with `200`/`206` raw bytes and
  `Accept-Ranges: bytes`; a compressed answer never carries `Accept-Ranges`.
- No size cap: the branch accepts any file, because memory is one read chunk and
  no temporary copy is written.
- The serving side reports progress against the **file** (the source bytes read),
  the same scale the receiver measures; there is no wire total to report.
- A body aborted mid-stream (the file changed under the serve) ends the connection
  without a terminal chunk, so the receiver rejects it on the checksum.

## Consequences

- Large compressible files are compressed on the LAN, and compression no longer
  needs disk headroom on either side.
- A compressed download cannot be resumed byte-wise; a resume falls back to the
  raw path for the remainder, which is exactly what an interrupted transfer does.
- Any future change that reintroduces `Content-Length` on the compressed branch
  reintroduces the size cap with it; `hsync-client/tests/test_p2p_server_compression.py`
  pins the chunked shape, and the Kotlin master (`hsync-android/.../P2PServer.kt`)
  streams the same way.
