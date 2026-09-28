# ADR 0034 — Bootnode TLS trust: fingerprint pinning and opt-in TOFU

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

The `boot/1` bootstrap node (ADR-0032) serves QUIC/TLS 1.3 (ALPN `hsync-boot/1`)
with a self-signed certificate. The client
(`hsync-client/hsync_client/boot_client.py`) therefore cannot authenticate the
node: aioquic verifies hostname + chain + dates against the dialed host, but the
bootnode's SAN is a fixed `hsync-bootnode` DNS name (or the bind IP) and its cert
is not in any trust store, so the client authenticates the node by pinning the
certificate fingerprint (ADR-0035) rather than through WebPKI; `--ca-cert` cannot
work (a self-signed leaf is not a CA, and its fixed SAN does not match a dialed
hostname).

The trust gap is security-relevant, not cosmetic: the `bucket_token`
(`HMAC-SHA256(HSYNC_P2P_KEY, "boot/1" || bucket)`) travels inside `register` and
`query` frames, so a MITM or DNS-spoofed bootnode could learn a secret derived
from the p2p key before the client ever verifies who it is talking to. Trust must
therefore be established **before any frame is written**.

Three design constraints shape the solution:

- **No-log invariant.** The bootnode never writes peer data (IPs, CIDs,
  timestamps) to disk; its only on-disk artifact is its own long-lived TLS
  key+cert (`hsync-bootnode/AGENTS.md`, `llm-wiki/README.md`) — the same posture
  as an SSH host key. Peer-facing state (the routing table) stays in RAM.
- **Identity key type.** The identity is **ECDSA P-256** (ADR-0037): BoringSSL
  (used by Android's `quiche` client) disables Ed25519 in its default client
  signature algorithms, so an Ed25519 bootnode cannot complete a TLS 1.3
  handshake with it, while ECDSA P-256 is universally advertised.
- **Zero backward compatibility.** No shims or legacy modes; a changed contract is
  changed everywhere atomically. There are no production deployments yet.

## Decision

We will add a self-hosted trust tier to the `boot/1` channel, with a single
fingerprint domain shared with the existing `cert_fp` carried in frames.

1. **Fingerprint = SHA-256 of the leaf certificate DER**, lowercase hex, canonical
   form `sha256:<hex>`. No wire change (`PROTOCOL_VERSION_BOOT` unchanged): the
   fingerprint is published out of band (`identity show`, the startup banner, the
   service units).
2. **Client trust matrix, in precedence order:**
   - `--insecure` — tests/loopback only; mutually exclusive with pin/TOFU (hard
     error) and logged with a loud warning (not hard-blocked by host, since
     DNS-based loopback detection is unreliable);
   - explicit pin `--bootnode-fingerprint` (repeatable, up to two for rotation);
   - opt-in TOFU `--bootnode-tofu` (dedicated store, hard refusal on mismatch);
   - default policy **`ask`** (ADR-0035): prompt on an unknown node, pin on
     acceptance; a non-interactive caller fails closed. The certificate is
     verified against the pinned fingerprint with `verify_mode=CERT_NONE` (the pin
     is the trust anchor), not against the system CA store.
3. **The check runs post-handshake and before `create_stream()`**, so a mismatch
   closes the connection with zero application bytes sent. In pin/TOFU modes
   `verify_mode = CERT_NONE` (trust comes from the pin). The peer certificate is
   read from aioquic's private `tls._peer_certificate`, isolated in one helper.
4. **The node identity persists by default.** The node keeps a long-lived
   self-signed ECDSA P-256 key+cert (`0600` in a `0700` directory) at a state
   path, created on first start and reused afterwards, so the fingerprint is
   stable across restarts and can be pinned; `identity rotate` regenerates it.
   `--ephemeral` opts out into a per-process in-memory identity for read-only
   filesystems or throwaway nodes. The shared service-identity model — key type,
   key-at-rest and validity — is ADR-0037.
5. **`--ca-cert`/`HSYNC_CA_CERT` do not affect the bootnode path** and are
   refused in `hsync p2p` (they keep their server-mode meaning). An external-CA /
   WebPKI tier is out of scope.
6. **Rotation uses a single stored pin**: the TOFU store keeps only `current`; the
   transition is a documented window in which the client runs with two
   `--bootnode-fingerprint` values, and the store records whichever matched.

The pure trust primitives (`parse_fingerprint`, `fingerprint_matches`,
`FingerprintMismatch`) live in `hsync_common.protocol.pairing`, the existing
pin-decision single source of truth, so the Python client and future Rust/Android
ports share one fingerprint contract instead of each re-implementing it.

## Consequences

- A bootnode is authenticated before any `register`/`query` frame is sent, closing
  the `bucket_token` exposure. A fingerprint mismatch is fatal and is not retried
  by the client lease loop.
- The client authenticates the node with the SSH-like `ask` policy by default
  (ADR-0035): it confirms an unknown fingerprint at a terminal prompt and fails
  closed without one, so an operator always has an explicit, documented way to
  pin. Because the node identity persists by default, that pin stays valid across
  restarts.
- The no-log invariant is preserved: the daemon writes no peer data to disk; its
  only on-disk artifact is its own key+cert, kept by default and replaced with an
  in-memory identity under `--ephemeral`. `hsync-bootnode` documentation and the
  man page carry the `identity`/`--public-host`/`--ephemeral` surface.
- Follow-up obligations: the boot/1 spec gains a "Trust & identity" section; the
  golden fingerprint scenarios (`hsync-bootnode/fixtures/bootnode-fingerprint.json`)
  are replayed by a language-neutral parity test; a future external-CA/WebPKI tier
  and the Rust/Android ports reuse the same fingerprint format.
