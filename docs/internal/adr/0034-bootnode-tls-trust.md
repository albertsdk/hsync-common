# ADR 0034 — Bootnode TLS trust: fingerprint pinning and opt-in TOFU

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

The `boot/1` bootstrap node (ADR-0032) serves QUIC/TLS 1.3 (ALPN `hsync-boot/1`)
with a self-signed certificate that is regenerated in memory on every start
(`hsync-bootnode/python/src/hsync_bootnode/server.py`). The client
(`hsync-client/hsync_client/boot_client.py`) therefore cannot authenticate the
node: aioquic verifies hostname + chain + dates against the dialed host, but the
bootnode's SAN is a fixed `hsync-bootnode` DNS name (or the bind IP) and its cert
is not in any trust store, so the client authenticates the node by pinning the
certificate fingerprint (ADR-0035) rather than through WebPKI; `--ca-cert` cannot
work (the node never exports its PEM, and a fixed-SAN self-signed cert does not
match a dialed hostname).

The trust gap is security-relevant, not cosmetic: the `bucket_token`
(`HMAC-SHA256(HSYNC_P2P_KEY, "boot/1" || bucket)`) travels inside `register` and
`query` frames, so a MITM or DNS-spoofed bootnode could learn a secret derived
from the p2p key before the client ever verifies who it is talking to. Trust must
therefore be established **before any frame is written**.

Three design constraints shape the solution:

- **No-log invariant.** The bootnode is a zero-log daemon whose TLS identity is
  in-memory and regenerated per process (`hsync-bootnode/AGENTS.md`,
  `llm-wiki/README.md`). A long-lived on-disk key would change that posture.
- **Identity key type.** The identity is **ECDSA P-256**: BoringSSL (used by
  Android's `quiche` client) disables Ed25519 in its default client signature
  algorithms, so an Ed25519 bootnode cannot complete a TLS 1.3 handshake with it,
  while ECDSA P-256 is universally advertised. RSA/Ed25519 identities remain
  loadable, but new identities are ECDSA P-256.
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
4. **Identity persistence is opt-in.** The bootnode stays ephemeral by default
   (no-log invariant intact); `--identity PATH` persists an ECDSA P-256 key+cert
   (`0600` file / `0700` dir), and `identity rotate` regenerates it. The packaged
   service units pass `--identity`.
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
- The default client behaviour refuses an unpinned self-signed bootnode;
  operators have an explicit, documented way to pin. *(Superseded by
  [ADR-0035](0035-bootnode-trust-policy.md): the default is now the SSH-like
  `ask` policy, which confirms an unknown fingerprint at a terminal prompt and
  fails closed without one; `strict` keeps the behaviour described here.)*
- The no-log invariant is preserved: the daemon writes nothing to disk unless the
  operator opts into `--identity`. `hsync-bootnode` documentation and the man page
  gain the new `identity`/`--public-host` surface.
- Follow-up obligations: the boot/1 spec gains a "Trust & identity" section; the
  golden fingerprint scenarios (`hsync-bootnode/fixtures/bootnode-fingerprint.json`)
  are replayed by a language-neutral parity test; a future external-CA/WebPKI tier
  and the Rust/Android ports reuse the same fingerprint format.
