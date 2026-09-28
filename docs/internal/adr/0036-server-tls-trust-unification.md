# ADR 0036 — Unified SSH-style TLS trust for the sync server

- **Status:** Accepted
- **Date:** 2026-09-30

## Context

Three transports authenticate with a certificate whose fingerprint can be
pinned, under one shared model:

- the **P2P master** (self-signed, fingerprint shared over mDNS): TOFU pinning in
  `hsync_client/pinning.py`, managed with `hsync trust peer` — ADR-0020;
- the **`boot/1` bootnode** (self-signed by contract): the SSH-like policy in
  `hsync_common/protocol/tls_trust.py` and the `bootnode_known_hosts.json` store —
  ADR-0034/0035;
- the **sync server**: the same store/CLI/prompt/event model, with `--ca-cert`
  as the public-CA anchor and `--insecure` for tests.

The server case differs from the bootnode in one way: it may be fronted by a
reverse proxy with a **public-CA** certificate, so "pin on first sight" is not a
sensible default. It still benefits from the same store/CLI/prompt/event model
when the certificate is self-signed (a LAN deployment with the built-in TLS).

## Decision

1. **One policy SSOT** for all three transports:
   `hsync_common/protocol/tls_trust.py` gains **`chain`** (standard CA chain
   validation, no fingerprint pinning) alongside `ask`/`accept-new`/`strict`/
   `none`. `evaluate_tls_trust` treats `chain` and `none` as "proceed" (the caller
   applies or skips chain validation respectively) and never pins.
2. **`chain` is the server default.** Pin-based policies are opt-in; `--ca-cert`
   means `chain` with a custom anchor, `--insecure` means `none`.
3. **One durable store per host kind, one shared shape.** The bootnode and server
   stores are both `host:port` known-hosts maps (records `current`, `updated_at`,
   `first_seen`, `source`); they share a `KnownHostsStore` base. The server store
   is `server_known_hosts.json`, overridable with `HSYNC_SERVER_TRUST_FILE`.
4. **One CLI namespace.** Because `hsync server`/`hsync p2p` are actions (not
   groups), trust management lives under a top-level `hsync trust` namespace:
   `hsync trust peer|bootnode|server {list,show,add,remove,fingerprint}` (+
   `--json`).
5. **Same UX as the bootnode**: TOFU/prompt on connect, structured
   `pairing_needed`/`fingerprint_changed` events with `scope="server"`, SSH-style
   messages naming the exact `hsync trust server add|remove` commands, a
   desktop pre-flight + "Manage trusted keys" servers tab, and an Android
   policy/store mirror.
6. **The server can print its own fingerprint** with
   `hsync-server admin tls fingerprint` for the out-of-band step, and rotate its
   certificate with `hsync-server admin tls rotate`.

## Consequences

- The desktop and Android use the same policy + store, so all clients share one
  rule set and the shared `p2p-bootnode-trust-scenarios` fixture (including
  `chain`).
- A self-signed LAN server is pinned like a bootnode; a public-CA server keeps
  working with the default `chain` (no prompt).
- New flags/env oblige the man page, `docs/`, the WD OS5 packaging and the wiki
  to be updated atomically.
- `hsync trust` is the single, discoverable trust surface across all three
  transports; the P2P peer store keeps its `cid|bucket` shape and remains a
  `PinStore` (not a `KnownHostsStore`).
