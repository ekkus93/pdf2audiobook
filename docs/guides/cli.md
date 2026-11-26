# CLI reference

[Home](../../README.md) · [All guides](README.md)

For a first conversion, follow
[the walkthrough](getting-started.md#walkthrough-from-pdf-to-audiobook).
Persistent settings are described in [configuration](configuration.md).

- [Command reference](#command-reference)
- [Exit codes](#exit-codes)
- [PDF and EPUB input](#pdf-and-epub-input)
- [Batch conversion](#batch-conversion)
- [Chapter preview and selective conversion](#chapter-preview-and-selective-conversion)
- [Progress and time estimates](#progress-and-time-estimates)

## Command reference

~~~bash
uv run pdf2audiobook doctor
uv run pdf2audiobook config init
uv run pdf2audiobook config show --sources
uv run pdf2audiobook config validate --config ./my-config.toml
uv run pdf2audiobook inspect path/to/book.pdf
uv run pdf2audiobook analyze path/to/book.pdf --no-llm
uv run pdf2audiobook convert path/to/book.pdf --no-llm --allow-single-chapter
uv run pdf2audiobook batch ./books --no-llm --recursive
uv run pdf2audiobook pack-m4b ./audiobooks/BOOK/manifest.json --output ./book.m4b
uv run pdf2audiobook convert path/to/book.pdf --cover ./cover.jpg
uv run pdf2audiobook convert path/to/damaged.pdf --accept-review damaged_source
uv run pdf2audiobook budget show --output ./audiobooks/BOOK
uv run pdf2audiobook convert path/to/book.pdf --llm-provider openai --allow-remote-content
uv run pdf2audiobook workspace path/to/book.pdf --json
uv run pdf2audiobook voices --json
uv run pdf2audiobook thumbnail path/to/book.pdf --output cover.png --width 320 --json
uv run pdf2audiobook asr list
uv run pdf2audiobook verify-audio ./audiobooks/BOOK/manifest.json --chapter 3
uv run pdf2audiobook resynthesize ./audiobooks/BOOK/manifest.json --chapter 3
uv run pdf2audiobook audio-report show ./audiobooks/BOOK/manifest.json
uv run pdf2audiobook audio-report dismiss ./audiobooks/BOOK/manifest.json --chapter 3 --flag 0
uv run pdf2audiobook --version
~~~

`workspace` prints the folder a book's analysis uses, without creating it. `voices` lists the
voices the selected TTS provider accepts (Piper reports that its numbered speakers can't be
listed). `thumbnail` writes a PNG of a PDF's first page or an EPUB's cover into an existing
folder. `review --json` prints its address as one JSON line, `{"url", "port"}`, as soon as the
server is listening. These and the error `reason` codes below exist so that other programs,
such as the desktop app, can drive the CLI.

Every command has `--help` with its options and an example.

`--init` is a shortcut for `config init` at the default path and exits after initialization.
Use `config init --config FILE --json` for a custom path or JSON output. An existing config
is never overwritten. See [configuration setup](configuration.md#create-your-config-file).

### Analysis and audio

`analyze` extracts text, applies conservative pagination cleanup, and writes chapter text and
a manifest. `convert` also creates tagged chapter MP3s with the selected TTS provider.
TTS retries default to two and apply only to transient failures. Failed chapters are visible
with `inspect`; conversion continues through other chapters before reporting partial failures.

For `convert` and `batch`, `--cover PATH` embeds JPEG/PNG artwork up to 5 MiB;
`audio.cover_image` supplies a default. `pack-m4b --cover` applies artwork to the M4B only.
Packaging freshness is based on chapter text.

### Review requirements

Use `--accept-review REASON` after reviewing a book-wide issue. Accepted codes are
`damaged_source` and `ambiguous_page_numbers`; an unknown code exits 2 before any work.
`--dry-run` reports what it would acknowledge.

Empty chapters require individual approval in the browser review page. An approved empty
chapter is skipped and listed in the conversion report. `--accept-review empty_chapter`
exits 2, and approving one chapter never approves another that becomes empty later.
See [editing and review](editing-and-review.md).

### LLM budgets

`budget show` reports accounting without book content. Unknown and pending attempts count at
their worst-case token and cost bounds. Rejected requests count toward `max_requests`, but
consume no token or cost budget when they report no usage. `budget resolve` settles ambiguous
requests only after explicit confirmation. Older ledger rows without a recorded bound block
token and cost budgets until settled. See
[budget configuration and resolution](llm.md#optional-llm-token-and-dollar-limits).

### Output and concurrency

A failed command prints its `Error:` line, or one JSON object with `--json`.
JSON results include a `warnings` array of event codes; human output uses `Warning:` lines.
`--quiet` suppresses warnings and progress. Progress and failure events appear on stderr
only with `--verbose` or an explicitly configured `general.log_level`.
A second `convert` of the same book is refused while one is running.

Install Tesseract separately for scanned pages. For synthesis, run `uv sync --extra kitten --extra
dev` and install FFmpeg. The Kitten model alias `mini` resolves to the lightweight 0.8 mini model.

**Limitations:** Chapter detection is provisional, especially for complex layouts. A poem or
section-number sequence in the only qualifying margin band can be mistaken for folios; disable
removal with `pdf.remove_page_numbers = false` if needed. Tables, footnotes, OCR ambiguities and
LLM-assisted text corrections remain in progress. Review chapter text before distributing audiobook
files.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Unexpected error |
| 2 | Invalid configuration or command-line usage |
| 3 | Unreadable or unsupported input (for example a wrong PDF password) |
| 4 | Extraction or workspace problem (for example a chapter-edit conflict or a pending recovery) |
| 5 | LLM problem (unreachable server, context too small, output cut off, budget reached) |
| 6 | Audio problem, including "review the manifest before synthesis" |
| 7 | Some chapters converted and others failed |
| 130 | Interrupted with Ctrl+C, or stopped with SIGTERM |

With `--json`, a failure prints one JSON object on stderr: `{"ok": false, "error": {"type",
"code", "message", "reason"}, "warnings"}`. `reason` appears only when a program can act on the
failure: `review_required`, `review_acknowledgement_required`, `workspace_locked`,
`pending_recovery`, `chapter_conflict`, `llm_unreachable`, `llm_context_too_small`,
`llm_output_cap` or `budget_exhausted`. For example, exit 6 with `review_required` means "open
the review page", while exit 6 without a reason is an audio failure.

Some commands (for example `verify-audio` and `resynthesize`) stop with the exit code of the
check they ran. Then the message is the fixed line `The command stopped with exit code N.`, and
with `--json` its error `type` is `Stopped`, with the same `code`.

### PDF and EPUB input

PDF and EPUB books use the same analysis commands. For an EPUB, chapter boundaries come from its
own outline when it has one: an entry such as "Chapter 12" is matched to the line that opens that
chapter on its page, including books whose chapters begin with only a numeral. Cover and plate
pages that are just an image are noted but do not block conversion, and an EPUB's many per-page
warnings are summarized as one line with a count ("Analysis recorded N warnings; see warnings in
manifest.json"). Page numbers in an EPUB are generated by
the renderer and can vary.

### Batch conversion

Batch conversion accepts a directory of PDFs (nested folders are opt-in):

~~~bash
uv run pdf2audiobook batch ./books --no-llm --recursive --json
~~~

## Chapter preview and selective conversion

Use `--dry-run` to analyze a PDF and preview target MP3 paths without downloading or running the TTS
model:

~~~bash
uv run pdf2audiobook convert book.pdf --no-llm --dry-run --json
uv run pdf2audiobook convert book.pdf --no-llm --chapter-range 2:5
uv run pdf2audiobook convert book.pdf --no-llm --chapter 3 --speed 1.15 --sample-rate 24000
~~~

Chapter ranges are **inclusive** and start at chapter 1. `--chapter` and `--chapter-range` cannot be
combined. Dry-run still performs PDF extraction/OCR and may update local analysis files, but it
produces no MP3 audio.

When an LLM is enabled, proposed OCR corrections are stored in the manifest as **unapproved**
`CleanupEdit` entries. Inspect the original and replacement before accepting an edit with
the [review commands](editing-and-review.md#citations-and-equations). Derived narration text
is regenerated from approved corrections, retaining raw source spans for auditing.

For the supported lightweight Kitten models, `kittenml` exposes `KittenTTS` and aliases `mini`,
`micro` and `nano`. Actual model download and audio-listening acceptance are not covered by the
offline CI tests.

## Progress and time estimates

Long runs show a progress bar per stage on stderr, with elapsed time and an estimate of the time
left: page extraction, LLM analysis requests, speech synthesis (counted in characters, so the
estimate follows how much text remains) and M4B packaging. The estimate reads "estimating…"
until the first real unit of work finishes, and work reused from a previous run (cached LLM
answers, already converted chapters or chunks) is counted as done without making the estimate
optimistic. A single FFmpeg encode shows elapsed time only. A one-line summary follows each
command, for example `Finished 12 chapter(s) in 41m 07s`.

~~~bash
pdf2audiobook --progress convert ./book.pdf     # force bars on
pdf2audiobook --no-progress convert ./book.pdf  # force bars off
~~~

### Watching a long run

Every `analyze` and `convert` keeps `reports/run_status.json` in the book's workspace, even with
`--json`: the command, `state` (`running`, `completed` or `stopped`), elapsed time, the current
stage
with its count, total and estimated seconds remaining, and the stages already finished. It is
refreshed every few seconds, including while a single slow LLM request is in flight, so
`watch -n5 cat reports/run_status.json` works from another terminal. It contains only stage names,
counts and times.

`--heartbeat N` (or `general.heartbeat_seconds`, `PDF2AUDIOBOOK_HEARTBEAT_SECONDS`) also prints one
line to stderr every N seconds, such as
`[12:49:58] Analyzing with the LLM, cleanup: 712/940 request, 52m 00s elapsed, about 11m 20s left`.
It is off by default so that stderr stays empty on success, and is ignored under `--quiet`.

With `--verbose`, each LLM request logs one `llm_request` event (stage, seconds, prompt and output
tokens) and a failed one logs `llm_request_failed` with a reason such as `output_cap`. A request
that is far slower or produces far more output than its stage's recent average raises a single
`llm_slow_request` warning per stage, which usually means the model is rambling or the output cap
is too generous.

By default (`general.progress = "auto"`, or `PDF2AUDIOBOOK_PROGRESS=auto|always|never`) bars
appear only when stderr is a terminal. `--json` and `--quiet` always turn them off, so machine
output stays parseable; bars never go to stdout and never include book text, titles or paths.

## Voice cloning and model setup

`tts models [--json]` reports capabilities and local readiness; `tts fetch kitten2 [--yes]
[--json]` explicitly downloads pinned artifacts. `convert`, `batch` and `resynthesize` accept
`--clone-voice/--no-clone-voice`, `--reference-audio PATH` and `--reference-text-file PATH`.
Choose `--tts-model kitten2`; repair also accepts `--tts-provider`. The same three commands
accept `--tts-temperature` (Kitten 2 only, default `0.2`; see
[Kitten 2 temperature](voices.md#kitten-2-temperature)). See the
[complete examples and privacy rules](voice-cloning.md). Stable clone error reasons are
`voice_clone_unsupported`, `voice_clone_unavailable`, `voice_reference_invalid`,
`voice_reference_changed` and `voice_selection_conflict`; existing exit-code families apply.
