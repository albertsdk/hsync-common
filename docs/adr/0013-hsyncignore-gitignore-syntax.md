# ADR 0013 — `.hsyncignore` using gitignore syntax

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

Users need to exclude certain files and directories from synchronization:
build artifacts (`node_modules/`, `target/`), editor temp files (`*.swp`,
`.vscode/`), OS metadata (`.DS_Store`, `Thumbs.db`), and sensitive files
(`.env`, `*.key`). An ignore mechanism is required, and the syntax choice
affects learnability and compatibility.

Options:

- **Custom glob syntax** — full control, but every user must learn a new syntax.
- **Regex patterns** — powerful but error-prone for non-technical users.
- **gitignore syntax** — already known by virtually every developer; well-tested
  pattern matching libraries exist; users can copy their existing `.gitignore`.
- **No ignore support** — forces users to move excluded files outside the sync
  directory, which is impractical.

## Decision

We will use **gitignore-compatible syntax** for `.hsyncignore` files, placed at
the root of each sync directory:

- The ignore logic is implemented in `hsync_common.ignore` using
  `pathspec.PathSpec` (the same library Git uses internally), guaranteeing
  exact compatibility with `.gitignore` patterns.
- Standard gitignore features are supported: `*` wildcards, `**` for recursive
  matching, `/` for root-anchored patterns, `!` for negation, `#` for comments.
- The file is named `.hsyncignore` (not `.gitignore`) to avoid conflating sync
  ignores with Git ignores — they serve different purposes.

Alternatives rejected:

- **Custom glob syntax**: adds learning curve; users would need to read docs
  instead of reusing existing knowledge.
- **Regex**: too error-prone; escaping issues, no built-in negation, and
  poor UX for directory-level patterns.
- **Reusing `.gitignore` directly**: tempting but dangerous — a file excluded
  from Git (e.g. `.env`) might need to be synced, or vice versa. Separate files
  keep concerns separated.

## Consequences

- **Zero learning curve for developers** — `.hsyncignore` is literally a
  `.gitignore` with a different name. Migration from Syncthing's `.stignore` or
  rsync's `--exclude` is straightforward.
- **Pattern matching is exact** — the same `pathspec` library Git uses ensures
  no subtle incompatibilities.
- **Separate from `.gitignore`** means users must maintain two files if their
  sync and Git ignore lists differ, but this is the correct trade-off: sync
  ignores and VCS ignores are different concerns.
- **No per-directory `.hsyncignore`** — only the root file is read. This
  simplifies implementation and avoids ordering/merge complexity. If needed
  later, nested ignore files could be added without breaking compatibility.

## See also

- [hsync_common/ignore.py](https://github.com/albertobasso/hsync-common/blob/main/hsync_common/ignore.py) —
  implementation.
- [Migration Guide](https://github.com/albertobasso/hsync-client/blob/main/docs/migration.md) —
  examples of converting `.stignore` and `--exclude` patterns.
