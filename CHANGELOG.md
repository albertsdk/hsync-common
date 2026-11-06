# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The `rdv/1` rendezvous channel is transport-neutral in the shared code:
  `RDV_TRANSPORTS`, `RDV_TRANSPORT_DEFAULT`, `RDV_TRANSPORT_STAGGER_S` and
  `RDV_TCP_FALLBACK_TTL_S` name the QUIC/UDP and TLS/TCP options, and
  `hsync_common.tls_context` provides the certificate-free client TLS context
  without pulling `cryptography` into the CLI startup path.
- The `X-Client-Id` request header constant (`HEADER_CLIENT_ID`), carrying the
  requester CID so the P2P master can bucket relayed peers (which all arrive
  from the loopback address) by identity.

### Changed

- The master election prefers a node that confirms an externally dialable
  endpoint (`inbound`); the mDNS TXT schema and the `rdv/1` register/peer
  mirrors carry it, and a reachable node out-ranks a relay-only one.
- The data-relay docs (ADR-0047, `rdv-protocol.md`) state that the peers
  multiplex their loopback connections inside the opaque relay stream, which the
  node never parses.

### Fixed

- The wiki anchor checker accepts a `file.py::Class.attribute` anchor that
  points at a bare annotated declaration (`_link_down: bool`) or at a
  `self.x = ...` assignment instead of reporting it as a broken anchor.
