# Repository Guidelines

## Project Structure & Module Organization

This Python 3.11+ CLI package uses a `src` layout. Runtime code lives in `src/pdf2audiobook/`: `document/` handles structure, `audio/` and `tts/` handle speech output, and `llm/` contains model adapters. The CLI entry point is `cli.py`; conversion is coordinated by `pipeline.py`. Pytest tests are in `tests/`; specifications and maintainer guidance are in `docs/`.

## Build, Test, and Development Commands

Use `uv` to manage the environment and dependencies:

- `uv sync --locked --extra dev` installs the pinned development environment.
- `uv run pdf2audiobook --help` shows CLI commands; `uv run pdf2audiobook doctor` checks prerequisites.
- `uv run pytest -q -ra` runs the offline test suite and reports skip reasons.
- `uv run ruff check .` checks lint and import ordering; `uv run mypy` runs configured type checks.
- `uv lock --check` verifies dependency declarations against `uv.lock`. After dependency changes, regenerate with `uv lock` and review the diff.

OCR and audio workflows may require Tesseract and FFmpeg. Optional Kitten TTS installs with `uv sync --extra kitten --extra dev`.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations on runtime interfaces, and Ruff's 100-character line limit. Ruff checks E4, E7, E9, F, and I. Use `snake_case` for modules, functions, and variables; use `PascalCase` for classes. Follow existing adapter and configuration patterns.

## Testing Guidelines

Add pytest tests in `tests/` named `test_*.py` with `test_*` functions. Prefer deterministic offline fixtures; live LLM smoke tests are opt-in and must stay out of the default suite. Run the relevant module and, for broad changes, `uv run pytest -q`. No coverage threshold is configured.

## Commit & Pull Request Guidelines

Recent history uses concise Conventional Commit-style prefixes, such as `fix(llm): ...`, `feat(document): ...`, and `docs: ...`. Keep commits focused. Pull requests should explain the problem and change, list validation and results, link issues when available, and include CLI examples or screenshots for user-facing changes.

## Security & Configuration

Never commit API keys, PDF passwords, private source documents, workspaces, or model caches. Pass secrets through environment variables and obtain explicit remote-content consent before sending book text to an external LLM. Review LLM cleanup suggestions before applying them.
