# ADR 0053 — A compressed file serve is streamed and unbounded

- **Status:** Accepted
- **Date:** 2026-11-23

## Context

A client downloads a file either byte-addressed (resume, `Range`) or as a
`Content-Encoding: zstd` body, over both transports: the p2p master's serve and
the central server's `GET …/files/download`. Staging the whole zstd frame first
to learn its length costs a copy of the payload on disk and ties the compressed
branch to a size worth staging, leaving larger compressible files to travel
uncompressed on the very link compression exists for.

## Decision

Produce the frame into the response instead of staging it: a chunked body
(`Transfer-Encoding: chunked`, no `Content-Length`) written while the source is
read, through a compressor flushed at the end of the stream. The contract, for
both transports:

- A compressed response and a byte-addressed response are mutually exclusive. A
  request carrying `Range` is answered with `200`/`206` raw bytes and
  `Accept-Ranges: bytes`; a compressed answer never carries `Accept-Ranges`.
- No size cap: the branch accepts any file, because memory is one read chunk and
  no temporary copy is written.
- The wire carries no *compressed* total. The **uncompressed** size is sent as
  `X-Uncompressed-Size`, so any client can size progress/pre-allocation without
  reading the listing; progress itself is measured against the source bytes, the
  same scale the receiver measures.
- A body aborted mid-stream (the file changed under the serve) ends the
  connection without a terminal chunk, so the receiver rejects it on the checksum.

## Consequences

- Large compressible files are compressed on the LAN and on the server, and
  compression needs no disk headroom on either side.
- A compressed download cannot be resumed byte-wise; a resume falls back to the
  raw path for the remainder, which is exactly what an interrupted transfer does.
  The client writes the decoded body to its `.part`, so the raw resume offset is
  the decoded prefix and stays exact.
- `hsync-client/tests/test_p2p_server_compression.py` pins the chunked p2p shape;
  `hsync-server/tests/test_api_files_crud.py::test_download_compressed_streaming`
  pins the server `X-Uncompressed-Size` header and the identity-on-`Range` path.
