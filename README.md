# pdf2audiobook

Python CLI for analyzing PDF and EPUB books and converting approved chapters into tagged MP3 audiobooks. It supports selectable OCR, chapter review, optional LLM-assisted analysis, resumable TTS, batch conversion and M4B packaging.

**Status:** Working CLI with offline end-to-end fixture coverage. Real Kitten synthesis is an opt-in smoke test; live OpenAI and llama-server acceptance remains deferred. See the [specification](docs/PDF2AUDIOBOOK_SPEC.md), [implementation TODO](docs/PDF2AUDIOBOOK_TODO.md), and [installation/maintainer guide](docs/MAINTAINER_GUIDE.md).

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

The default LLM provider is local Ollama; OpenAI requires explicit consent before transmitting book contents. For consented non-loopback endpoints, a one-time stderr warning identifies the provider, selected model, and current analysis block-window scope *before* uploading book text. Local loopback analysis does not emit the remote-upload warning. See the specification for privacy and audit requirements.

PDF and EPUB books use the same analysis commands. Kitten is the default TTS provider. Piper can be selected when its CLI and a voice model are installed separately; configure the ONNX model path in TOML:

~~~toml
[tts]
provider = "piper"

[tts.piper]
model_path = "/path/to/en_US-lessac-medium.onnx"
voice = "0" # optional multi-speaker ID
speed = 1.0
~~~

Then run `uv run pdf2audiobook convert book.pdf --no-llm --tts-provider piper`. Piper is not installed or downloaded by the default project environment.

Batch conversion accepts a directory of PDFs (nested folders are opt-in):

~~~bash
uv run pdf2audiobook batch ./books --no-llm --recursive --json
~~~

Use `tts.profiles` to select a voice and speed by exact PDF filename stem:

~~~toml
[tts.profiles."My Book"]
provider = "kitten"
kitten_model = "mini"
voice = "Jasper"
speed = 1.05

[tts.pronunciations]
"Māori" = "Mow-ree"
~~~

Pronunciation replacements apply only to speech output; they must be a single token. Source chapter text remains unchanged and progress ranges still point to the original words.

For dialogue, edit an approved chapter text file and put `[[voice:VOICE_ID]]` on its own line between blank lines before the paragraph that voice should narrate. For example:

~~~text
The narrator introduces the scene.

[[voice:OtherVoice]]

“We should leave,” she said.
~~~

The marker is omitted from speech; that voice continues until another marker or the end of the chapter. The chapter's configured voice is used before the first marker. Markers require blank-line paragraph boundaries, and their source offsets remain in the narration progress record.

After converting all chapters, package them as a single AAC audiobook with chapter navigation:

~~~bash
uv run pdf2audiobook pack-m4b ./audiobooks/BOOK/manifest.json --output ./book.m4b
~~~

Open a local browser editor for chapter titles and boundaries with:

~~~bash
uv run pdf2audiobook review ./audiobooks/BOOK/manifest.json
~~~

The review server binds only to loopback, requires a per-run token for manifest data, and marks saved chapter boundaries as manually approved. It also accepts an optional TTS voice ID per chapter; paragraph-level voice markers in the approved chapter text can override it for dialogue.

**Lockfile:** The generated `uv.lock` is committed and pins the project's declared default, `dev`, and optional `kitten` dependency graphs. For reproducible development installs, run `uv sync --locked --extra dev`; for the heavyweight voice extra, run `uv sync --locked --extra kitten --extra dev`. Regenerate the lockfile deliberately with `uv lock` when changing dependencies and review the resulting diff. **CI verifies `uv lock --check` and installs development dependencies using `uv sync --locked --extra dev`** on Python 3.11, 3.12 and 3.13; the optional Kitten model remains an explicit heavyweight, environment-dependent acceptance gate.

## CLI workflow

~~~bash
uv run pdf2audiobook doctor
uv run pdf2audiobook config show --sources
uv run pdf2audiobook inspect path/to/book.pdf
uv run pdf2audiobook analyze path/to/book.pdf --no-llm
uv run pdf2audiobook convert path/to/book.pdf --no-llm --allow-single-chapter
uv run pdf2audiobook batch ./books --no-llm --recursive
uv run pdf2audiobook pack-m4b ./audiobooks/BOOK/manifest.json --output ./book.m4b
uv run pdf2audiobook convert path/to/book.pdf --cover ./cover.jpg
uv run pdf2audiobook convert path/to/damaged.pdf --accept-review damaged_source
uv run pdf2audiobook budget show --output ./audiobooks/BOOK
uv run pdf2audiobook convert path/to/book.pdf --llm-provider openai --allow-remote-content
~~~

`analyze` extracts text, applies conservative pagination cleanup and writes chapter text plus a manifest. `convert` additionally creates tagged chapter MP3s with the selected TTS provider; `--cover PATH` embeds JPEG/PNG artwork (up to 5 MiB). The same option works with `batch`, and `audio.cover_image` configures a default. `pack-m4b --cover` applies artwork to the M4B only; packaging freshness is based on chapter text. `budget show` reports content-free LLM request accounting; unknown and pending attempts count at their worst-case token and cost bounds. A rejected provider request still counts toward `max_requests`, but does not consume token or cost budget when it reports no usage. `budget resolve` settles an ambiguous request only after explicit confirmation. TTS retries default to two and are limited to transient failures; failed chapters are visible with `inspect`, and conversion continues through other chapters before reporting partial failures. Use `--accept-review REASON` only after reviewing the flagged issue. REASON is `damaged_source`, `empty_chapter` or `ambiguous_page_numbers`; an unknown value exits 2 before any work, `--dry-run` reports what it would acknowledge, and the browser review page (`review`) clears `damaged_source` only when its checkbox is ticked. Budget rows without a recorded bound (from older ledgers) block token and cost budgets until `budget resolve` settles them. A failed command prints only its `Error:` line (or one JSON object with `--json`); progress and failure events appear on stderr only with `--verbose` or an explicit `general.log_level`. A second `convert` of the same book is refused while one is running.

Install Tesseract separately for scanned pages. For synthesis, run `uv sync --extra kitten --extra dev` and install FFmpeg. The Kitten model alias `mini` resolves to the lightweight 0.8 mini model.

**Limitations:** Chapter detection is provisional, especially for complex layouts. A poem or section-number sequence in the only qualifying margin band can be mistaken for folios; disable removal with `pdf.remove_page_numbers = false` if needed. Tables, footnotes, OCR ambiguities and LLM-assisted text corrections remain in progress. Review chapter text before distributing audiobook files.

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
book and should be protected like the original PDF. Optional per-book request, provider-reported token and estimated dollar limits
are enforced through the persistent budget ledger described below.

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
Per-book accounting persists in `reports/llm_budget.sqlite3`, including
across process restarts and `--no-resume` runs in the same book workspace.
SQLite reservations serialize concurrent budgeted requests. Cached responses
do not create new ledger charges. `reports/llm_usage.json` includes both
current-run counters and persistent book totals; neither report stores book
text, prompts, responses, or credentials.

If a request crashes or returns no trustworthy usage, the ledger records an
unresolved request. A token or dollar budget then fails closed on subsequent
requests until the unknown charge is reviewed. Enabling a dollar limit after
earlier unpriced calls also fails closed rather than treating them as free.
Back up the ledger and reconcile provider billing before manually resetting
any such entries. Changing the configured prices does not retroactively
reprice historical calls; each request records the operator-supplied rates
in effect at that time.

**Important:** a single completion can exceed its budget before usage is
reported; that response is rejected but may still be billed. Internal HTTP
retries can also incur charges not reported by the provider. Dollar totals
are estimates, not authoritative provider billing. Do not rely on these
limits as guaranteed provider-side spending caps.

## LLM context and completion capacity

The LLM adapter checks each request before uploading book content, reserving
space for model output as well as instructions and document records. Configure:

~~~toml
[llm]
max_context_tokens = 16384
chunk_tokens = 4000
max_output_tokens = 1024
~~~

`max_output_tokens` can also be set with
`PDF2AUDIOBOOK_LLM_MAX_OUTPUT_TOKENS`. The adapter sends this value as
`max_tokens` and fails closed if a server rejects the parameter; it must
not retry without the cap. Existing JSON-mode fallback preserves the cap.
Input estimation uses a conservative UTF-8-byte count plus reserved chat
overhead, **not** model-specific tokenization. Oversized requests are rejected
before cache retrieval or SQLite budget reservations, so a locally rejected
request does not leave a false unresolved provider charge. Changing the output
cap also invalidates earlier LLM response-cache identities. Operators must verify actual
context windows and `max_tokens` support against their selected live model.
These checks do not guarantee that a misconfigured server honors its limit.

## Optional visual review

Set `llm.vision = true` (or `PDF2AUDIOBOOK_LLM_VISION=true`) to render up to 12 pages with detected images, vector art, or likely multi-column layouts for review-only descriptions. Use `--vision` for a one-command opt-in. Visual suggestions are saved in `reports/vision_review.json`; they do not change chapter text or narration. Select a vision-capable model. Remote page images follow the same explicit consent and HTTPS rules as other book content.

## Opt-in live LLM provider smoke tests

These are **never run by offline CI**. Each command sends only a small synthetic
fixture (no PDF content) to the selected endpoint. The `--execute` switch is
required even for loopback servers:

~~~bash
uv run python -m pdf2audiobook.llm.smoke --provider ollama --model qwen3.5:9b --execute
uv run python -m pdf2audiobook.llm.smoke --provider llama-server --model auto --execute
~~~

For OpenAI, set `OPENAI_API_KEY` in the environment first and additionally
provide explicit remote-content consent:

~~~bash
uv run python -m pdf2audiobook.llm.smoke --provider openai --model gpt-4.1-mini --execute --allow-remote-content
~~~

Model identifiers are examples, not guarantees that those models are installed
or available. The runner returns a JSON success/error result with sanitized
provider details and usage metadata, but never echoes the synthetic request
body or credentials. Real backend acceptance remains pending until these
checks are executed against actual reachable services.
