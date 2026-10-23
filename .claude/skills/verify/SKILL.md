---
name: verify
description: Run the full local equivalent of this repo's Python CI (lockfile, ruff lint, ruff format check, mypy, pytest, CLI smoke) and report results honestly. Use before committing or when asked to verify changes.
---

Run each step from the repo root, in order. Keep going after a failure so the report covers every gate.

1. `uv lock --check`
2. `uv sync --locked --extra dev`
3. `uv run --extra dev ruff check .`
4. `uv run --extra dev ruff format --check .`
5. `uv run --extra dev mypy`. Also confirm that every new or renamed module under `src/pdf2audiobook/` appears in `[tool.mypy].files` in `pyproject.toml`.
6. `uv run --extra dev pytest -q` (or the narrower path in `$ARGUMENTS`, if one is given).
7. CLI smoke:
   - `uv run --extra dev pdf2audiobook --help`
   - `uv run --extra dev pdf2audiobook config show --json`
   - `uv run --extra dev pdf2audiobook doctor --json`

Report a pass/fail table, one row per step, with the relevant error output for each failure. Use pytest's `-ra` summary to list skipped tests, and call out any skips caused by a missing `ffmpeg` or `tesseract` binary. Those paths were not exercised locally, though CI does install both.

Do not claim CI passed. This is a local check only, and real CI evidence comes from `/record-ci-evidence`.
