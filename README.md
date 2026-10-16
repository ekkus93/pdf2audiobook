# pdf2audiobook

Python CLI project for converting PDF books into chapter-separated MP3 audiobooks. Planned features include OCR, chapter detection, optional LLM support for OpenAI/Ollama/llama-server, and Kitten TTS.

**Status:** Early development. See the [specification](docs/PDF2AUDIOBOOK_SPEC.md) and [implementation TODO](docs/PDF2AUDIOBOOK_TODO.md). Conversion is not complete yet.

## Development with uv

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+; uv manages the local `.venv` and dependencies.

~~~bash
uv python install 3.11
uv sync --extra dev
uv run pdf2audiobook --help
uv run pdf2audiobook doctor
uv run pdf2audiobook config show --sources
uv run pytest -q
uv run ruff check .
~~~

The `uv sync` command creates/manages `.venv` automatically. You can also explicitly create one with `uv venv`. To use Kitten TTS later, run `uv sync --extra kitten --extra dev`; that may download a large model and additional dependencies. FFmpeg and Tesseract are installed separately at the OS level.

The default LLM provider is local Ollama; OpenAI requires explicit consent before transmitting book contents. See the specification for privacy and audit requirements.

**Lockfile:** `uv.lock` is not checked in yet and must be generated with `uv lock` in an environment with PyPI connectivity, then committed. CI currently resolves dependencies when running `uv sync --extra dev`.
