# ADR 0033 — The rendezvous Python v1 reuses hsync-common utilities

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

[ADR-0032](0032-rdv-protocol.md) defines the `rdv/1` rendezvous protocol
and keeps the daemon's wire contract standalone and portable to C. The Python
v1 nevertheless declares `hsync-common==1.0.0` as a main dependency
(`hsync-rendezvous/python/pyproject.toml`) and imports `hsync_common.ssl_utils` in
`server.py` to generate its per-process TLS identity.

Two shared contracts must be identical on both sides of the wire:

- the CID shape `^[A-Za-z0-9]{21}$`;
- the `bucket` field domain. The client mirror
  (`hsync_common.protocol.rendezvous`, backed by
  `hsync_common.path_validation.is_valid_bucket_name`) enforces the canonical
  bucket-name rule; if the daemon accepted any 1–128-character string, a peer
  registering a non-canonical bucket would produce `query` responses the client
  could not parse.

## Decision

We will let the rendezvous's Python v1 reuse **generic** `hsync-common` utilities,
while the `rdv/1` wire contract itself stays canonical in `hsync-rendezvous`:

- `hsync_common.ssl_utils` for the TLS identity;
- `hsync_common.models.event.CID_PATTERN` for the CID shape;
- `hsync_common.path_validation.is_valid_bucket_name` for the wire `bucket`
  domain (the canonical bucket name shared by client, server and desktop).

The daemon keeps its own `rdv/1` frame models and never imports the
`hsync_common.protocol.rendezvous` mirror; `protocol-spec/rdv-1.md` and the golden
fixtures remain the cross-language SSOT, and the C port may reimplement the
same rules without any Python dependency.

## Consequences

- The Python implementation keeps its single dependency on `hsync-common`
  (already present) and does not duplicate the CID shape or the bucket-name
  rule; the accepted and rejected buckets are identically defined on both sides.
- The `rdv/1` wire shape is unchanged: only values outside the canonical bucket
  rule — which a conforming client never sends — are invalid, so no
  `protocol_version` bump is required. `protocol-spec/rdv-1.md` states the
  bucket domain explicitly.
- [ADR-0032](0032-rdv-protocol.md) governs the `rdv/1` contract and the
  portability goal; this record governs which `hsync-common` utilities the
  Python daemon reuses.
- Follow-up obligation: any further shared constant or validator the daemon needs
  is imported from `hsync-common` (pinned to the spec by a drift test), never
  re-declared locally. The C port mirrors the spec and fixtures only.
