# hsync-common

Shared models, constants, compression utilities, and ignore-file support for the HSYNC ecosystem.

## Key modules

| Module | Purpose |
|--------|---------|
| `hsync_common.models` | Unified `File`, `Dir`, `Symlink`, `Event`, `SyncAction`, `Tombstone` models |
| `hsync_common.compression` | Zstandard helpers, `PRECOMPRESSED_EXTENSIONS`, `should_compress` |
| `hsync_common.ignore` | `.hsyncignore` gitignore-style matcher (`IgnoreMatcher`) |
| `hsync_common.constants` | Shared constants (`HSYNCKEEP_FILENAME`, `HSYNCIGNORE_FILENAME`, `HSYNCTOMBSTONES_FILENAME`, …) |
| `hsync_common.ssl_utils` | Shared SSL primitives |
| `hsync_common.logger` | `BaseInterceptHandler`, log rotation helpers |
| `hsync_common.exceptions` | `HSyncError` base class |
| `hsync_common.path_validation` | Path safety helpers |
| `hsync_common.env` | Environment-variable parsing helpers |
| `hsync_common.text` | Text utilities (e.g. `escape_loguru_braces`) |

## Ignore file (`.hsyncignore`)

Place a `.hsyncignore` file in the root of a bucket to control which files are
excluded from sync.  The syntax is identical to `.gitignore`:

```
# Ignore build artefacts
/dist/
*.pyc

# Re-include a specific file
!important.log
```

`IgnoreMatcher` combines three layers:

1. **Default hidden patterns** (files/dirs starting with `.`, swap files, …)
2. **Per-bucket `.hsyncignore`** file
3. **Extra patterns** provided programmatically (e.g. from CLI `--ignore-patterns`)

The sentinel `.hsynckeep` is always preserved regardless of any pattern.

Use `set_active_matcher()` / `get_active_matcher()` to install a process-wide
matcher; `should_skip(rel_path, is_dir)` is a convenience wrapper that falls
back to the legacy hidden-file check when no matcher is active.

## License

[Mozilla Public License 2.0](LICENSE)
