# Contributing to hsync-common

Thanks for your interest in contributing! `hsync-common` is the shared library
(models, constants, compression, and utilities) used by the other HSYNC
components, so changes here must stay consistent across the ecosystem.

## Prerequisites

- Python `>=3.12,<3.15` (lint/CI target: **3.13**)
- A committed virtualenv at `.venv/` (no Poetry required)

## Setup

The project ships a committed virtualenv at `.venv/`. All tooling is invoked
through it as `.venv/bin/python -m <tool>` — exactly as the root `Makefile`
does. No Poetry installation is required.

## Code Style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and
formatting (line length 100, target `py313`), enforced via pre-commit hooks.

```bash
.venv/bin/python -m ruff check --fix .
.venv/bin/python -m ruff format .
```

## Pre-commit Workflow

Pre-commit hooks run ruff (and an end-of-file fixer) on commit. When a hook
auto-fixes files, the commit aborts because files changed — **this is expected,
not a failure**. Re-stage and commit again:

```bash
.venv/bin/python -m ruff check --fix .
.venv/bin/python -m ruff format .
git add -A
git commit -m "type(scope): message"
# if hooks modified files and the commit aborted, re-stage and retry:
git add -A
git commit -m "type(scope): message"
```

## Tests

```bash
# Run the full test suite
.venv/bin/python -m pytest

# Run a specific test file
.venv/bin/python -m pytest tests/test_models.py

# Run with coverage report
.venv/bin/python -m pytest --cov=hsync_common --cov-report=term-missing

# Run a test matching a keyword
.venv/bin/python -m pytest -k "protocol"
```

### Test structure

All tests live at the project root under `tests/`. The suite is organised by
area; each file name starts with `test_` and groups related functionality.

| Area | Key files | What they cover |
|------|-----------|-----------------|
| **Protocol / wire** | `test_handshake.py`, `test_protocol_lan.py`, `test_protocol_pairing.py`, `test_protocol_schemas.py`, `test_protocol_fixtures.py`, `test_capabilities.py` | WS handshake, LAN election/pairing, schema fixtures, capabilities |
| **Models** | `test_models.py` | Data model validation (file, dir, tombstone, sync_action, event) |
| **Path validation / security** | `test_path_validation.py`, `test_permissions.py`, `test_ssl_utils.py` | Path traversal prevention, permissions, SSL utils |
| **Delta transfer** | `test_delta.py`, `test_delta_transfer.py` | Delta signatures, block matching, apply |
| **Compression** | `test_compression.py` | Zstandard compression/decompression |
| **Config / env** | `test_env.py`, `test_constants.py`, `test_version.py` | Environment loading, constants, version |
| **Utils** | `test_clock.py`, `test_events.py`, `test_exceptions.py`, `test_format.py`, `test_hashing.py`, `test_ignore.py`, `test_logger.py`, `test_text.py` | Clock sync, events, exceptions, formatting, hashing, ignore patterns, logging, text utils |
| **Docs** | `test_check_doc_links.py` | Documentation link checker |
| **Shared** | `tests/conftest.py` | Shared fixtures |

### Cross-project testing

`hsync-common` is the single source of truth for shared models and the wire
protocol. When you change a model or protocol constant, run the downstream
test suites to verify nothing breaks:

```bash
cd ../hsync-client && .venv/bin/python -m pytest
cd ../hsync-server && .venv/bin/python -m pytest
```

## Documentation

HSYNC maintains two documentation sets that must stay in sync with the code:

- `llm-wiki/` — internal agent knowledge base (architecture, modules, data models)
- `docs/` — end-user technical documentation

Any change that affects architecture, contracts, configuration, or behavior
must update the relevant files in both sets within the same change.

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):
`type(scope): summary` (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`, …).

## Pull Requests

- Keep changes focused and covered by tests.
- `hsync-common` is the single source of truth for shared models and the wire
  protocol. The project follows a **Zero Backward Compatibility** policy: when
  a contract intentionally changes, update all affected consumers atomically
  (client, server, desktop, Android mirrors, fixtures, schemas, and docs).
- Ensure `ruff` and `pytest` pass locally before opening a PR.
