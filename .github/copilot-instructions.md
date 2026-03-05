# Copilot Instructions

## Required before commit or push

- Always run Ruff lint checks before committing or pushing changes.
- Command:

```bash
ruff check .
```

- If Ruff reports issues, fix them (or explicitly coordinate exceptions) before commit/push.

## Validation order

1. Run focused tests for changed areas.
2. Run `ruff check .`.
3. Commit only after lint and tests pass.
