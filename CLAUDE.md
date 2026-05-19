# CLAUDE.md — hsync-common

## Pre-commit workflow

This project uses pre-commit hooks with ruff (`ruff --fix` and `ruff-format`).
When ruff auto-fixes files during `git commit`, the commit aborts because files
were modified. **This is expected behavior.** Do NOT treat this as a failure.

### Before committing, always follow this sequence:

1. Run ruff auto-fix: `ruff check --fix .`
2. Run ruff format: `ruff format .`
3. Stage any changes ruff made: `git add -A`
4. Commit: `git commit ...`
5. If pre-commit hooks still modify files (step 4 fails), re-stage and retry:
   ```
   git add -A
   git commit ...
   ```

### Quick path — use the project wrapper script:

```
bash ../../scripts/dev/commit.sh hsync-common -m "type(scope): message"
