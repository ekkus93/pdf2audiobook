---
name: lint-n-test
description: Lint the files and run all tests (ruff lint, ruff format check, full pytest suite) and report the results. Use for a quick lint-and-test pass; use /verify for the full CI gate.
model: haiku
---

Run these from the repo root, in order. Keep going after a failure so the report covers everything.

1. `uv run --frozen --extra dev ruff check .`
2. `uv run --frozen --extra dev ruff format --check .`
3. `uv run --frozen --extra dev pytest -q`

This skill only reports. Do not edit files, apply `--fix`, or commit.

Report:
- PASS or FAIL for each step.
- For lint failures: each `file:line` and rule code.
- For test failures: each failing test's node ID with a one-line reason.
- The skipped-test count from pytest's `-ra` summary, noting any skips caused by a missing `ffmpeg` or `tesseract`.
