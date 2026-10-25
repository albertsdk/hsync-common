# Boot/1 bootstrap protocol (client mirror)

Reference for the `boot/1` channel the `hsync p2p` client uses to discover peers
across networks through a bootstrap node.

> **The authoritative specification is
> [`hsync-bootnode/protocol-spec/boot-1.md`](https://github.com/albertsdk/hsync-bootnode/blob/main/protocol-spec/boot-1.md)**
> and the canonical golden fixtures are
> [`hsync-bootnode/fixtures/`](https://github.com/albertsdk/hsync-bootnode/tree/main/fixtures). This page
> describes the mirror that ships in `hsync-common` for the client; it never
> replaces the spec.

## Where the mirror lives

| Artifact | Path |
| -------- | ---- |
| Frame models + validators | `hsync_common/protocol/bootnode.py` |
| Mirrored golden fixtures | `hsync_common/protocol/fixtures/bootnode-*.json` |
| Drift test (bytes vs the canonical fixtures) | `tests/test_protocol_bootnode.py` |
| Consumer | `hsync-client` (`hsync p2p`, bootnode discovery plan) |

The bootnode daemon keeps its own model of the frames (it does not import this
mirror); its Python v1 reuses only generic `hsync-common` utilities — the TLS
identity helpers, the CID pattern and the canonical bucket-name rule. The two
copies are kept honest by the drift test, which compares the mirrored fixtures
byte-for-byte with the canonical ones.

## Transport

- QUIC over UDP, TLS 1.3, ALPN **`hsync-boot/1`**
  (`BOOT_ALPN`).
- The QUIC/TLS listener presents a **self-signed** certificate: the client
  authenticates its SHA-256 DER fingerprint against an explicit pin, the opt-in
  TOFU store or an SSH-style confirmation prompt (the default), and never sends a
  frame to a node it has not authenticated. The full rule lives in the canonical
  spec's *Trust & identity* section; the operator procedure is
  [`hsync-client` — Sync across networks](https://github.com/albertsdk/hsync-client/blob/main/docs/p2p-bootnode.md).
- One bidirectional stream per request; frames are **newline-terminated JSON**
  (NDJSON).
- A refusal is a uniform `response` with `error` — `token_required`
  (authorization), `rate_limited` (per-source limit; `retry_after` = limiter
  refill) or `overloaded` (node capacity backpressure; `retry_after` advisory);
  malformed or unknown frames are **silently dropped**.

## Frames

| Frame | Direction | Fields |
| ----- | --------- | ------ |
| `register` | client → server | `cid`, `bucket`, `group?`, `bucket_token?`, `cert_fp`, `version`, `capacity`, `endpoints[{proto,host,port}]`, `connected?` |
| `refresh` | client → server | `cid`, `bucket`, `group?`, `bucket_token?`, `connected?` |
| `leave` | client → server | `cid`, `bucket`, `bucket_token?` (no response frame) |
| `query` | client → server | `bucket`, `group?`, `bucket_token?`, `limit?` (1–50, default 20) |
| `ack` | server → client | `observed_endpoint{proto,ip,port}`, `ttl`, `server_time`, `retry_after?` |
| `response` | server → client | `peers[{cid, endpoints[{proto,host,port}], cert_fp, bucket, group?, version, capacity, reachable}]`, `count`, `ttl`, `error?`, `retry_after?` |

Every frame carries `protocol_version` (`boot/1`) and a `type` discriminator;
unknown fields make the frame invalid (`extra="forbid"` in the daemon,
strict validators in the mirror).

## Register, then register again

The first `register` cannot publish a public endpoint (the client does not know
its own address yet). The `ack` carries the **observed endpoint** (the
STUN-equivalent echo of the source address). Once the data-plane endpoint is
ready, the client sends a **second `register`** that publishes `endpoints[]`
(the full candidate list):

- `host` is the observed public IP and/or the local/LAN address;
- `port` is the master's **TCP** listen port (`--listen-port` /
  `HSYNC_P2P_LISTEN_PORT`) — never the QUIC/UDP source port;
- `proto` is `tcp`.

`refresh` renews the TTL and the `connected` count only: it never carries
`endpoints` and never mutates other record fields.

## Advisory fields

- **`capacity`** (`0..32`, default `0`; `0` = not a peer-download seeder) is the
  peer's declared service-capacity hint, relayed to querying peers. It is **not
  authenticated and not authoritative**: the authoritative value is `serve_slots`
  on the authenticated data-plane session (ADR-0030). Use it to pre-size
  concurrency, never to exclude a peer; the bootnode never orders its sample by
  it.
- **`reachable`** is derived from `bool(endpoints)` at register time: only a peer
  that published a listen endpoint is advertised as a data-plane master.
- **`endpoints`** is the peer's candidate list, relayed in order and capped at
  **four** entries per peer (a single-element observed-source fallback when the
  peer advertised none); each `host` must be an IP literal or a DNS name, so a
  peer cannot hand other peers an undialable or internal-looking target. Try the
  candidates host/LAN-first and fall back to the next, so two peers behind the
  same NAT connect over the local path even when the public endpoint has no
  hairpin route ([ADR-0038](internal/adr/0038-bootnode-endpoint-candidate-list.md)).
- **`cert_fp`** is a SHA-256 certificate fingerprint (`sha256:<hex>`, bare hex, or
  colon-separated hex): the value the data-plane pin compares, so anything that is
  not a full digest is an invalid frame.

## Bucket tokens

Protected buckets derive the token as
`HMAC-SHA256(key, "boot/1" || bucket)[:32]` hex (64 chars); the mirror exposes
`derive_bucket_token` / `verify_bucket_token` and the daemon compares in
constant time. Refusals are uniform and never reveal whether a bucket exists.

The group key is the token's only entropy, so the node's key source enforces
`MIN_GROUP_KEY_CHARS` (`hsync_common/protocol/boot_tokens.py::MIN_GROUP_KEY_CHARS`,
32 characters): a shorter key is a configuration error, never a weaker
deployment. Clients may instead supply a user-typed `HSYNC_P2P_PASSPHRASE` (at
least 12 characters), which the client expands with scrypt to the same 64-hex
key; the node always consumes the derived key (use `hsync derive-group-key` to
produce it).

## See also

- [p2p Protocol spec](p2p-protocol.md) — the data plane (`p2p/1`).
- [`hsync-client` — Sync across networks (bootnode)](https://github.com/albertsdk/hsync-client/blob/main/docs/p2p-bootnode.md) — the operator how-to.
- [Protocol guide](protocol.md) — the versioned channels at a glance.
