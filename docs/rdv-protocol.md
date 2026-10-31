# Rdv/1 rendezvous protocol (client mirror)

Reference for the `rdv/1` channel the `hsync p2p` client uses to discover peers
across networks through a rendezvous node.

> **The authoritative specification is
> [`hsync-rendezvous/protocol-spec/rdv-1.md`](https://github.com/albertsdk/hsync-rendezvous/blob/main/protocol-spec/rdv-1.md)**
> and the canonical golden fixtures are
> [`hsync-rendezvous/fixtures/`](https://github.com/albertsdk/hsync-rendezvous/tree/main/fixtures). This page
> describes the mirror that ships in `hsync-common` for the client; it never
> replaces the spec.

## Where the mirror lives

| Artifact | Path |
| -------- | ---- |
| Frame models + validators | `hsync_common/protocol/rendezvous.py` |
| Mirrored golden fixtures | `hsync_common/protocol/fixtures/rendezvous-*.json` |
| Drift test (bytes vs the canonical fixtures) | `tests/test_protocol_rendezvous.py` |
| Consumer | `hsync-client` (`hsync p2p`, rdv rendezvous plan) |

The rendezvous daemon keeps its own model of the frames (it does not import this
mirror); its Python v1 reuses only generic `hsync-common` utilities — the TLS
identity helpers, the CID pattern and the canonical bucket-name rule. The two
copies are kept honest by the drift test, which compares the mirrored fixtures
byte-for-byte with the canonical ones.

## Transport

- QUIC over UDP, TLS 1.3, ALPN **`hsync-rdv/1`**
  (`RDV_ALPN`).
- The QUIC/TLS listener presents a **self-signed** certificate: the client
  authenticates its SHA-256 DER fingerprint against an explicit pin, the opt-in
  TOFU store or an SSH-style confirmation prompt (the default), and never sends a
  frame to a node it has not authenticated. The full rule lives in the canonical
  spec's *Trust & identity* section; the operator procedure is
  [`hsync-client` — Sync across networks](https://github.com/albertsdk/hsync-client/blob/main/docs/p2p-rendezvous.md).
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
| `relay_listen` | client → server | `cid`, `bucket`, `group?`, `bucket_token?` (listener control stream) |
| `relay_ping` | client → server | `cid`, `bucket` (keepalive on that control stream, no reply) |
| `relay_connect` | client → server | `cid`, `bucket`, `target_cid`, `group?`, `bucket_token?` |
| `relay_attach` | client → server | `cid`, `bucket`, `relay_id`, `bucket_token?` |
| `ack` | server → client | `observed_endpoint{proto,ip,port}`, `ttl`, `server_time`, `retry_after?` |
| `response` | server → client | `peers[{cid, endpoints[{proto,host,port}], cert_fp, bucket, group?, version, capacity, reachable}]`, `count`, `ttl`, `error?`, `retry_after?` |
| `relay_listening` | server → client | `ttl` |
| `relay_incoming` | server → client | `relay_id`, `cid`, `expires_in` |
| `relay_ok` | server → client | `relay_id` |
| `relay_error` | server → client | `error` (`token_required`/`rate_limited`/`overloaded`/`relay_unavailable`), `retry_after?` |

Every frame carries `protocol_version` (`rdv/1`) and a `type` discriminator;
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
  concurrency, never to exclude a peer; the rendezvous never orders its sample by
  it.
- **`reachable`** is derived from `bool(endpoints)` at register time: only a peer
  that published a listen endpoint is advertised as a data-plane master.
- **`endpoints`** is the peer's candidate list, relayed in order and capped at
  **four** entries per peer (a single-element observed-source fallback when the
  peer advertised none); each `host` must be an IP literal or a DNS name, so a
  peer cannot hand other peers an undialable or internal-looking target. Try the
  candidates host/LAN-first and fall back to the next, so two peers behind the
  same NAT connect over the local path even when the public endpoint has no
  hairpin route ([ADR-0038](internal/adr/0038-rendezvous-endpoint-candidate-list.md)).
- **`cert_fp`** is a SHA-256 certificate fingerprint (`sha256:<hex>`, bare hex, or
  colon-separated hex): the value the data-plane pin compares, so anything that is
  not a full digest is an invalid frame.

## Data relay

The relay gets two peers that no inbound NAT mapping reaches (carrier-grade NAT,
a hotspot behind a carrier) onto the `p2p/1` data plane. The node pairs them and
forwards their bytes, which stay **opaque TLS**: it never terminates or inspects
that TLS, so it sees no content, file name or credential, and the peers keep
authenticating each other by certificate pinning. The pairing (`cid` ↔ `cid`) and
the volume are visible to the node; the feature is opt-in per node (`--relay`)
and bounded by host-derived session caps plus an operator-set byte rate.

- The serving peer (the master) holds a **control** stream: `relay_listen` →
  `relay_listening`, then one `relay_incoming` per requester and a `relay_ping`
  keepalive (no reply) while idle.
- A requester opens a fresh stream with `relay_connect` and gets `relay_ok` (the
  rest of the stream is opaque) or `relay_error` and a close.
- For each `relay_incoming` the listener opens a fresh stream whose single framed
  line is `relay_attach`; the node then bridges the two streams with a fixed
  64 KiB buffer and `drain()` on both sides.
- `relay_listen` is accepted only from the current owner of the `(cid, bucket,
  group)` record, `relay_attach` must match `relay_id` + listener `cid`/`bucket` +
  the listener's source IP, and every relay frame carries the optional
  `bucket_token` (uniform `token_required` on protected/private buckets).
- `relay_unavailable` means "no relay here": disabled on the node, no listener for
  that `target_cid`, or the listener did not attach within `expires_in`.

## Bucket tokens

Protected buckets derive the token as
`HMAC-SHA256(key, "rdv/1" || bucket)[:32]` hex (64 chars); the mirror exposes
`derive_bucket_token` / `verify_bucket_token` and the daemon compares in
constant time. Refusals are uniform and never reveal whether a bucket exists.

The group key is the token's only entropy, so the node's key source enforces
`MIN_GROUP_KEY_CHARS` (`hsync_common/protocol/rdv_tokens.py::MIN_GROUP_KEY_CHARS`,
32 characters): a shorter node key is a configuration error, never a weaker
deployment. Clients may instead supply a user-typed `HSYNC_P2P_PASSPHRASE` (at
least 12 characters), which the client expands with scrypt to the same 64-hex
key; the node always consumes the derived key (use `hsync derive-group-key` to
produce it).

## See also

- [p2p Protocol spec](p2p-protocol.md) — the data plane (`p2p/1`).
- [`hsync-client` — Sync across networks (rendezvous)](https://github.com/albertsdk/hsync-client/blob/main/docs/p2p-rendezvous.md) — the operator how-to.
- [`hsync-rendezvous` — Usage: Group keys](https://github.com/albertsdk/hsync-rendezvous/blob/main/docs/usage.md#group-keys---keys-fd----keys-file) — the node-side keys file (one `bucket=<hex-key>` line per bucket) and the `--protected-bucket`/`--private` flags.
- [Protocol guide](protocol.md) — the versioned channels at a glance.
