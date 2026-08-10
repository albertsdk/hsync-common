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

`IgnoreMatcher` combines three layers:

1. **Default hidden patterns** (files/dirs starting with `.`, swap files, …)
2. **Per-bucket `.hsyncignore`** file
3. **Extra patterns** provided programmatically (e.g. from CLI `--ignore-patterns`)

The sentinel `.hsynckeep` is always preserved regardless of any pattern.

Use `set_active_matcher()` / `get_active_matcher()` to install a process-wide
matcher; `should_skip(rel_path, is_dir)` is a convenience wrapper that falls
back to the legacy hidden-file check when no matcher is active.
