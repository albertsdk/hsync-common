## Description

Brief summary of the changes and why they are needed.

## Type of change

- [ ] Bug fix (non-breaking change)
- [ ] New feature / model / utility (non-breaking change)
- [ ] Breaking change (protocol, model schema, or constant change)
- [ ] Documentation update
- [ ] Internal refactor

## Checklist

- [ ] Tests pass locally (`poetry run pytest`)
- [ ] Code is linted (`poetry run ruff check --fix . && poetry run ruff format .`)
- [ ] Cross-project impact assessed:
  - [ ] `hsync-client` tests pass with this change
  - [ ] `hsync-server` tests pass with this change
- [ ] Kotlin mirror updated if model/constant changed (`hsync-android`)
- [ ] Cross-language test fixtures updated if protocol changed
- [ ] `CHANGELOG.md` updated under `## [Unreleased]` if the change is user-facing
- [ ] `docs/android-mirroring.md` updated if mirrored components changed

## Related issues

Closes # (issue number) or N/A.
