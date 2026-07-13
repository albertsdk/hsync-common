# LAN Discovery & Master Election

This document is the human-readable companion to the machine-checked sources of
truth for the LAN channel. It exists so the Python client (`hsync_client.lan`,
`PeerManager`) and the Android client (`com.hsync.android.p2p`, `LanManager`)
cannot drift: both consume the same canonical algorithm and are validated against
the same golden fixtures.

| Concern | Single source of truth |
|---|---|
| TXT record keys / schema | `hsync_common.protocol.schemas` (`LAN_TXT_KEYS`, `build_lan_txt_schema`) |
| WSS handshake + inventory frames / schema | `hsync_common.protocol.handshake` (`build_lan_*`), `hsync_common.protocol.peer_download` (`build_lan_inventory_*`), `hsync_common.protocol.schemas` (`build_lan_wss_schema`) |
| Peer-source REST payloads / schema | `hsync_common.protocol.peer_download` (`build_lan_sources_*`, strict validators), `hsync_common.protocol.schemas` (`build_lan_sources_schema`) |
| Full-download checksum header | `hsync_common.constants.HEADER_CHECKSUM_SHA256` (`X-Checksum-SHA256`) |
| Election algorithm | `hsync_common.protocol.lan` (`rank_election_candidates`, `elect_master`, `election_sort_key`) |
| Pairing / trust policy | `hsync_common.protocol.pairing` (`evaluate_pin`, `lan_write_requires_key`, `requires_pairing_confirmation`) |
| Kotlin mirror | `com.hsync.android.p2p.Election`, `com.hsync.android.p2p.Pairing`, `com.hsync.android.data.api.Protocol` |
| Cross-language scenarios | `protocol/fixtures/lan-election-scenarios.json`, `protocol/fixtures/lan-pairing-scenarios.json`, `protocol/fixtures/lan-sources-*.json`, `protocol/fixtures/lan-wss-*.json` |

## mDNS / TXT record

Each peer announces itself over mDNS/NSD. All TXT values are strings (mDNS
encoding); boolean flags are advertised **only when true**. The canonical key set
lives in `LAN_TXT_KEYS`; do not introduce keys outside it.

**Required keys**

| Key | Type | Notes |
|---|---|---|
| `cid` | string | Unique client id; strictly alphanumeric (`[A-Za-z0-9]{21}`), so it always starts with a letter or digit; final election tiebreaker. |
| `bucket` | string | Bucket served/synced. |
| `version` | string | Semantic app version (informational only). |
| `protocol` | string | LAN protocol version (`lan/1`); mismatched peers are ignored. |
| `startup_time` | string (number) | Unix start time; earlier wins. |
| `sync_direction` | string | `bidirectional` (preferred), `upload-only`, `download-only`. |

**Optional keys** (present only when meaningful/true): `group`, `https`,
`cert_fp`, `compression`, `delta`, `server_ready`, `force_master`,
`never_master`, `connected`, `heartbeat`, `peer_download`.

`compression` and `delta` are advertised only when the feature is enabled on
that node. Per the canonical rule, a boolean flag is advertised only when
true, so an absent key means "false". Causal version metadata (ADR-0022) and
deletion gossip (ADR-0003) are hard dependencies of the sync/conflict model and
are negotiated over the authenticated WSS handshake (ADR-0024), never the TXT
record.

`peer_download` means the node implements the ADR-0028 inventory, batch source
lookup, and read-only seeder semantics. A serving master publishes it when its
`POST .../files/sources` endpoint is available; this TXT flag gates initial and
one-shot lookup before WSS. After an authenticated handshake the WSS capability is
authoritative, and so is the seeder's live capacity advertisement (ADR-0030):
whether a peer can serve *right now* is decided only by its authenticated session
with the master, never by a discovery-time hint. A stale or spoofed hint can at
worst cause a failed source lookup or peer attempt, followed by the mandatory
master fallback.

Endpoint-material keys are optional at the record level because a node advertises
them only while it serves an endpoint. A master or seeder, however, **must**
advertise both `https` (`"true"`) and `cert_fp` (the lowercase SHA-256
fingerprint clients pin). A peer that advertises a serving role without them is
invalid and must not be contacted. Non-serving slaves need not advertise either.

## Presence counters

`connected` (a stringified non-negative integer, advertised only by a serving
master) carries the number of slaves currently connected to the master's
WebSocket. It is **diagnostic only**: it never participates in the election
and is never trusted for gating decisions. Slaves use it to display the
display-ready group presence pair

- `connected = 1 + peers' connected` (the master itself always counts as
  connected; clamped to `total` against stale records)
- `total = 1 + alive mDNS peers`

which mirrors the server-mode `presence` WebSocket frame shape
(`hsync_common.protocol.handshake.build_ws_presence`,
`{"type": "presence", "connected", "total"}`). The same pair is the payload of
the `peers` structured UI event (schema v2), so desktop and mobile surfaces
render one shared "connected/total" value across both transports.

## Master ⇄ slave WebSocket handshake

The connecting slave and the master exchange the **capability registry on the
WSS connection itself** (ADR-0024), on both the authenticated and the
unauthenticated path. The frames are built by
`hsync_common.protocol.handshake` builders and are pinned by
`protocol/lan/wss-schema.json` and the `lan-wss-*` golden fixtures (mirrored in
Android):

1. The master greets first:
   - **With a LAN key** — `{"type": "auth_required", "protocol_version": "lan/1", "capabilities": [...]}`.
   - **Without a LAN key** — `{"type": "hello", "protocol_version": "lan/1", "capabilities": [...]}` (the slave replies with the same shape plus its `cid`).
2. On the auth path the slave replies
   `{"type": "auth", "token", "cid", "protocol_version", "capabilities"}`; the
   master validates the CID format **first**, then the `protocol_version` (hard
   fail → `{"type": "auth", "status": "failed", "reason": "protocol_incompatible"}`),
   then the token (constant-time). Success is
   `{"type": "auth", "status": "ok", "protocol_version", "capabilities"}`.
   The slave's frame also carries `serve_slots` (1–32) **while it serves peer
   downloads**: the master records it with the publisher session and echoes it to
   requesters as their per-seeder admission limit (ADR-0030). An out-of-range
   value, or a slot count without the `peer_download` capability, is refused as a
   protocol violation; omitting it means "not a source candidate".

Semantics:

- **The authenticated reply is the authoritative capability source.** The slave
  adopts the master's advertised set from the auth reply into its transfer
  gates; the TXT values are a discovery-time hint only. mDNS data is
  unauthenticated and can be stale, so it never decides the session.
- **Intersection, never negotiation.** A feature is used only when both sides
  advertise it; an absent capability degrades the feature (delta → full
  transfer, compression → raw bytes, no `vector_clocks` → empty clock), never an
  error. Unknown tokens are silently ignored.
- **The hello path is coherence only.** Without a `LAN_KEY` neither the CID nor
  the capabilities are authenticated: the values are logged, never trusted for
  gating decisions on the master side; the slave keeps using the TXT values
  unless it later authenticates.
- `peer_download` follows the same intersection rule. A slave publishes
  inventory only when its implementation is enabled and the master's WSS
  handshake advertises the capability. On a no-key hello it is an availability
  hint rather than authenticated authorization; every failure remains a safe
  master fallback.
- A `protocol_version` mismatch anywhere in the handshake is a **hard failure**
  (auth refused / peer treated as invalid), exactly like the WS channel.

## Peer-assisted full-file download (ADR-0028)

Peer assistance is an optimization for **full regular-file downloads only**.
The master remains tracker, causal arbiter, event relay, and guaranteed source.
Uploads, deletes, renames, permission changes, tombstones, symlinks and delta
transfer remain master-coordinated. When delta applies, the requester tries the
existing delta-to-master path first; only its full-transfer fallback may use a
peer.

Continuous, non-dry-run slaves may seed. One-shot clients may request peer
sources but never bind a seeder or publish inventory. Eligibility is not a
function of file size: a listed file is looked up whenever a live seeder
advertises its exact `(path, SHA-256)`, and the requester then respects that
seeder's advertised `serve_slots` capacity. Missing capability, an empty source
list, or any peer failure selects the master without changing sync correctness.

### Batch source lookup

- Each `sources` list has 0–8 unique CIDs. `serve_slots` is the capacity the
  seeder advertised on its authenticated handshake (1–32); the requester admits at
  most that many concurrent reads per CID, waiting a bounded interval for a slot
  before falling back to the master, so it never discovers the limit by provoking
  refusals (ADR-0030). A candidate is never returned for a CID without a live
  advertisement.

The master-only endpoint is:

```http
POST /api/v1/buckets/{bucket}/files/sources
Content-Type: application/json
```

Request:

```json
{
  "cid": "RequesterCid123456789",
  "files": [
    {
      "path": "dir/a.bin",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
  ]
}
```

Response:

```json
{
  "files": [
    {
      "path": "dir/a.bin",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "sources": [
        {
          "cid": "SeederPeerX1234567890",
          "download_url": "https://192.0.2.10:8443/api/v1/buckets/bucket-1/files/download",
          "cert_fp": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
          "compression": true,
          "serve_slots": 2
        }
      ]
    }
  ]
}
```

The machine-readable contract is `protocol/lan/sources-schema.json`; strict
builders and validators live in `hsync_common.protocol.peer_download`.

- Request and response objects reject unknown properties. A body is at most
  2 MiB and must use `application/json`.
- `cid` is required and must match `[A-Za-z0-9]{21}`. If that CID already has a
  live WSS owner, the master rejects a claim from another address with 403;
  one-shot requesters without a WSS binding remain valid.
- `files` contains 1–500 entries. `path` is canonical bucket-relative output of
  `validate_remote_relpath`; every normalized path appears exactly once. Hashes
  are exactly 64 lowercase hex characters. Identical hashes at different paths
  are valid. Bad shape/CID/path/hash/duplicate or content type returns 400; an
  encoded body over 2 MiB returns 413.
- The route bucket must exactly match the serving bucket. A response is a list,
  preserving identity as `(path, sha256)` rather than collapsing it into a
  path-keyed map.
- Each `sources` list has 0–8 unique CIDs. The requester and master are omitted
  by CID; distinct peers may legitimately share one IP address. A candidate is
  included only for exact indexed hash membership, a WSS session address that
  matches its advertised endpoint, and a currently alive peer.
- `download_url` is the complete HTTPS `.../files/download` endpoint with an
  explicit port in `1..65535`. Hosts are current peer IP literals; IPv6 literals
  are bracketed and zone identifiers are rejected. `cert_fp` is canonical
  lowercase 64-hex. Clients append query parameters only.
- Candidate ranking partitions same-subnet peers first (IPv4 `/24`, IPv6 `/64`)
  and uses injectable randomness inside each partition. This is a proximity
  bias, never proof of identity or authority.
- A seeder does not expose this POST; unsupported methods return 405. Lookup
  failure, 404/405, malformed candidates, or an empty list is master-only
  fallback, not a sync failure.

The exact seeder request is:

```http
GET {download_url}?filename=<percent-encoded-normalized-path>&sha256=<lowercase-hex>&cid=<requester-cid>
```

Missing or repeated parameters, an invalid path/hash/CID, or a hash that no
longer matches the opened regular file is rejected (400 for malformed input,
409 for current-content mismatch). Seeders expose only `GET /health`,
`GET /time`, and this file download; list, write, delta, tombstone and source
routes return 405. Their active response-body concurrency is capped (default 2,
valid range 1–32) and **advertised on the handshake** as `serve_slots`, so a
requester knows the limit in advance and does not fire attempts that must be
refused. Saturation still answers 503 before opening the file, now with a
`Retry-After` delay: the requester defers that source for exactly that interval
instead of counting it as a health failure (ADR-0030).

The seeder hashes and streams the same no-follow opened regular-file descriptor,
rejecting identity/size mutation. Its response uses the canonical
`X-Checksum-SHA256` header. The requester still treats every source header as
untrusted and commits only after the complete decoded body matches the listing
hash. Peer candidates are tried before the master; partial bytes survive only
an interrupted body, never a completed hash/range/size failure.

### Inventory frames

Inventory extends `lan/1` additively. Slave to master snapshot:

```json
{
  "type": "inventory",
  "gen": 1,
  "seq": 0,
  "mode": "snapshot",
  "more": true,
  "entries": [
    {
      "path": "a.bin",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "size": 123
    }
  ]
}
```

Complete delta upsert and delete frames are independent transactions:

```json
{"type":"inventory","gen":1,"seq":8,"mode":"delta","more":false,"entries":[{"path":"b.bin","sha256":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","size":456}]}
```

```json
{"type":"inventory","gen":1,"seq":9,"mode":"delta","more":false,"entries":[{"path":"a.bin","deleted":true}]}
```

Master to slave acknowledgement:

```json
{"type":"inventory_ack","gen":1,"seq":7,"status":"ok"}
```

`status` is exactly `ok`, `resync`, or `rejected`. A rejected ACK also carries a
required lowercase machine reason matching `[a-z][a-z0-9_]{0,63}`, for example
`quota` or `invalid`; other statuses must not carry `reason`.

Wire and state-machine rules:

1. All objects are strict. Paths and hashes use the same canonical rules as the
   source endpoint. `gen`, `seq`, and `size` are non-boolean integers in
   `0..2^63-1`. Every frame is at most 2 MiB and has at most 500 entries.
2. A snapshot has one generation and contiguous `seq=0..N`. Snapshot entries
   have exactly `path`, `sha256`, and `size`; deletion entries are delta-only.
   The master stages chunks and exposes the previous committed snapshot until
   terminal `more=false` atomically replaces it. Empty inventory is one terminal
   `seq=0` snapshot with an empty `entries` list.
3. Missing or out-of-order snapshot sequence discards that session's staging
   and returns `(gen, expected_seq, resync)`. A terminal commit returns cumulative
   `(gen, N, ok)`. A retransmitted terminal frame after a lost ACK is ACKed
   idempotently only when its canonical payload digest matches the committed
   terminal frame; a mismatch returns `resync`.
4. Deltas begin only after the terminal snapshot ACK. Each delta is non-empty,
   has `more=false`, and commits independently. Upserts have exactly
   `path,sha256,size`; deletes exactly `path,deleted=true`. Larger queues are
   split into consecutive independently ACKed frames. A duplicate
   `seq <= last_applied` is ACKed without reapplying; a gap returns `resync`.
5. Duplicate normalized paths inside one frame are invalid. Structural errors
   reject/close publication; individual bad entries are never silently dropped
   into an otherwise committed frame.
6. Final-snapshot/delta ACK timeout is 15 seconds: resend the same frame once,
   then reconnect and start a new generation/snapshot. One existing WSS receive
   loop demultiplexes ACKs from file events; a second `recv()` is forbidden.
7. Every admitted WSS connection owns an opaque server session token. Only the
   current token may mutate or purge that CID. Disconnect purges holders only
   when the disconnecting connection still owns the CID; replacement
   connections are unaffected.
8. Per-CID quota is committed plus staged rows, at most 2,000,000. The global
   quota counts both tables, at most 20,000,000. At most 64 publisher sessions
   exist and snapshot staging expires after five minutes. Expired staging is
   reclaimed before frame admission; quota check and mutation share one
   transaction.
9. `rejected` drops only that session's staging and disables further publication
   for it. The previous committed snapshot stays visible until the owner
   disconnects, and ordinary master sync continues.
10. A live resnapshot resolves/cancels an outstanding delta, increments `gen`,
    resets `seq=0`, and leaves prior committed rows visible until terminal
    commit. Local mutations during scanning/staging queue as post-ACK deltas;
    ACKs from older generations are ignored.

Successful existing `transfer` UI events may include `source_cid` only for a
peer-served, fully verified full transfer. Master downloads, delta downloads,
and failed peer attempts followed by master success omit it. URLs and
fingerprints never appear in structured events; no new event names are added.

## Group partitioning

`group` is a strict partition key: a peer is visible only when its group is
**exactly equal** to the local group. "No group" (null/blank) is itself a
distinct partition, so an ungrouped peer matches only other ungrouped peers.
Peers in a different partition are dropped before election.

## Master election

Election decides only **who serves** the transport hub (the HTTPS/WSS server
peers connect to and that relays file events). It confers **no authority over
conflicts**: every node resolves concurrently with vector clocks
([ADR-0022](internal/adr/0022-causal-vector-clock-conflict-model.md)), so the
elected master never wins a divergence by role.

Election runs on every discovery change (peer added, updated, removed), when the
local `server_ready` state changes, and on a **periodic staleness sweep**: every
discovery wake (and every slave WebSocket drop) re-evaluates each peer's
heartbeat, expires peers whose announce has not been seen within the configured
peer timeout, and re-runs the election. A peer that crashes hard sends no
goodbye and no further announce, so without this sweep the surviving peers would
otherwise keep a dead master's record indefinitely (the two-node failure mode).
The candidate set is the local node plus every alive, group-compatible peer.
`never_master` nodes are carried into the set but **excluded** by the algorithm.

Liveness has two layers. The **WebSocket link is authoritative** for the
master<->slave channels: a peer with a live WSS connection is alive regardless
of mDNS staleness. For the **slave<->slave** channel (no WSS link) liveness is
carried by a **heartbeat**: every peer re-announces its TXT record at
`HSYNC_HEARTBEAT_INTERVAL` with an incremented opaque `heartbeat` counter, and
zeroconf only re-delivers a TXT record when its *value* changes — so the
counter is what makes a quiescent-but-alive peer's `last_seen` stay fresh.
mDNS staleness is therefore the **fallback** that detects a hard crash: a dead
peer stops heartbeating and its record goes stale within the peer timeout,
without the false "idle peer = dead" demotions (split-brain) that a value-less
re-announce would cause.

Receivers must also apply a **goodbye grace**: a peer cannot always update its
TXT in place (Android NSD has no `update_service`, so its heartbeat is an
unregister+register cycle) and the unregister broadcasts a goodbye. Honouring
that goodbye immediately would drop live **slave<->slave** peers (no WSS
link) on every Android heartbeat and re-elect. Receivers therefore delay
acting on `remove_service` / `onServiceLost` long enough for the following
announce to cancel the removal. A live WSS link is still an immediate ignore.
A peer that truly left is removed after the grace window (or by the staleness
sweep if it crashed hard).

The eligible candidates are ranked once by the shared helper
`rank_election_candidates` (smallest sort key first, `never_master` filtered
out); `elect_master` is its winner-only projection and consumers needing more
than the winner (successor, conflict reports) use the same ranked list:

1. **`server_ready`** — an already-serving incumbent wins, so a newcomer never
   triggers a needless takeover/split-brain for the same bucket.
2. **`force_master`** — an operator-pinned master wins over ordinary peers.
3. **bidirectional `sync_direction`** — a fully bidirectional peer is preferred
   over an upload-/download-only one (it can serve every other peer).
4. **earliest `startup_time`** — the node that started first wins.
5. **lowest `cid`** lexicographically — a deterministic final tiebreaker.

If no candidate is eligible (every node is `never_master`) **no master is
elected**: `elect_master` returns `None`, the role becomes `NONE`, and a parsable
`[NO MASTER]` warning is logged so front-ends can tell the user synchronization
cannot proceed.

### Edge cases

- **Incumbency vs force_master.** A serving incumbent (`server_ready=true`) beats
  a newcomer even if the newcomer sets `force_master`, because `server_ready`
  ranks above `force_master`. The pin still wins once both are at parity on
  readiness (scenario `incumbent-server-ready-wins-over-force-master`).
- **force_master conflict.** When more than one eligible candidate sets
  `force_master`, the best-ranked one wins and the others are logged as
  `[MASTER CONFLICT]` (`conflict_won` / `conflict_lost`).
- **force_master takeover.** A remote `force_master` peer overriding the local
  non-`force_master` incumbent is logged as `[MASTER TAKEOVER]`.
- **never_master.** Such nodes never serve. If they are the only candidates the
  result is `NO_MASTER` (scenario `all-never-master-no-master`).

### Failover timing

The staleness sweep bounds how long the group runs masterless after a hard
crash: the dead master is demoted once its heartbeat has been absent for the
configured peer timeout, and every remaining peer converges on the same
successor because the election is deterministic. Each node also pre-computes
the **successor** (the next-ranked eligible candidate) for operator logging and
diagnostics — it never gates the decision. The peer timeout is a client
operational knob (`HSYNC_PEER_TIMEOUT`) constrained to at least twice the
heartbeat (`HSYNC_HEARTBEAT_INTERVAL`) so a single missed announce can never
flap a live peer into a needless re-election. A slave whose WebSocket to the
master drops clears the master's WSS liveness mark and re-runs the sweep
immediately, but only demotes a master whose record is already stale: a
transient local-link blip leaves the incumbent in place, so the surviving peers
do not split-brain.

### Leadership lease and yield (ADR-0027)

Serving is a **lease**: a node holds the right to serve only while it is the
elected master *and* actually serving. When a live master **loses** the
election — which, because exactly one node serves per healthy partition, only
happens on **network-partition heal** (the two sides elected different masters,
and a `force_master` peer wins at parity when they converge) — it **yields
immediately**: it stops its HTTP/WSS servers, revokes its incumbency by
clearing the local `server_ready` flag and updating its mDNS record in place
without `server_ready`/`connected`, and logs `[MASTER YIELD]`. A yielded node is
therefore no longer an incumbent in any peer's election, closing the *zombie
incumbent* window (a node that had stopped serving but still advertised
`server_ready=true`).

A master's `server_ready`/`connected` TXT changes are always published
**in place** (`zeroconf.update_service`), never as an unregister+register cycle:
an unregister broadcasts a goodbye that every slave would observe as a spurious
`remove_service` for the master (a "Peer disconnected" + re-election churn) for
a value that only changed for diagnostics. (Android cannot honour this rule —
NSD lacks an in-place TXT update — so its periodic re-announces rely on the
receivers' goodbye grace described above; the grace applies to the heartbeat
re-announce, never to a real mastership flip.)

This is a bounded-incumbency lease, **not** a quorum: a full network partition
can still briefly yield two masters, and the divergence is reconciled causally
on heal ([ADR-0022](internal/adr/0022-causal-vector-clock-conflict-model.md)).
Guaranteeing at-most-one master under partition would require a majority quorum
with fixed membership, which conflicts with the dynamic home-LAN topology.

## Cross-language parity

`lan-election-scenarios.json` is generated from the Python source
(`hsync_common.protocol.fixtures`): each scenario stores its candidates and the
winner **computed by `elect_master`** (never hand-written). The file is copied
verbatim into the Android test resources and replayed by both runners:

- Python — `tests/test_protocol_lan.py`.
- Android — `LanElectionParityTest` (via `Election.electMaster`).

A divergence on either side fails the parity test instead of becoming a
split-brain in the field. Regenerate after any change with:

```bash
poetry run python scripts/export_protocol_schemas.py
```

then copy the regenerated `protocol/fixtures/*.json` into
`hsync-android/app/src/test/resources/protocol/fixtures/` (the
`TestAndroidFixtureParity` test enforces byte-for-byte equality).

## Causal tombstones (deletion gossip)

Deletion markers exchanged over the LAN gossip channel (`/tombstones` on the
master, see `hsync-client/lan_server.py`) are **causal** ([ADR-0003](../docs/internal/adr/0003-tombstone-gossip.md)):
each entry carries `sha256`, `version_id`, `origin_cid`, the informational `ts`
and a `vclock` — the stored version clock for the path, merged and ticked by
the deleter. The merge between peers is decided by **causal dominance** of the
clocks, with a deterministic content-based tie-break (content hash, then
version id, then author cid) on true divergence. The deletion timestamp is
never consulted for decisions.

Consequences for the wire protocol:

- A receiving peer **must** validate each entry strictly: without a structurally
  valid `vclock` (non-negative int counters, valid cids, ≤ 256 entries) a marker
  is not a legal deletion and is dropped — it must never be loaded with a
  fabricated empty clock.
- A tombstone causally dominating the local version is positive proof the
  deletion descends from the common history: the deleting peer applies it
  unconditionally (the mass-deletion guard, ADR-0015, exempts these).
- An edit concurrent with (not dominated by) a tombstone resurrects the file:
  the re-created content wins and the tombstone is dropped by the new clock.
- Retransmission of stale markers is harmless: the causal merge keeps the
  dominant clock, so a peer that re-gossips an older entry cannot regress the
  store.

Every peer records its own deletion markers at deletion time — both when it is
serving as master and when it is running as a slave — so correctness never
depends on which role observed the removal nor on the transport being up at
that moment: a slave whose master is temporarily unreachable still records the
marker, and the next reconciliation deletes the stale remote copy on the master
instead of downloading it back. The client-side `delete_remote` action therefore
speaks both transports' DELETE contracts: form fields (`filename`, `cid`)
against the central server and query parameters (`path`, `is_dir`, `cid`)
against the LAN master (`hsync-client/hsync_client/transfer.py`
`delete_file_remote`).

The tombstone **TTL (default 90 days) is a storage bound only**: correctness
never depends on pruning, because deletion decisions are causal. The
`causal-tombstone-scenarios.json` fixture (generated from the shared algorithm
and copied into the Android test resources) is replayed by the Python and
Android parity tests to guarantee both sides reach the same merge decisions.

## Event propagation and timing

Once roles are settled, file changes flow over the WSS event channel, but the
two directions are deliberately **asymmetric** because the master and the slaves
play different transport roles:

- **Master → slave (metadata push, near-instant).** The master watches its
  local bucket and, the moment a file is closed, broadcasts a `modified` event
  carrying only metadata (path, size, SHA-256) to every connected slave. Slaves
  then **pull** the bytes over HTTPS and verify them against the broadcast hash.
  The master never waits before broadcasting, so propagation is bounded only by
  network latency and the slave's download time.
- **Slave → master (byte push, guarded by a *hybrid* stability check).** A slave
  does not broadcast; it **uploads** the bytes to the master over HTTPS, which
  then re-broadcasts to the other peers. Before each upload the slave runs the
  file-stability guard (`is_file_stable`), which compares the file's size and
  mtime across a quiet interval. The length of that interval depends on **what
  triggered the upload**:
  - **Fast path (`on_closed` / `IN_CLOSE_WRITE`, Linux).** When the kernel
    reports that the writer closed the descriptor, the close itself already
    signals write completion, so the slave performs a single **short re-check**
    (`STABILITY_DELAY_ON_CLOSED` = 0.3 s) and uploads immediately. This brings
    slave→master propagation to **sub-second**, matching the near-instant
    master→slave path.
  - **Slow path (polling / `on_modified` fallback / non-Linux).** Without a
    close signal the slave falls back to the conservative guard
    (`STABILITY_DELAY`, default `FILE_STABILITY_INTERVAL_DEFAULT` = 5 s),
    polling size+mtime until they settle.

  The fast path also **degrades to the slow path** automatically: if the 0.3 s
  re-check still sees the file changing (e.g. a rapid multi-close or an NFS
  chunked write), the guard reverts to the bounded poll.

### Why the asymmetry is intentional

The guard lives on the **push** side to avoid uploading a half-written
("torn") file to the master, which is the single source of truth other peers
pull from. The pull side does not need it: the master only advertises a
closed-file's metadata, and the slave's download is checksum-verified against
that metadata, so a transient mismatch is simply re-synced by the next event. A
file that never stabilises within `MAX_WAIT_TIMEOUT` is **rescheduled** rather
than uploaded torn (bounded by `UPLOAD_MAX_RESCHEDULES`).

### Why trusting `on_closed` is safe

`IN_CLOSE_WRITE` is the same completion signal used by industry-standard tools
(lsyncd, Syncthing's watcher). The short re-check absorbs the few edge cases
where a close does not yet mean "done" (NFS, multi-writer rapid close,
non-atomic save-then-reopen). Integrity is then guaranteed **downstream** by the
server regardless of client-side timing: every upload is committed with an
atomic `replace()` and verified against its SHA-256, so a torn or mismatched
body is rejected and re-synced rather than persisted. This makes reducing the
client-side latency safe by construction.

### Latency

Slave-originated changes now propagate in **sub-second** time on Linux (the
common `on_closed` case), aligned with the near-instant master→slave path; the
conservative 5 s guard remains only for platforms/fallbacks without a close
signal.

## Security

The election above decides *who serves*; this section decides *who to trust*. The
trust decisions are the single source of truth in
`hsync_common.protocol.pairing`; persistence and I/O live in each client.

### Threat model

The LAN channel is designed for a **trusted LAN** (a home/office network the
operator controls) and degrades safely on an **untrusted LAN** (shared/public
Wi-Fi):

- mDNS/TXT discovery is **unauthenticated**: any host can advertise any `cid`,
  `bucket` or flag. Discovery data is therefore a hint, never proof.
- The LAN transport is **HTTPS/WSS only**: there is no plain-HTTP path. A master
  serves over TLS and advertises its certificate fingerprint in `cert_fp`. TLS
  gives **confidentiality and integrity** against passive eavesdroppers, but the
  self-signed certificate **does not prove identity** — on its own it cannot
  distinguish the real master from an impostor that generated its own
  certificate. A peer that does not advertise both `https` and `cert_fp` is not a
  valid master and is refused (`[INSECURE MASTER]`).
- `HSYNC_LAN_KEY` is a shared secret presented as a bearer token. It authenticates
  *writes* to the master, travels only over the (mandatory) encrypted transport,
  and is shared, not per-peer.

Identity is therefore established by **Trust On First Use (TOFU)** pinning.
Mutation authorization uses the shared key, or an explicit dangerous keyless
write opt-in on both the writing client and the master.

### Master identity (persistent)

A peer's identity is **persistent**, not per-session: each installation owns a
device identity (Syncthing-style) — a stable 21-character device ID plus the
LAN keypair — stored in the device directory (`~/.local/state/hsync/device`,
overridable via `HSYNC_DEVICE_DIR`). The device ID is advertised as the mDNS
`cid` and
anchors the TOFU pin (`(cid, bucket)`), so a restarted master is recognised by
its peers instead of being silently re-pinned, and a rotated keypair (deleted
`*.pem` files with the device ID kept) triggers `[FINGERPRINT CHANGED]` as
intended. The certificate is RSA, self-signed, and valid for ~10 years —
validity is an operational convenience only, since trust comes from the pinned
fingerprint rather than chain/date validation.

The private key is written as an **unencrypted PKCS#8** PEM, protected solely by
filesystem permissions: the key file is `0o600` inside a `0o700` directory. There
is no key password.

### Certificate pinning (TOFU)

The first `cert_fp` seen for a `(cid, bucket)` is pinned (client store:
`hsync_client.pinning.PinStore`, outside the synced bucket and overridable via
`HSYNC_LAN_PIN_FILE`). Because the transport is HTTPS-only, every master sighting
carries a fingerprint; a missing one is a contract violation and `evaluate_pin`
raises. `evaluate_pin` classifies every (present) later sighting:

| Decision | Meaning | Client behaviour |
|---|---|---|
| `trusted` | first sighting | pin it and proceed |
| `matched` | equals the pin | proceed |
| `changed` | differs from the pin | **refuse** to connect; emit `fingerprint_changed` |

A `changed` fingerprint is treated as a possible man-in-the-middle: the client
logs a parsable `[FINGERPRINT CHANGED]` line, emits the structured event, and
stays in discovery instead of connecting. Re-trusting a legitimately rotated
certificate requires removing the stale pin out of band.

The pin is enforced **at the connection level**, on the very TLS connection that
carries the data, with no separate probe (which would leave a TOCTOU window):

- **REST (`requests`/`urllib3`)** — `FingerprintHTTPAdapter` mounts the pinned
  fingerprint via urllib3's `assert_fingerprint`, so the handshake itself fails if
  the peer certificate does not match. The chain and hostname are intentionally
  not validated: trust is the pinned fingerprint alone.
- **WebSocket (WSS)** — after the handshake completes,
  `verify_peer_cert_fingerprint` checks the live connection's peer certificate
  (`getpeercert(binary_form=True)`) against the pin before any data is exchanged.

### LAN mutation authorization (ADR-0029)

Because a self-signed transport does not authorize mutation, LAN writes fail
closed independently of whether the invocation is interactive:

- When a LAN key is configured, every mutation requires its matching Bearer
  token. The keyless-write setting is ignored and cannot bypass the key.
- With no configured key, mutation is rejected by default. Read endpoints,
  health/time, source lookup, inventory publication, and seeder downloads remain
  available.
- With no configured key, mutation is allowed only when the master explicitly
  enables unauthenticated writes. A write-capable client must independently opt
  in before emitting such a request; its setting cannot override the master.

`lan_write_requires_key(sync_direction,
allow_unauthenticated_writes=...)` is the canonical client-side rule. It returns
true for `bidirectional` and `upload-only` unless the explicit opt-in is set.
`download-only` never writes and therefore does not require the key.

When a write would have neither a key nor the explicit opt-in, the client logs
`[AUTH REQUIRED]`, emits the `auth_required` event, and exits before sync. The
master independently returns 403 for no-key mutation unless its own dangerous
opt-in is enabled. Upload, delete, rename, permission update, delta apply, and
tombstone mutation all use this same matrix.

### Explicit pairing (strict mode)

TOFU trusts a peer's *first* certificate automatically, which is convenient on a
trusted LAN but assumes no attacker was already present at first sighting. Strict
pairing (`HSYNC_LAN_REQUIRE_PAIRING` / client `LAN_REQUIRE_PAIRING` or the
`--require-pairing` CLI flag, Desktop *Require pairing* toggle, Android
`SyncConfig.lanRequirePairing`) closes that window by disabling the auto-pin
shortcut. `requires_pairing_confirmation(decision, require_pairing=...)` is the
canonical rule: it returns true only for a first sighting (`trusted`) while
strict pairing is on; `matched`/`changed` are unaffected.

When it triggers, the client logs `[PAIRING NEEDED]`, emits the `pairing_needed`
event and stays in discovery without connecting. The operator confirms the peer
out of band — by pinning its fingerprint (or disabling strict pairing) — after
which the normal TOFU table applies.

### Security events

Security state is surfaced on the structured channel rather than by
scraping log wording: `fingerprint_changed` (pin mismatch, connection refused),
`auth_required` (write lacks a key and the explicit keyless-write opt-in), and
`pairing_needed` (strict pairing: a first-seen certificate awaiting out-of-band
confirmation).

### CID format enforcement

Every client-ID received from a remote peer (WebSocket auth/hello message, HTTP
query parameter `?cid=`, delta token metadata) **MUST** pass `is_valid_cid()`
(`hsync_common.models.event`, pattern `^[A-Za-z0-9]{21}$`, `fullmatch`) before
it is trusted for log lines, echo suppression, or event attribution.  A CID that
fails validation is rejected at the transport level (WebSocket close / HTTP 4xx)
rather than silently falling back to `"unknown"`.  This prevents log injection
and ensures every CID-bearing log line is safe to parse.

The `fullmatch` (vs `match`) guarantee means a trailing `\n` or any other
character outside the alphanumeric set causes rejection, closing the
newline-injection vector documented in the `CID_PATTERN` docstring.
