# pdf2audiobook

Python CLI project for converting PDF books into chapter-separated MP3 audiobooks. Planned features include OCR, intelligent chapter boundaries, LLM support for OpenAI/Ollama/llama-server, and Kitten TTS.

**Status:** Early development. See [technical specification](docs/PDF2AUDIOBOOK_SPEC.md) and [implementation checklist](docs/PDF2AUDIOBOOK_TODO.md).

## Development

Requires Python 3.11+. The Kitten TTS model, FFmpeg and Tesseract are separate runtime requirements.

~~~bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pdf2audiobook --help
pdf2audiobook doctor
pytest -q
ruff check .
~~~

Local-only and remote-consent safety are described in the specification. No cloud API access is needed for automated tests.
