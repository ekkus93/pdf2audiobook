# pdf2audiobook

Turn a PDF or EPUB book into one tagged MP3 per chapter, or a single M4B with chapter navigation.
Text extraction, OCR and speech synthesis run locally. Optional LLM assistance uses local
Ollama by default; sending book content to a remote service requires explicit consent.

Review chapter boundaries and text in your browser before synthesis. LLM cleanup and equation
readings remain proposals until you approve them.

## Quick start

Install [uv](https://docs.astral.sh/uv/), Python 3.11+, and FFmpeg. Scanned PDFs also need
Tesseract with the appropriate language pack. On Debian/Ubuntu:

```bash
sudo apt install ffmpeg tesseract-ocr tesseract-ocr-eng
```

From a checkout of this repository:

```bash
uv python install 3.11
uv sync --locked --extra kitten --extra dev
uv run pdf2audiobook doctor
uv run pdf2audiobook analyze book.pdf --no-llm
```

Kitten is the default speech provider; its model downloads on first synthesis. After that,
conversion can run offline. Keep `--extra kitten` in subsequent `uv sync` commands to retain it.
See [installation and the illustrated walkthrough](docs/guides/getting-started.md) for details.

Analysis prints the workspace path under `./audiobooks/`. Replace `BOOK` below with that folder
name, open the review URL, check the chapters, and save reviewed boundaries. Stop the review
server with Ctrl+C, then convert and optionally package the audio:

```bash
uv run pdf2audiobook review ./audiobooks/BOOK/manifest.json
uv run pdf2audiobook convert book.pdf --no-llm
uv run pdf2audiobook pack-m4b ./audiobooks/BOOK/manifest.json --output book.m4b
```

Conversion stops for unresolved review issues. Read the reported issue and use the
[review guide](docs/guides/editing-and-review.md) before retrying. Finished chapters are reused
when you run conversion again.

Optional [local voice cloning](docs/guides/voice-cloning.md) uses the full KittenTTS 2 model;
the default small model keeps its built-in voices.

## Configuration

Save recurring settings in `~/.config/pdf2audiobook/config.toml` (or under `XDG_CONFIG_HOME`).
The [configuration guide](docs/guides/configuration.md) explains how to create the file, select
voices and LLMs, and override settings. Create it once, then inspect the effective values:

```bash
uv run pdf2audiobook config init       # or: uv run pdf2audiobook --init
uv run pdf2audiobook config show --sources
```

Existing files are kept. The desktop app creates missing configuration on startup and offers
a TOML editor in **Settings → CLI configuration**.

## Documentation

| Guide | What it covers |
|---|---|
| [Installation and first audiobook](docs/guides/getting-started.md) | Requirements, setup, illustrated review and conversion walkthrough |
| [Configuration](docs/guides/configuration.md) | Config file setup, precedence, environment variables, passwords and troubleshooting |
| [CLI reference](docs/guides/cli.md) | Commands, input formats, batch jobs, exit codes and progress |
| [Voices and speech](docs/guides/voices.md) | Voice samples, Kitten, Piper, per-book settings and pronunciation |
| [LLM assistance](docs/guides/llm.md) | Local Ollama, context limits, timeouts, budgets, caching and privacy |
| [Editing and review](docs/guides/editing-and-review.md) | Chapter edits, approvals, recovery, citations and equations |
| [Audio verification and repair](docs/guides/audio-verification.md) | Optional speech recognition checks and selective resynthesis |
| [Development and validation](docs/guides/development.md) | Lint, formatting, types, offline tests and opt-in live smoke tests |

Each command also has `--help`, for example `uv run pdf2audiobook convert --help`.

## Desktop app

The Linux desktop app uses Tauri, React and TypeScript and runs the installed CLI.
See the [desktop guide](desktop/README.md) for setup, screenshots and
[AppImage or .deb builds](desktop/README.md#building-an-installer).

## Status and contributing

The CLI has offline end-to-end fixture coverage. Real Kitten synthesis is an opt-in smoke test;
live OpenAI and llama-server acceptance remains deferred. Chapter detection and handling of
complex layouts still need review, especially tables, figures and OCR ambiguities. Check chapter
text and listen to the audio before sharing it.

See [Repository Guidelines](AGENTS.md) for contribution conventions and
[development checks](docs/guides/development.md) before submitting changes. The
[maintainer guide](docs/MAINTAINER_GUIDE.md), [specification](docs/PDF2AUDIOBOOK_SPEC.md) and
[implementation TODO](docs/PDF2AUDIOBOOK_TODO.md) document architecture and remaining acceptance work.
