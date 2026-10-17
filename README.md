# pdf2audiobook

Python CLI project for converting PDF books into chapter-separated MP3 audiobooks. Planned features include OCR, chapter detection, optional LLM support for OpenAI/Ollama/llama-server, and Kitten TTS.

**Status:** Working initial CLI implementation with offline end-to-end fixture coverage; real-model acceptance and release hardening remain incomplete. See the [specification](docs/PDF2AUDIOBOOK_SPEC.md), [implementation TODO](docs/PDF2AUDIOBOOK_TODO.md), and [installation/maintainer guide](docs/MAINTAINER_GUIDE.md).

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

## CLI workflow

~~~bash
uv run pdf2audiobook doctor
uv run pdf2audiobook config show --sources
uv run pdf2audiobook inspect path/to/book.pdf
uv run pdf2audiobook analyze path/to/book.pdf --no-llm
uv run pdf2audiobook convert path/to/book.pdf --no-llm --allow-single-chapter
uv run pdf2audiobook convert path/to/book.pdf --llm-provider openai --allow-remote-content
~~~

`analyze` extracts text, applies conservative pagination cleanup and writes chapter text plus a manifest. `convert` additionally creates tagged chapter MP3s with Kitten TTS. Models are loaded on demand.

Install Tesseract separately for scanned pages. For synthesis, run `uv sync --extra kitten --extra dev` and install FFmpeg. The Kitten model alias `mini` resolves to the lightweight 0.8 mini model.

**Limitations:** Chapter detection is provisional, especially for complex layouts. Tables, footnotes, OCR ambiguities and LLM-assisted text corrections remain in progress. Review chapter text before distributing audiobook files.

## Chapter preview and selective conversion

Use `--dry-run` to analyze a PDF and preview target MP3 paths without downloading or running the TTS model:

~~~bash
uv run pdf2audiobook convert book.pdf --no-llm --dry-run --json
uv run pdf2audiobook convert book.pdf --no-llm --chapter-range 2:5
uv run pdf2audiobook convert book.pdf --no-llm --chapter 3 --speed 1.15 --sample-rate 24000
~~~

Chapter ranges are **inclusive** and start at chapter 1. `--chapter` and `--chapter-range` cannot be combined. Dry-run still performs PDF extraction/OCR and may update local analysis files, but it produces no MP3 audio.

When an LLM is enabled, any proposed OCR corrections are stored in the manifest as **unapproved** `CleanupEdit` entries. To apply an edit, inspect the original and replacement, then explicitly set its `accepted` field to true. Derived narration text will be regenerated from approved corrections, retaining the raw source spans for auditing.

For the supported lightweight Kitten models, `kittenml` exposes `KittenTTS` and aliases `mini`, `micro` and `nano`. Actual model download and audio-listening acceptance are not covered by the offline CI tests.

## Password-protected PDFs

Supply the **name of an environment variable**, not the password itself:

~~~bash
export BOOK_PDF_PASSWORD='your PDF reader password'
uv run pdf2audiobook inspect encrypted.pdf --pdf-password-env BOOK_PDF_PASSWORD
uv run pdf2audiobook convert encrypted.pdf --no-llm --pdf-password-env BOOK_PDF_PASSWORD
~~~

You can also configure `[pdf] password_env = "BOOK_PDF_PASSWORD"` in TOML. Never commit the password itself or pass it directly as a command-line argument. The raw password is neither persisted in the manifest nor included in configuration diagnostics. The `doctor` command lists installed Tesseract language packs and reports any missing languages requested by the configuration.

## Protecting manual edits

After reviewing a `manifest.json`, mark a chapter's `manually_approved` field or the book's `approved` field to preserve the approved boundaries. The app will regenerate missing derived chapter text from that manifest on resume, but will **reject a destructive reanalysis** when approved content would otherwise be overwritten (including when using `--no-resume` or changing analysis settings). To start a new analysis, back up the approved manifest and choose a fresh output directory.

## Explicit fallback when a local LLM is unavailable

By default, LLM provider errors stop analysis with a typed diagnostic; the program
does **not** silently switch providers or downgrade analysis. For an offline-only
workflow, use `--no-llm`. To allow automatic deterministic fallback *only when
a configured LLM request fails*, set the following in your config file:

~~~toml
[llm]
fallback_to_deterministic = true
~~~

Alternatively set `PDF2AUDIOBOOK_LLM_FALLBACK_TO_DETERMINISTIC=true`.
The fallback discards partial model suggestions, preserves original book text
and unrelated review warnings, and records the fallback in the manifest.
Boundary confidence still requires review where applicable. A remote provider
continues to require explicit `--allow-remote-content` consent.

## LLM response cache and privacy

LLM analysis responses are cached locally under each book workspace at
`.cache/llm/`, with keys derived from the full request, prompt and provider
identity. Cache hits still pass the same deterministic source/ID verification
as fresh provider responses. Malformed or mismatched records are not trusted.
`--no-resume` disables cache reuse; turning off the cache in configuration
does likewise. Cache files can contain model-generated text derived from the
book and should be protected like the original PDF. There is currently no
automatic per-book request, token or dollar budget enforcement.

## Optional LLM token and dollar limits

Set the following in your TOML config under `[llm]`:

~~~toml
[llm]
max_requests = 12
max_reported_tokens = 20000
max_estimated_cost_usd = 0.15
input_cost_usd_per_million_tokens = 2.00
output_cost_usd_per_million_tokens = 8.00
~~~

The prices above are **illustrative only**, not actual or verified provider pricing.
Supply rates for your selected provider/model if enabling the dollar limit.
You may also set `PDF2AUDIOBOOK_LLM_MAX_REPORTED_TOKENS` and
`PDF2AUDIOBOOK_LLM_MAX_ESTIMATED_COST_USD` through environment variables.

These checks use token counts returned by the provider and stop subsequent
requests after the limit is reached. A request can exceed the budget before
its response is received; the over-budget response is rejected and not cached.
If a budget is enabled and the server omits required usage data, processing
fails instead of assuming a free request. The JSON usage report is local,
contains no PDF prose, and is scoped to the **current analysis run**, not
an authoritative cross-run book expenditure ledger. Do not rely on these
limits as a guaranteed provider billing ceiling.
