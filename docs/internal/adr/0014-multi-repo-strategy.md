# ADR 0014 — Multi-repository architecture

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

HSYNC comprises five distinct components:

- `hsync-common` — shared models, constants, protocol, compression (Python
  library, mirrored in Kotlin for Android).
- `hsync-server` — FastAPI server for centralized sync (Python).
- `hsync-client` — CLI sync engine for desktop/server mode (Python).
- `hsync-desktop` — PySide6 GUI that drives the client as a subprocess
  (Python).
- `hsync-android` — Kotlin Android app (mirrors the client logic).

These components have different release cadences, different audiences, and
different language toolchains. The repository structure decision affects CI/CD
complexity, dependency management, and contributor onboarding.

Options:

- **Monorepo** — all components in one repository. Pros: atomic commits across
  components, single CI, easy cross-component refactoring. Cons: large clone,
  mixed toolchains (Python + Kotlin + Gradle) in one repo, difficult to
  version/release independently.
- **Multi-repo** — each component in its own repository. Pros: independent
  versioning, smaller clones, language-specific CI, clear ownership. Cons:
  cross-repo changes need multiple PRs, harder to ensure compatibility.
- **Hybrid** — `hsync-common` + one other in a monorepo, the rest separate.
  Adds inconsistency without solving the core problem.

## Decision

We will use a **multi-repository architecture** with five independent
repositories, linked by `hsync-common` as the single source of truth for shared
code:

- **`hsync-common`** is a Python package consumed as a **path dependency**
  (`hsync-common = { path = "../hsync-common", develop = true }`) by the Python
  projects, and mirrored in Kotlin for Android with parity tests.
- **Cross-repo compatibility** is enforced by:
  - **ADR golden fixtures** (e.g. `protocol/fixtures/p2p-election-scenarios.json`,
    `p2p-pairing-scenarios.json`) replayed in both Python and Kotlin tests.
  - **Protocol versioning** ([ADR-0005](0005-protocol-versioning.md)): breaking
    changes bump a protocol version and cause hard-fail, preventing silent drift.
  - **ADRs in `hsync-common`**: all architectural decisions that span
    repositories are recorded here, in the shared repo.
- **Release independence**: each repo is versioned and released separately.
  `hsync-common` follows strict SemVer; consumers pin a range.
- **Documentation cross-links**: documentation files reference each other via
  absolute GitHub URLs (not relative paths) so links work when viewed on
  GitHub's web UI, where each repo is rendered independently.

Alternatives rejected:

- **Monorepo**: would couple release cycles — a server bugfix would require
  rebuilding the Android app. Mixed build systems (Poetry + Gradle) in one CI
  pipeline add complexity. The clone size would include all components for
  contributors who only need one.
- **Hybrid**: choosing which components to group is arbitrary; the inconsistency
  confuses contributors.

## Consequences

- **Atomic cross-repo changes are impossible** — a change to
  `hsync-common` that affects all consumers requires coordinated PRs and careful
  merge ordering. Protocol versioning and golden fixtures mitigate the risk of
  incompatible merges.
- **Each repo has its own CI/CD** — simpler to configure (one language per
  pipeline) but requires duplication of some workflows (linting, pre-commit
  hooks).
- **Contributors clone only what they need** — an Android developer doesn't
  need to clone the server; a server operator doesn't need the Android SDK.
- **Documentation must be careful with cross-references** — relative paths work
  locally (if repos are cloned as siblings) but fail on GitHub. Absolute URLs
  are the canonical form.
- **`hsync-common` is the integration point** — all cross-repo contracts
  (models, protocol, ADRs, fixtures) live here, making it the most critical
  repository for ecosystem consistency.

## See also

- [ADR-0005](0005-protocol-versioning.md) — how protocol versioning prevents
  drift across repos.
- [ADR-0004](0004-desktop-subprocess-contract.md) — desktop↔client contract
  across `hsync-desktop` and `hsync-client`.
- [ADR-0002](0002-p2p-master-election.md) — cross-language election algorithm
  mirrored in Python and Kotlin.
