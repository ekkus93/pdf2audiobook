# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Authoritative docs: `docs/PDF2AUDIOBOOK_SPEC.md` (contracts, precedence, §12 engineering principles) and `docs/PDF2AUDIOBOOK_TODO.md` (dependency-ordered P0–P5 checklist; follow its "Working rules").

## Commands

Use uv only; never install into the system interpreter. These mirror `.github/workflows/ci.yml` (run all of them via `/verify`):

- `uv lock --check` then `uv sync --locked --extra dev`
- `uv run --extra dev ruff check .` (import sorting `I` is enforced — a frequent CI failure in new tests)
- `uv run --extra dev ruff format --check .`: formatting is enforced repository-wide (a PostToolUse hook formats edited `.py` files).
- `uv run --extra dev mypy`: checks the explicit `[tool.mypy].files` list in `pyproject.toml`. **Add every new module under `src/` to that list.**
- `uv run --extra dev pytest -q`
- CI runs on Python 3.11, 3.12 and 3.13 and runs mypy once per version (`mypy --python-version X`). Locally only 3.11 is checked.
- CI also runs a CLI smoke (`--help`, `config show --json`, `doctor --json`) and a clean-venv wheel/sdist install smoke using `--no-config`. `/verify` doesn't cover the packaging smoke, so packaging regressions only show up in CI.
- `tests/conftest.py` has an autouse fixture that stubs `OpenAICompatibleProvider._ollama_served_context`. Mark a test `@pytest.mark.ollama_context` to exercise the real lookup.
- Kitten TTS needs `uv sync --extra kitten --extra dev`; tests mock it.
- Tests needing `ffmpeg`/`tesseract` skip silently when the binaries are absent — check the `-ra` skip summary before claiming coverage.
- Live LLM smoke (`python -m pdf2audiobook.llm.smoke ... --execute`) is opt-in and never part of CI; CI must not depend on the network.

## Invariants that are easy to break

- Privacy: errors and logs must be content-free — never echo book text, private paths, or raw filesystem exception text. Many `tests/test_*_privacy.py` enforce this; add one when introducing a new error path.
- `--json` output must stay parseable: silence third-party stdout (PyMuPDF, kittenml) at the adapter (see `tests/test_third_party_stdout_privacy.py`).
- PDF text and LLM output are untrusted data, never instructions. LLM edits are proposals (`accepted=false`) until a human accepts them; never invent or silently drop book text.
- `manually_approved`/`approved` manifest entries block destructive reanalysis even with `--no-resume`/`--force`.
- Resume is content-addressed: changing derived semantics requires a fingerprint or schema-version bump. Old manifest versions are rejected, not migrated.
- JSON writes are atomic and reject NaN/Infinity. Cached reads are size- and depth-bounded (see `llm/cache.py`, `audio/__init__.py`); bad cache entries are misses, not errors.
- Budget ledger fails closed and uses exact `Decimal` cost math.
- Remote LLM content requires `--allow-remote-content`; plain HTTP to non-loopback hosts is always refused. PDF passwords are passed as an env-var *name*.

## Workflow

- Commit directly to `master`. Conventional Commits (scope when one fits), lowercase imperative subject, no body (e.g. `fix(llm): ...`, `test(audio): ...`, `style(test): ...`).
- After CI finishes for a pushed fix, record evidence in a separate `docs: record ... CI evidence` commit by appending a row to the "Progress ledger" table at the end of `docs/PDF2AUDIOBOOK_TODO.md` (use `/record-ci-evidence`). Use the full 40-char SHA and real run numbers/IDs, including failed attempts. Never invent CI results and never add duplicate rows.
- Mark TODO items `[x]` only with an implementation plus verified tests/evidence. Otherwise mark partial in the ledger.
- Keep `docs/MAINTAINER_GUIDE.md` current when a change touches what it describes. If the CI apt package list changes, bump the `apt-…-v1` cache key in `ci.yml`.
