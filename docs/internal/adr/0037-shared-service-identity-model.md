# ADR 0037 — Shared self-signed service identity model

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

Three HSYNC components own a long-lived, self-signed **service identity**: the
`boot/1` bootstrap node (its QUIC/TLS node key, ADR-0034), the sync server (its
HTTPS/WSS certificate), and the P2P master (its LAN/WSS certificate, ADR-0020).
All three are authenticated by **pinning the certificate fingerprint** — the SSH
`known_hosts` model (ADR-0035/0036) — not through WebPKI: the certificates are
self-signed, their SANs are a bind address or a fixed name, and they are in no
public or system trust store.

Because the fingerprint is the trust anchor, the identity must be **stable and
rotatable**, and its key material is the operator's own secret (never peer data).
A single model is needed so the three components cannot diverge on key type,
key-at-rest or validity.

## Decision

We will give every self-signed **service identity** in HSYNC one shared model,
implemented in `hsync_common/ssl_utils.py` (the SSOT) and reused by every
consumer.

1. **Key type: ECDSA P-256.** It is advertised by every mainstream TLS stack
   (BoringSSL/OpenSSL/rustls); BoringSSL (Android's `quiche` client) omits
   Ed25519 from its default client signature algorithms, so an Ed25519 identity
   cannot complete a TLS 1.3 handshake with Android. Service identities are
   ECDSA P-256.
2. **Key at rest: unencrypted PKCS#8, permission-guarded.** The private key is
   written **unencrypted** as PKCS#8, `0600` inside a `0700` directory — the
   established model for SSH host keys and Syncthing device keys. Confidentiality
   comes from filesystem permissions, not a passphrase, because identity is
   established by fingerprint pinning rather than by an encrypted-at-rest secret;
   a co-located passphrase would only add a secret to manage and leak.
3. **Validity: 20 years, backdated one day.** `SERVICE_CERT_VALIDITY_DAYS`
   (7305) bounds the certificate to the lifetime of the deployment. The 825-day
   Apple/CA-Browser-Forum cap applies only to certificates that must be accepted
   by a browser/OS trust store, which these are not; Syncthing hardcodes 20 years
   for exactly this pinned-identity case. `NotBefore` is backdated by one day so a
   freshly generated certificate is still valid on a peer whose clock lags.
4. **Rotation and expiry are explicit.** Each component can regenerate its
   identity and print the new fingerprint (`hsync-bootnode identity rotate`,
   `hsync-server admin tls rotate`; the P2P master rotates by deleting its
   keypair and keeping the device ID); rotation is announced out of band and
   clients accept two pins during the window (ADR-0035/0036). Startup warns when
   a persisted certificate is near or past expiry.
5. **Persistence is the default; ephemeral is the opt-out.** A service identity
   is kept on disk (created on first run, reused afterwards) so its fingerprint
   is stable and pin-able across restarts; `hsync-bootnode run --ephemeral`
   keeps the identity in memory for read-only filesystems or throwaway nodes
   (ADR-0034).

## Consequences

- The bootnode node key, the server TLS certificate and the P2P master
  certificate are generated, stored, validated and rotated identically, so
  operators learn one procedure and the documentation stays consistent across
  the repositories.
- A pinned identity survives for the lifetime of the deployment without silent
  expiry; the cost accepted is that a leaked key must be rotated explicitly (no
  short-validity auto-recovery), which the pin-rotation window and the `rotate`
  commands cover.
- The shared model lives only in `hsync_common.ssl_utils`; consumers
  (`hsync-bootnode`, `hsync-server`, `hsync-client`) reuse it rather than
  re-declaring key type, file permissions or validity.
