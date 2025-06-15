# Delta transfer (rsync-style block sync)

`hsync-common` implements rsync-style block-level delta synchronisation so that
only the changed portions of a file are transferred when a previous version of
the same file already exists on the target peer.

## How it works

1. **Receiver** computes **block signatures** of the base file (weak Adler32 +
   strong SHA-256 for every block) and sends them to the sender.

2. **Sender** slides a window over the **new file**, computing a weak Adler32
   checksum at each position. When the weak checksum matches a base block
   signature, the **strong SHA-256** confirms the match and filters Adler32
   collisions. Consecutive unmatched bytes are coalesced into a single `data` op.

3. **Receiver** applies the delta operations: copy from the base file where
   possible, and write literal data for the changed portions (`apply_delta`).

## Package structure

| Module | Purpose |
|--------|---------|
| `hsync_common.delta.decision` | Block-size selection, change-ratio computation, worthwhileness gate. |
| `hsync_common.delta.rolling_checksum` | rsync-style rolling checksum engine, matching, and delta reconstruction. |
| `hsync_common.models.delta` | Wire models: `BlockSignature`, `DeltaOp`, `DeltaInstructions`, `DeltaApplyMetadata`. |

---

## API reference

### `hsync_common.delta.decision`

Pure functions shared by every component — no I/O, no peer state.

#### `optimal_block_size(file_size)`

Pick the adaptive block size for a base file of *file_size* bytes. Both peers
must derive the same value from the same base file size — signatures computed
with mismatched block sizes are incompatible.

```python
from hsync_common.delta.decision import optimal_block_size

optimal_block_size(500_000)  # 4096 (4 KB)  — < 1 MB
optimal_block_size(5_000_000)  # 16384 (16 KB) — 1–10 MB
optimal_block_size(50_000_000)  # 65536 (64 KB) — 10–100 MB
optimal_block_size(500_000_000)  # 262144 (256 KB) — > 100 MB
```

| Base file size | Block size |
|----------------|------------|
| < 1 MB | 4 KB |
| 1–10 MB | 16 KB |
| 10–100 MB | 64 KB |
| > 100 MB | 256 KB |

#### `changed_block_ratio(ops, base_size, block_size)`

Return the fraction of base blocks **not** reused by copy ops (0.0 = identical,
1.0 = everything changed). A base block is "reused" when at least one copy op
references its byte range.

```python
from hsync_common.delta.decision import changed_block_ratio

ratio = changed_block_ratio(ops, base_size, block_size)
# 0.0 → identical files (all blocks matched)
# 0.3 → 30% changed
# 1.0 → nothing reusable (full transfer cheaper)
```

#### `is_delta_worthwhile(ops, base_size, literal_size, block_size, *, max_change_ratio=0.50, max_literal_size=1GB)`

Decide whether a computed delta beats a full transfer. Returns `False` when:

- The literal payload exceeds `max_literal_size` (1 GB hard cap).
- More than `max_change_ratio` (50%) of base blocks changed.

In both cases a full transfer is cheaper than the delta overhead, and the sender
aborts back to a plain upload.

```python
from hsync_common.delta.decision import is_delta_worthwhile

if is_delta_worthwhile(ops, base_size, literal_size, block_size):
    # send delta instructions
else:
    # fall back to full transfer
```

---

### `hsync_common.delta.rolling_checksum`

The rsync-style rolling checksum engine.

#### `adler32_roll(prev_a, prev_b, window_size, byte_out, byte_in)`

Roll an Adler32 window forward by one byte in **O(1)**.

| Parameter | Type | Description |
|-----------|------|-------------|
| `prev_a` | `int` | `a` half (low 16 bits) of the previous Adler32. |
| `prev_b` | `int` | `b` half (high 16 bits) of the previous Adler32. |
| `window_size` | `int` | Window width in bytes (n). |
| `byte_out` | `int` | Byte leaving the window. |
| `byte_in` | `int` | Byte entering the window. |

Returns `(adler32, new_a, new_b)` — the combined value equals
`zlib.adler32` of the new window.

```python
from hsync_common.delta.rolling_checksum import adler32_roll

# Initialize from zlib.adler32
import zlib

window = new_data[0:block_size]
weak = zlib.adler32(window)
a = weak & 0xFFFF
b = (weak >> 16) & 0xFFFF

# Slide one byte forward
weak, a, b = adler32_roll(a, b, block_size, new_data[0], new_data[block_size])
```

#### `compute_signatures(filepath, block_size)`

Compute per-block signatures of the base file. Every block gets a weak Adler32
and a strong SHA-256; the final partial block (`length < block_size`) is included
with its real length — but it is never matched by the sliding window.

```python
from hsync_common.delta.rolling_checksum import compute_signatures

signatures = compute_signatures("/path/to/base_file", block_size=4096)
# [BlockSignature(index=0, offset=0, length=4096, weak=..., strong="abc..."),
#  BlockSignature(index=1, offset=4096, length=4096, weak=..., strong="def..."),
#  ...]
```

#### `build_signature_index(signatures, block_size)`

Index full-size signatures by weak checksum for **O(1)** candidate lookup. The
partial tail signature is excluded (it can never match a full window).

```python
from hsync_common.delta.rolling_checksum import build_signature_index

index = build_signature_index(signatures, block_size)
# {weak_checksum: [(offset, strong_hash), ...], ...}
```

#### `find_matches(new_data, signatures, block_size)`

Match *new_data* against the base signatures using a rolling Adler32 window.
Returns `(ops, literals)` — a list of `DeltaOp` and the literal payload bytes.

```python
from hsync_common.delta.rolling_checksum import find_matches

new_data = open("/path/to/new_file", "rb").read()
ops, literals = find_matches(new_data, signatures, block_size)
# ops: [copy(offset=0, length=4096), data(data_offset=0, length=512), ...]
# literals: b"..." (only the changed bytes)
```

#### `find_matches_file(new_path, signatures, block_size)`

mmap-backed variant of `find_matches()` for large new files. Uses OS memory
mapping so peak RAM stays bounded regardless of file size.

```python
from hsync_common.delta.rolling_checksum import find_matches_file

ops, literals = find_matches_file("/path/to/new_file", signatures, block_size)
```

#### `apply_delta(base_path, ops, literal_data, output_path)`

Rebuild the new file from base copy ops + literal data ops. Copy ops are streamed
through a bounded buffer (64 KB); `literal_data` may be an in-memory buffer or a
seekable binary stream so large payloads never need to be resident in RAM.

Returns the number of bytes written; the caller should verify the whole-file
SHA-256 after reconstruction.

```python
from hsync_common.delta.rolling_checksum import apply_delta

bytes_written = apply_delta(base_path, ops, literals, output_path)
```

---

## See also

- [Constants](constants.md) — delta transfer constants (block sizes, thresholds, security caps).
- [Models guide](models.md) — delta wire models (`BlockSignature`, `DeltaOp`, `DeltaInstructions`, `DeltaApplyMetadata`).
- [ADR 0016 — Delta transfer](internal/adr/0016-delta-transfer.md) — rationale and design decisions.
