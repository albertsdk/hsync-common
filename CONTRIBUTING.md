# Contributing to hsync-common

Thanks for your interest in contributing! `hsync-common` is the shared library
(models, constants, compression, and utilities) used by the other HSYNC
components, so changes here must stay backward compatible across the ecosystem.

## Prerequisites

- Python `>=3.12,<3.15` (lint/CI target: **3.13**)
- [Poetry](https://python-poetry.org/) for dependency management

## Setup

```bash
poetry install
```

## Code Style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and
formatting (line length 100, target `py313`), enforced via pre-commit hooks.

```bash
poetry run ruff check --fix .
poetry run ruff format .
```

## Pre-commit Workflow

Pre-commit hooks run ruff (and an end-of-file fixer) on commit. When a hook
auto-fixes files, the commit aborts because files changed — **this is expected,
not a failure**. Re-stage and commit again:

```bash
poetry run ruff check --fix .
poetry run ruff format .
git add -A
git commit -m "type(scope): message"
# if hooks modified files and the commit aborted, re-stage and retry:
git add -A
git commit -m "type(scope): message"
```

## Tests

```bash
poetry run pytest
```

If the project configures mypy (see `pyproject.toml`), also run
`poetry run mypy .`.

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):
`type(scope): summary` (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`, …).

## Pull Requests

- Keep changes focused and covered by tests.
- Preserve backward compatibility — both `hsync-client` and `hsync-server`
  depend on this package via a Poetry path dependency.
- Ensure `ruff` and `pytest` pass locally before opening a PR.
