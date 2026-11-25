# Ignore file (`.hsyncignore`)

Place a `.hsyncignore` file in the root of a bucket to control which files are
excluded from sync.  The syntax is identical to `.gitignore`:

```
# Ignore build artefacts
/dist/
*.pyc

# Re-include a specific file
!important.log
```

## Layered matching

`IgnoreMatcher` combines three layers:

1. **Default hidden patterns** — built-in patterns for OS cache files
   (`.DS_Store`, `Thumbs.db`, …) and editor/office temporary files. These are
   **always active** and cannot be disabled. Dotfiles in general (`.env`,
   `.config`, …) are **not** excluded: they are synchronised normally.
2. **Per-bucket `.hsyncignore`** — user-defined rules in the bucket root.
3. **Extra patterns** — programmatic patterns (e.g. from CLI `--ignore-pattern`).

The sentinel `.hsynckeep` is always preserved regardless of any pattern.

## Engine-owned artifacts

The following files are **never** synced, regardless of any ignore pattern:

| File | Purpose |
|------|---------|
| `.hsyncignore` | The ignore file itself (not synced across peers) |
| `.hsyncfolder` | Folder-identity marker (UUIDv4); causal state lives outside the bucket |
| `.hsyncstate` | Legacy name; rejected so an old peer cannot plant it |
| `.hsynctombstones` | Legacy name; rejected so an old peer cannot plant it |
| `*.part` | In-progress download artifacts |
| `*.delta.part` | In-progress delta reconstruction artifacts |

## ReDoS protection

The ignore matcher enforces a maximum of 1000 total patterns (defaults +
`.hsyncignore` + extras). Beyond this cap, remaining patterns are silently
dropped and a warning is emitted. This prevents a crafted `.hsyncignore` with
thousands of complex regex-compiled globs from degrading scanning performance.

---

## API reference

### `IgnoreMatcher`

```python
from hsync_common.ignore import IgnoreMatcher
```

`IgnoreMatcher` is a gitignore-style matcher bound to a **bucket root**. All
paths passed to `matches()` are normalised relative to that root before being
tested against the loaded rules.

| Parameter | Type | Description |
|-----------|------|-------------|
| `bucket_root` | `str` | Absolute path of the directory being synchronised. |
| `extra_patterns` | `Iterable[str] \| None` | Additional patterns from e.g. `--ignore-pattern`. |

```python
matcher = IgnoreMatcher("/home/user/sync-bucket", extra_patterns=["*.log"])
```

#### `matches(path, is_dir=False)`

Return `True` when *path* should be **excluded** from sync.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | File or directory path (absolute or bucket-relative). |
| `is_dir` | `bool` | When `True` a trailing slash is appended so gitignore directory-only patterns (`foo/`) match. |

```python
matcher.matches(".DS_Store")  # True (default pattern)
matcher.matches("build/output.o")  # True if .hsyncignore has "build/"
matcher.matches("important.log")  # False (no matching rule)
matcher.matches(".hsynckeep")  # Always False (sentinel preserved)
```

#### `reload()`

Re-read `.hsyncignore` from disk and rebuild the internal pattern spec. Called
automatically by `__init__`; intended to be invoked by client code (or a file
watcher) whenever the ignore file changes on disk.

```python
matcher.reload()  # re-parse .hsyncignore after external modification
```

The master sync engine calls `reload()` after every reconcile cycle so that
`.hsyncignore` changes take effect without restarting (hot-reload).

### Module-level singleton

The module provides a process-wide `IgnoreMatcher` singleton so that utility
functions like `is_hidden_dir()` in the models can consult the active ignore
rules without receiving a matcher reference explicitly.

#### `set_active_matcher(matcher)`

Install *matcher* as the process-wide active matcher. Pass `None` to clear it,
which causes `should_skip()` to fall back to the built-in default patterns only.

```python
from hsync_common.ignore import set_active_matcher, IgnoreMatcher

set_active_matcher(IgnoreMatcher(bucket_root))
```

#### `get_active_matcher()`

Return the currently active `IgnoreMatcher`, or `None` if none is installed.

#### `should_skip(path, is_dir=False)`

Convenience entry point used by sync engines. Delegates to the active
`IgnoreMatcher` when one is installed, otherwise falls back to the built-in
default patterns.

```python
from hsync_common.ignore import should_skip

if should_skip("Thumbs.db"):
    # skip this file
    pass
```
