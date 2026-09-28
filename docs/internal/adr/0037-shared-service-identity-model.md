# ADR 0037 — Shared self-signed service identity model

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

Two HSYNC components own a long-lived, self-signed **service identity**: the
`boot/1` bootstrap node (its QUIC/TLS node key, ADR-0034) and the sync server
(its HTTPS/WSS certificate). Both are authenticated by **pinning the certificate
fingerprint** — the SSH `known_hosts` model (ADR-0035/0036) — not through WebPKI:
the certificates are self-signed, their SANs are the bind address or a fixed
name, and they are in no public or system trust store.

Because the fingerprint is the trust anchor, the identity must be **stable and
rotatable**, and its key material is the operator's own secret (never peer data).
Three details had drifted between the two components:

- **Key type** — the bootnode used ECDSA P-256 (chosen for TLS-client
  interoperability, see below); the server generated RSA.
- **Key at rest** — the bootnode stored an unencrypted PKCS#8 key guarded by
  filesystem permissions (SSH host-key / Syncthing model); the server *required*
  an on-disk passphrase (`HSYNC_SSL_KEYFILE_PASSWORD`) and stored an encrypted
  key.
- **Validity** — both used 365 days with no expiry handling, even though a
  fingerprint-pinned identity has no reason to be as short-lived as a WebPKI
  leaf.

## Decision

We will give every self-signed **service identity** in HSYNC one shared model,
implemented in `hsync_common/ssl_utils.py` (the SSOT).

1. **Key type: ECDSA P-256.** It is advertised by every mainstream TLS stack
   (BoringSSL/OpenSSL/rustls); BoringSSL (Android's `quiche` client) omits
   Ed25519 from its default client signature algorithms, so an Ed25519 identity
   cannot complete a TLS 1.3 handshake with Android. Identities are ECDSA P-256;
   no other key type is generated or loaded.
2. **Key at rest: unencrypted PKCS#8, permission-guarded.** The private key is
   written **unencrypted** as PKCS#8, `0600` inside a `0700` directory — the
   established model for SSH host keys and Syncthing device keys. Confidentiality
   comes from filesystem permissions, not a passphrase, because identity is
   established by fingerprint pinning rather than by an encrypted-at-rest
   secret; a co-located passphrase would only add a secret to manage and leak.
   `HSYNC_SSL_KEYFILE_PASSWORD` and the encrypted-key helper
   (`serialize_key_pem`) are removed.
3. **Validity: 20 years, backdated one day.** `SERVICE_CERT_VALIDITY_DAYS`
   (7305) bounds the certificate to the lifetime of the deployment. The 825-day
   Apple/CA-Browser-Forum cap applies only to certificates that must be accepted
   by a browser/OS trust store, which these are not; Syncthing hardcodes 20 years
   for exactly this pinned-identity case. `NotBefore` is backdated by one day so a
   freshly generated certificate is still valid on a peer whose clock lags.
4. **Rotation and expiry are explicit.** Each component can regenerate its
   identity and print the new fingerprint (`hsync-bootnode identity rotate`,
   `hsync-server admin tls rotate`); rotation is announced out of band and clients
   accept two pins during the window (ADR-0035/0036). Startup warns when the
   persisted certificate is near or past expiry.
5. **Persistence is the default; ephemeral is the opt-out.** A service identity
   is kept on disk (created on first run, reused afterwards) so its fingerprint
   is stable and pin-able across restarts; `hsync-bootnode run --ephemeral`
   replaces it with a per-process in-memory identity for read-only filesystems or
   throwaway nodes (ADR-0034).

## Consequences

- The bootnode node key and the server TLS certificate are generated, stored,
  validated and rotated identically, so operators learn one procedure and the
  documentation stays consistent across both repositories.
- Removing the encrypted-key path deletes `serialize_key_pem` and the
  `HSYNC_SSL_KEYFILE_PASSWORD` configuration surface; the man pages, `docs/` and
  the wiki are updated atomically in the owning repositories.
- A pinned identity now survives for the lifetime of the deployment without
  silent expiry; the cost accepted is that a leaked key must be rotated
  explicitly (no short-validity auto-recovery), which the pin-rotation window and
  the `rotate` commands cover.
- Follow-up obligations: the shared model lives only in `hsync_common.ssl_utils`;
  consumers (`hsync-bootnode`, `hsync-server`) reuse it rather than re-declaring
  key type, file permissions or validity.
