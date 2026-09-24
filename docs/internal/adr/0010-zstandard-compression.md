# ADR 0010 — Zstandard compression with adaptive thresholds

- **Status:** Accepted
- **Date:** 2026-07-02

## Context

File synchronization over the network benefits from compression — smaller
payloads mean faster transfers and less bandwidth. However, compression is not
free: it consumes CPU on both sides and is useless (or even counterproductive)
for files that are already compressed. The choice of algorithm and when to apply
it matters.

Options considered:

- **gzip** — universal, built into HTTP (`Content-Encoding: gzip`), but slower
  and lower ratio than modern alternatives.
- **Brotli** — excellent ratio, but asymmetric: compression is very slow, making
  it unsuitable for on-the-fly compression of arbitrary files during sync.
- **Zstandard (zstd)** — developed by Facebook/Meta, offers a wide speed/ratio
  spectrum, symmetric performance (compress ≈ decompress), and fast
  dictionaries. Compression level 3 is a good default balance.

Beyond algorithm choice, applying compression blindly to all files wastes CPU on
already-compressed formats (`.zip`, `.gz`, images, videos) and small files where
the overhead exceeds the savings.

## Decision

We will use **Zstandard (zstd) at compression level 3** with **adaptive
thresholds** that vary by context:

- **Algorithm**: Zstandard via the `zstandard` Python library (C extension for
  speed), exposed through `hsync_common.compression`.
- **Thresholds** (configurable via constants in `compression.py`):
  - **Upload**: 32 KB — client CPU is more precious than server CPU; only
    compress files where savings clearly outweigh cost.
  - **Download**: 10 KB — server CPU is more abundant; compress even smaller
    files.
  - **p2p mode**: 100 KB — local network is fast (1 Gbps+); below 100 KB the
    compression time exceeds the transfer time saved.
- **Precompressed extension list** (`PRECOMPRESSED_EXTENSIONS`): a hardcoded set
  of 30+ file extensions (`.zip`, `.gz`, `.jpg`, `.png`, `.mp4`, `.apk`, etc.)
  that are never compressed because their formats are already compressed.
- **Content-Encoding header**: `zstd` is advertised via `Content-Encoding: zstd`
  and negotiated per-request.
- The capability `compression` is advertised via the protocol handshake
  ([ADR-0005](0005-protocol-versioning.md)) so peers can detect support.

Alternatives rejected:

- **gzip**: slower, lower ratio, no advantage over zstd for this use case.
- **Brotli**: great for static web assets (pre-compressed once, served many
  times) but terrible for on-the-fly sync where compression speed matters.
- **No compression**: wasteful on bandwidth, especially for text/log/config
  files that compress 5-10x.
- **Single threshold for all contexts**: the optimal trade-off differs between
  upload (client CPU is precious), download (server CPU is cheap), and p2p
  (network is fast).

## Consequences

- The three-tier threshold system optimizes for the asymmetric nature of
  client-server sync: the server does more compression work, the client does
  less.
- The precompressed extension list is **manually maintained** — new compressed
  formats must be added explicitly. A false negative (compressing an already
  compressed file) costs CPU with no size reduction; a false positive (not
  compressing a compressible file) only costs bandwidth.
- Zstandard requires the `zstandard` Python package on both client and server,
  and the C extension may need compilation on some platforms (pre-built wheels
  cover most).
- The `compression` capability flag lets clients that don't have zstd installed
  still sync (just without compression), maintaining compatibility.

## See also

- [ADR-0005](0005-protocol-versioning.md) — capability negotiation includes
  `compression`.
- [hsync_common/compression.py](https://github.com/albertsdk/hsync-common/blob/main/hsync_common/compression.py) —
  the canonical implementation.
