# ADR 0009 — REST for data, WebSocket for events

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

The server needs to support two distinct communication patterns:

- **File transfer** (upload, download, list, delete): request-response, benefits
  from HTTP features like `Content-Range` for resumable uploads, `Content-Type`
  negotiation, and caching headers.
- **Real-time events** (file added/modified/deleted on another peer): push-based,
  low-latency, bidirectional, where the server must fan-out notifications to all
  connected clients for a bucket.

A single transport could theoretically handle both, but each has different
requirements. Options:

- **Pure WebSocket** — multiplex file transfers and events over one WS
  connection. Works, but loses HTTP caching, range requests, and tooling
  (curl, load balancers). Streaming large files over WS frames is less
  efficient than HTTP chunked transfer.
- **gRPC** — strong typing, bidirectional streaming, HTTP/2 multiplexing.
  Requires protobuf toolchain on every client (including Android), and is
  harder to debug with standard tools.
- **Server-Sent Events (SSE)** — unidirectional server→client push over HTTP.
  No client→server channel, so events initiated by a client (e.g. "I uploaded
  a file") would still need REST calls — two channels anyway.
- **REST + WebSocket** — HTTP/REST for file operations, WebSocket for real-time
  event fan-out. Standard, well-understood, debuggable with curl/wscat.

## Decision

We will use **REST for data operations and WebSocket for real-time events**,
as separate channels:

- **REST endpoints** (`/api/v1/buckets/{bucket}/files/...`) handle upload,
  download, list, delete. They benefit from HTTP caching (`ETag`/`If-None-Match`
  for downloads), range requests (`Content-Range` for resumable upload), and
  standard monitoring (status codes, middleware).
- **WebSocket** (`/api/v1/buckets/{bucket}/events/{cid}`) is used exclusively
  for real-time event broadcasting: when client A uploads a file, the server
  pushes a `file_added` event to clients B and C via their open WebSocket
  connections.
- The WebSocket connection is **authenticated** (first message is a JSON `auth`
  frame with the API key) and **per-bucket** (one WS per bucket per client).
- The REST API is versioned (`api/v1`) and the WebSocket uses the protocol
  versioning from [ADR-0005](0005-protocol-versioning.md).
  The `v1` in the URL prefix `/api/v1/` corresponds to
  `PROTOCOL_VERSION_REST = "api/1"` ([ADR-0005](0005-protocol-versioning.md)).
  A bump to `"api/2"` would introduce `/api/v2/` endpoints; the old `/api/v1/`
  would remain available during a deprecation window, after which it would be
  removed in a clean breaking change.

Alternatives rejected:

- **Pure WebSocket**: loses HTTP caching, content negotiation, standard load
  balancer support, and the ability to use tools like `curl` for testing.
- **gRPC**: adds build complexity (protobuf compilation for Python + Kotlin),
  harder debugging, and is overengineered for a single-server deployment.
- **SSE**: only solves half the problem (server→client); still needs REST for
  uploads, resulting in two channels with an asymmetric, less capable push
  channel.

## Consequences

- **Two connections per client**: one HTTP pool for REST calls + one persistent
  WebSocket. This is standard and well-supported by all HTTP libraries and
  proxies.
- **WebSocket reconnection**: clients must handle disconnects and re-establish
  the WS with a full re-auth. The reconnection strategy is client-side only.
- **No request multiplexing** — each REST call is a separate HTTP request.
  Acceptable because file operations are infrequent relative to event traffic.
- **Debugging is straightforward**: `curl` for REST, `wscat` for WebSocket, no
  special tooling needed.

## See also

- [ADR-0005](0005-protocol-versioning.md) — protocol versioning for both REST
  and WebSocket channels.
- [ADR-0001](0001-server-vs-lan-modes.md) — LAN mode also uses REST+WS between
  peers.
