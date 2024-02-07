# LAN Discovery & Master Election

This document is the human-readable companion to the machine-checked sources of
truth for the LAN channel. It exists so the Python client (`hsync_client.lan`,
`PeerManager`) and the Android client (`com.hsync.android.p2p`, `LanManager`)
cannot drift: both consume the same canonical algorithm and are validated against
the same golden fixtures.

| Concern | Single source of truth |
|---|---|
| TXT record keys / schema | `hsync_common.protocol.schemas` (`LAN_TXT_KEYS`, `build_lan_txt_schema`) |
| Election algorithm | `hsync_common.protocol.lan` (`elect_master`, `election_sort_key`) |
| Pairing / trust policy | `hsync_common.protocol.pairing` (`evaluate_pin`, `lan_write_requires_key`, `requires_pairing_confirmation`) |
| Kotlin mirror | `com.hsync.android.p2p.Election`, `com.hsync.android.p2p.Pairing` |
| Cross-language scenarios | `protocol/fixtures/lan-election-scenarios.json`, `protocol/fixtures/lan-pairing-scenarios.json` |

## mDNS / TXT record

Each peer announces itself over mDNS/NSD. All TXT values are strings (mDNS
encoding); boolean flags are advertised **only when true**. The canonical key set
lives in `LAN_TXT_KEYS`; do not introduce keys outside it.

**Required keys**

| Key | Type | Notes |
|---|---|---|
| `cid` | string | Unique client id; final election tiebreaker. |
| `bucket` | string | Bucket served/synced. |
| `version` | string | Semantic app version (informational only). |
| `protocol` | string | LAN protocol version (`lan/1`); mismatched peers are ignored. |
| `startup_time` | string (number) | Unix start time; earlier wins. |
| `sync_direction` | string | `bidirectional` (preferred), `upload-only`, `download-only`. |

**Optional keys** (present only when meaningful/true): `group`, `https`,
`cert_fp`, `compression`, `server_ready`, `force_master`, `never_master`.

These keys are optional at the record level because a node only advertises them
once it is **serving as master**. A master, however, **must** advertise both
`https` (`"true"`) and `cert_fp` (the SHA-256 fingerprint clients pin): the LAN
transport is HTTPS-only, so a peer that does not is **not a valid master** and a
slave refuses to connect to it (it logs `[INSECURE_MASTER]` and stays in
discovery).

## Group partitioning

`group` is a strict partition key: a peer is visible only when its group is
**exactly equal** to the local group. "No group" (null/blank) is itself a
distinct partition, so an ungrouped peer matches only other ungrouped peers.
Peers in a different partition are dropped before election.

## Master election

Election runs on every discovery change (peer added, updated, removed) and when
the local `server_ready` state changes. The candidate set is the local node plus
every alive, group-compatible peer. `never_master` nodes are carried into the set
but **excluded** by the algorithm.

The winner is the candidate with the smallest sort key
(`election_sort_key`), i.e. highest priority first:

1. **`server_ready`** — an already-serving incumbent wins, so a newcomer never
   triggers a needless takeover/split-brain for the same bucket.
2. **`force_master`** — an operator-pinned master wins over ordinary peers.
3. **bidirectional `sync_direction`** — a fully bidirectional peer is preferred
   over an upload-/download-only one (it can serve every other peer).
4. **earliest `startup_time`** — the node that started first wins.
5. **lowest `cid`** lexicographically — a deterministic final tiebreaker.

If no candidate is eligible (every node is `never_master`) **no master is
elected**: `elect_master` returns `None`, the role becomes `NONE`, and a parsable
`[NO_MASTER]` warning is logged so front-ends can tell the user synchronization
cannot proceed.

### Edge cases

- **Incumbency vs force_master.** A serving incumbent (`server_ready=true`) beats
  a newcomer even if the newcomer sets `force_master`, because `server_ready`
  ranks above `force_master`. The pin still wins once both are at parity on
  readiness (scenario `incumbent-server-ready-wins-over-force-master`).
- **force_master conflict.** When more than one eligible candidate sets
  `force_master`, the best-ranked one wins and the others are logged as
  `[MASTER_CONFLICT]` (`conflict_won` / `conflict_lost`).
- **force_master takeover.** A remote `force_master` peer overriding the local
  non-`force_master` incumbent is logged as `[MASTER_TAKEOVER]`.
- **never_master.** Such nodes never serve. If they are the only candidates the
  result is `NO_MASTER` (scenario `all-never-master-no-master`).

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
  valid master and is refused (`[INSECURE_MASTER]`).
- `HSYNC_LAN_KEY` is a shared secret presented as a bearer token. It authenticates
  *writes* to the master, travels only over the (mandatory) encrypted transport,
  and is shared, not per-peer.

Identity is therefore established by **Trust On First Use (TOFU)** pinning, and
writes by an unattended client are gated on the shared key.

### Master identity (persistent)

A master's keypair is **persistent**, not per-session: `load_or_create_master_cert`
stores it in an OS state directory (`~/.local/state/hsync/lan_cert`, overridable
via `HSYNC_LAN_CERT_DIR`) and reuses it on every restart, so the fingerprint a
peer pinned on first use keeps matching instead of triggering a spurious
`[FINGERPRINT_CHANGED]` after each restart. The certificate is RSA, self-signed,
and valid for ~10 years — validity is an operational convenience only, since
trust comes from the pinned fingerprint rather than chain/date validation.

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
logs a parsable `[FINGERPRINT_CHANGED]` line, emits the structured event, and
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

### LAN-key write policy

Because a self-signed transport does not prove identity, an **unattended**
(non-interactive, `--yes`) client must authenticate write-capable sync with the
shared key. `lan_write_requires_key(sync_direction, interactive=...)` is the
canonical rule: a key is required when the run is **non-interactive** *and* the
direction writes to the master (`bidirectional` or `upload-only`). `download-only`
never writes and is always allowed.

The client enforces this before sync (`_check_lan_write_policy`): when an
unattended write lacks an effective `HSYNC_LAN_KEY` it logs `[AUTH_REQUIRED]`,
emits the `auth_required` event, and exits. Interactive runs keep the key
recommended, not required: the operator can vouch for the peer out of band.

### Explicit pairing (strict mode)

TOFU trusts a peer's *first* certificate automatically, which is convenient on a
trusted LAN but assumes no attacker was already present at first sighting. Strict
pairing (`HSYNC_LAN_REQUIRE_PAIRING` / client `LAN_REQUIRE_PAIRING` or the
`--require-pairing` CLI flag, Desktop *Require pairing* toggle, Android
`SyncConfig.lanRequirePairing`) closes that window by disabling the auto-pin
shortcut. `requires_pairing_confirmation(decision, require_pairing=...)` is the
canonical rule: it returns true only for a first sighting (`trusted`) while
strict pairing is on; `matched`/`changed` are unaffected.

When it triggers, the client logs `[PAIRING_NEEDED]`, emits the `pairing_needed`
event and stays in discovery without connecting. The operator confirms the peer
out of band — by pinning its fingerprint (or disabling strict pairing) — after
which the normal TOFU table applies.

### Security events

Security state is surfaced on the structured channel rather than by
scraping log wording: `fingerprint_changed` (pin mismatch, connection refused),
`auth_required` (unattended write without an effective key), and `pairing_needed`
(strict pairing: a first-seen certificate awaiting out-of-band confirmation).
