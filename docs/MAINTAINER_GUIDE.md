# PDF2Audiobook: installation, usage and maintainer guide

This guide documents the **current Python CLI implementation**, not a promise of
production-quality recognition or narration. Read
[`PDF2AUDIOBOOK_SPEC.md`](PDF2AUDIOBOOK_SPEC.md) for normative requirements and
[`PDF2AUDIOBOOK_TODO.md`](PDF2AUDIOBOOK_TODO.md) for incomplete acceptance.

## Prerequisites and reproducible development environment

Python 3.11+, [uv](https://docs.astral.sh/uv/), FFmpeg and (for scanned PDFs)
Tesseract with the requested language data are required. On Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg tesseract-ocr tesseract-ocr-eng
uv python install 3.11
uv sync --extra dev
uv run pdf2audiobook doctor --json
```

For other OCR languages, install the corresponding system package (for example
`tesseract-ocr-fra` for French) and set `pdf.ocr_language` or
`PDF2AUDIOBOOK_OCR_LANGUAGE`. Check the `ocr_missing_languages` field from
`doctor --json` before converting a scan. FFmpeg must be on `PATH`.

For actual speech synthesis, install the optional Kitten package:

```bash
uv sync --extra dev --extra kitten
uv run pdf2audiobook doctor
```

Kitten model weights may be downloaded on first synthesis; allow disk space and
network access for that first run. Supported aliases are `mini`, `micro` and
`nano`, mapped in `src/pdf2audiobook/tts/__init__.py`; a full model ID can
also be selected. The default voice is `Jasper`. The actual model/voice must
be available to the installed Kitten version. Offline CI mocks Kitten; it does
**not** validate the real model's audio quality or download path.

The project uses `uv sync` to manage `.venv`; do not manually install
dependencies into the system interpreter. The committed `uv.lock` pins the
default, `dev` and `kitten` dependency graphs; install with
`uv sync --locked --extra dev` and regenerate deliberately with `uv lock`
when changing dependencies, as a separate, tested change.

## CLI workflows

Inspect PDF metadata, page labels, geometry, bookmarks and per-page text-layer
counts (characters and images only, no book text; `image_only_pages` hints at
OCR needs) without TTS:

```bash
uv run pdf2audiobook inspect book.pdf --json
uv run pdf2audiobook config show --sources --json
uv run pdf2audiobook doctor --json
uv run pdf2audiobook budget show --output ./audiobooks/BOOK
uv run pdf2audiobook budget resolve --output ./audiobooks/BOOK --confirm --unbilled 12
```

Analyze with no LLM and review the resulting manifest/chapter text before
synthesis. For books with no confident chapter boundaries, review the
single-chapter output and explicitly opt in:

```bash
uv run pdf2audiobook analyze book.pdf --no-llm --output ./audiobooks --json
uv run pdf2audiobook convert book.pdf --no-llm --dry-run --json
uv run pdf2audiobook convert book.pdf --no-llm --allow-single-chapter
```

Convert only a selected chapter or an inclusive, 1-based chapter range:

```bash
uv run pdf2audiobook convert book.pdf --no-llm --chapter 2 --voice Jasper --speed 1.1
uv run pdf2audiobook convert book.pdf --no-llm --chapter-range 2:5 --bitrate 128k
uv run pdf2audiobook convert book.pdf --no-llm --chapter 2 --force
uv run pdf2audiobook convert book.pdf --no-llm --no-resume
uv run pdf2audiobook convert book.pdf --no-llm --cover ./cover.jpg
```

`--dry-run` can still write analysis files and invoke OCR, but does not
synthesize audio. `--force` regenerates selected MP3s. `--no-resume` bypasses
the existing analysis/audio reuse path; **neither option authorizes overwriting
manually approved analysis**. Preserve a backup and use a different `--output`
directory if a new analysis would invalidate approved edits.

Boolean CLI pairs accept both explicit directions: `--llm/--no-llm`,
`--vision/--no-vision`,
`--allow-remote-content/--no-allow-remote-content`,
`--allow-single-chapter/--no-allow-single-chapter`,
`--resume/--no-resume`, and `--recursive/--no-recursive` for batch. Their
default is unset, so environment and TOML values remain effective unless a
flag is supplied. `--cover PATH` overrides `[audio].cover_image` for convert
or batch; `pack-m4b --cover PATH` embeds the same validated image at book level.

`budget show --output DIR` prints request statuses and accounting without
prompt or response text. `budget resolve --output DIR ID --confirm` requires
exactly one of `--tokens PROMPT:COMPLETION` or `--unbilled`, and should be used
only after checking provider billing evidence.

To use OCR explicitly, set `--ocr always` or `--ocr never`; `auto` uses
embedded text when usable and OCR otherwise. A PDF password is read from a
named environment variable, not a command-line password argument:

```bash
export BOOK_PASSWORD='replace-with-private-password'
uv run pdf2audiobook inspect encrypted.pdf --pdf-password-env BOOK_PASSWORD
uv run pdf2audiobook analyze scanned.pdf --no-llm --ocr always
```

Avoid storing passwords or copyrighted source text in shared logs.

In `auto` mode a page with no usable text is also OCRed when its drawings look
like outlined text (`pdf_ocr.py`): at least `_VECTOR_GLYPH_MIN_PATHS` (40) small
filled paths, each no larger than `_VECTOR_GLYPH_MAX_FRACTION` (6%) of the page
in either direction, or at least `_VECTOR_ARTWORK_MIN_PATHS` (100) paths of any
size covering `_VECTOR_ARTWORK_MIN_COVERAGE` (15%) of it. A text-free page with
`_VECTOR_REVIEW_MIN_PATHS` (10) or more drawn paths that is not OCRed is
reported as "drawings without readable text" and sets the `damaged_source`
review reason; a lone rule or border is treated as blank. The Tesseract test in
`tests/test_vector_outlined_text.py` runs in CI, whose job installs Tesseract.

`analyze`, `convert`, each `batch` book, and review saves share the exclusive
`<workspace>/.convert.lock` (POSIX `flock`). Analysis and conversion hold it
before analysis or workspace writes for the whole operation; review saves
acquire it without blocking and return HTTP 409 when busy. The conversion lock
also protects the temporary-WAV sweep from deleting another run's files.
`tts.max_retries` retries only errors a
provider marks transient (`exc.transient = True` or `provider.is_transient_error`).
The Piper adapter marks its subprocess timeout; the Kitten adapter runs
in-process and has no documented transient failure, so it never retries.

### Optional local and remote LLMs

The built-in default provider is Ollama at `http://127.0.0.1:11434/v1`
with model `qwen3.5:9b`. Start the service and ensure that model is installed
before using model-assisted analysis:

```bash
ollama pull qwen3.5:9b
ollama serve
uv run pdf2audiobook analyze book.pdf --llm-provider ollama --llm-model qwen3.5:9b
```

Ollama silently drops the start of a prompt longer than the context it
serves (a plain `qwen3.5:9b` pull is served with 4096 tokens), so before the
first uncached request the adapter loads the model with an empty prompt, reads
its `context_length` from `/api/ps`, and refuses any request whose
conservative byte bound plus output reserve exceeds the smaller of that and
`llm.max_context_tokens`. Use a variant with a larger `num_ctx` (for example a
Modelfile with `PARAMETER num_ctx 131072`) or lower `llm.chunk_tokens`. Fully
cached reruns do not contact Ollama.

For a local OpenAI-compatible `llama-server` listening on loopback:

```bash
uv run pdf2audiobook analyze book.pdf --llm-provider llama-server \
  --llm-model auto --llm-url http://127.0.0.1:8080/v1
```

For OpenAI, book text is transmitted to an external service **only after
explicit remote-content consent**. Review the book's rights and privacy
requirements first; set the API key only in the environment:

```bash
export OPENAI_API_KEY='replace-with-private-key'
uv run pdf2audiobook analyze book.pdf --llm-provider openai \
  --allow-remote-content
```

Non-loopback plain HTTP is prohibited even with consent. Local `--no-llm`
is available for deterministic analysis, and no provider is required for
`inspect`, `doctor` or `config show`. LLM heading and OCR-cleanup
suggestions are untrusted proposals; source anchors are validated and
non-deterministic cleanup edits remain unapproved until reviewed. A cleanup
proposal is kept for review only when every change is a known OCR glyph
confusion (`b00k`, `tlie`, `rn`/`m`, ligatures, long s) or a split/joined
word; rewording, tense, case, quote style, punctuation and completing a
hyphenated word from the next line are rejected as `not_ocr_correction`.

## Configuration and precedence

On Linux, the optional default configuration file is
`~/.config/pdf2audiobook/config.toml` (or under `XDG_CONFIG_HOME`).
An explicit `--config FILE` selects a different file, while `--no-config`
ignores TOML. Configuration precedence is CLI > `PDF2AUDIOBOOK_*`
environment > TOML > built-in defaults, including explicit boolean `false`.

Example TOML (contains no secrets):

```toml
[general]
output_dir = "./audiobooks"
resume = true

[pdf]
ocr = "auto"
ocr_language = "eng"
ocr_dpi = 300
remove_page_numbers = true
# warn: keep PDF position; inline: after the anchoring paragraph;
# end: after the chapter body; omit: audited exclusion
footnotes = "warn"

[chapters]
min_boundary_confidence = 0.75
allow_single_chapter = false

[llm]
enabled = false
provider = "ollama"
allow_remote_content = false
structure = true
cleanup = true

[llm.ollama]
model = "qwen3.5:9b"
base_url = "http://127.0.0.1:11434/v1"

[tts]
provider = "kitten"
bitrate = "128k"
sample_rate = 24000
pause_ms = 250

[tts.kitten]
model = "mini"
voice = "Jasper"
speed = 1.0
```

Use `uv run pdf2audiobook config show --sources --json` to see the
effective values and their provenance. Provider key configuration stores
**environment variable names**, not secret values. Examples of supported
environment overrides include `PDF2AUDIOBOOK_LLM_ENABLED=false`,
`PDF2AUDIOBOOK_OCR_LANGUAGE=fra`,
`PDF2AUDIOBOOK_LLM_PROVIDER=llama-server`, and
`PDF2AUDIOBOOK_ALLOW_REMOTE_CONTENT=false`.

## Workspace, review and cache contracts

The analysis directory is
`<output_dir>/<source-stem>-<first-10-hex-of-input-SHA256>/`. Important files:

- `manifest.json`: versioned `BookManifest` with immutable source spans,
  ordered blocks, proposed/accepted cleanup edits, chapter boundaries and
  warnings.
- `chapters/001.txt` and subsequent chapter text: derived from the manifest.
- `coverage.json`: chapter/prose coverage audit produced by the renderer.
- `*.mp3` and adjacent `*.cache.json`: final audio and fingerprint/hash
  records.
- `.cache/ocr/` and `.cache/tts/`: page recognition and checksum-validated
  WAV chunks; `.cache/tts/progress/` contains text-free synthesis ledgers.

Inspect `manifest.json`, `coverage.json`, warnings and chapter text against
the original PDF before listening or distributing. The schema currently
**rejects** unsupported versions; it does not auto-migrate manifests.
Manifest schema v3 is required after the second-review fixes. Existing v1 and
v2 workspaces are intentionally rejected; re-run `analyze` with a fresh output
directory to create a v3 workspace.
Printed poem or section numbers in the only qualifying margin sequence can be
mistaken for folios. Set `pdf.remove_page_numbers = false` when a book uses
those numbers and confirm the retained text in the review workspace.
The per-book LLM budget ledger schema v3 adds per-attempt token/USD upper
bounds and a `rejected` state. Unknown and pending sent requests remain charged
at their upper bounds; `budget resolve` validates and settles them in one
transaction.
LLM decision auditing writes `reports/llm_decisions.json`; the cleanup audit is
schema v3 and stores only sanitized IDs, hashes and fixed summaries/reason codes.
LLM cache identity v4 includes resolved provider/model and current request/task
semantics; existing LLM cache entries become misses and are regenerated on use.
Chapter audio identity `mp3-v6` and sidecar version 2 add current chapter-text
hashes for packaging checks and invalidate prior MP3 cache entries after
including the active TTS model identity, narration-normalization version and
cover-image digest. Piper identity hashes its ONNX model and adjacent JSON
configuration; Kitten identity includes the resolved model ID and installed
`kittenml` version. The `kitten` extra is bounded to `>=0.9.4,<0.10` and the
lockfile currently resolves 0.9.6. Re-encoding is automatic when a chapter is
next converted; no manifest migration is needed. Chapter synthesis now streams
PCM to a temporary WAV, so interrupted temporary audio is disposable.

Historical upgrade notes (superseded): analysis fingerprint `analysis-v19`
was introduced for safer folio detection and the damaged-source review gate;
it invalidated earlier analysis caches. Chapter audio identity `mp3-v5`
invalidated prior MP3 caches after adding the active TTS model identity,
narration-normalization version and cover-image digest. These versions are
retained here to explain older workspaces; the current versions are recorded
in the later upgrade notes below.

`ci.yml` pins uv 0.12.9 (`astral-sh/setup-uv` `version:`), the release that wrote
`uv.lock` (`revision = 3`; `uv lock` with 0.12.9 leaves the file unchanged). To move to a
newer uv, change the pin and the lockfile in the same commit and say so in the ledger.

Upgrade note (FX9): the analysis fingerprint is now `analysis-v21` (one-letter Roman
headings, wrapped initials and years, glyph-like vector pages sent to OCR), so existing
workspaces re-run analysis; unapproved workspaces recompute, approved ones are protected
as before. Chapter audio carries `narration-normalization-v2` (alignment on source words,
dash and invisible-character handling, pronunciation punctuation), so chapter MP3s
regenerate on the next `convert`. Chunk WAV keys contain the spoken chunk text and are not
bumped: unchanged chunks stay cached. No manifest schema change; `budget` ledger rows
without a recorded bound block token and USD budgets until `budget resolve` settles them.

Upgrade note (citation intervals): with `reading.process_citations` on, the chapter audio
fingerprint part is `citations-skipped-v2`, because a bracketed list right after `∈ = ≤ ≥ < > ≈ ×`
is now read as an interval instead of being skipped. Audio made with citation skipping regenerates
once on the next `convert`; chapter text, analysis and audio made with the setting off are
unchanged. `tests/test_citation_identity.py` pins the old on-state values to prove the change.

Upgrade note (LLM prompts): the LLM analysis identity carries `llm-analysis-v2` (cleanup and classification ask only for lines that change or aren't body text, equation windows are sized from the output cap), so books analyzed with the LLM before it are analyzed again; analyses without the LLM are unaffected.

Upgrade note (numbered running heads): analysis uses `analysis-v25`. A repeated margin line with a number is removed as a running head only when its number follows the page sequence, as a bare page number must; labels at the top of a figure that starts a page ("turn 1" on three pages of a paper) were being removed. (v24, bullet lists:) A line starting with `•` or `*`
next to a line with the same bullet is now a `list` block (before, the bullet rule never
matched and such lines were `unknown`), which changes reflow around bulleted lists.
Workspaces without approvals re-run analysis; approved workspaces stay protected as before.

Upgrade note (EPUB chapters): analysis uses `analysis-v23` and the chapter-boundaries stage
carries `chapter-detection-v6` (v6 keeps numbered subsections such as "2.1" or "D.3" in the chapter of their section when that section is itself a heading, so a paper's chapters are its sections; reads the body size as the median by characters, so figure and table lines can't drag it down; accepts an LLM-proposed heading only when it is set at least 1.1 times the body size and is not a table, caption, footnote, equation or list line; and measures the space above a line against the nearest earlier line that overlaps it sideways, so a vertical margin stamp such as arXiv's, or the foot of the other column, no longer hides a heading. On a 63-page paper this took 73 chapters, 38 of them figure labels the LLM proposed, to 12; v5 treats the page after a printed contents page as contents when every line on it is the next numbered label, so a contents list split over two pages no longer opens chapters; v4 anchors numeral chapters through an inferred page offset and lets corroborated numerals suppress font-size-only headings; v3 stripped contents leaders and page references from corroborated titles, rejects running page numbers even when an unnumbered page shifts their offset, and keys parts and chapters separately). Outline entries now anchor to the numeral that opens a chapter
on their own page ("Chapter 12" pairs with a line reading "12"), contents-page labels no
longer open chapters, numerals corroborated by a printed contents are headings, an EPUB cover
image on a page-sized background is not `damaged_source`, and a book's many manifest warnings
print as one summary line ("Analysis recorded N warnings; see warnings in manifest.json"). A workspace without approvals is re-planned on its next
`analyze`/`convert`; its cached LLM answers stay valid because they are keyed by request text,
not by chapter plan (verified by `tests/test_epub_analysis_upgrade.py`). A workspace with a
manually approved chapter keeps refusing reanalysis; use a new `--output` directory.

Upgrade note (FX10.31): analysis uses `analysis-v22` after the outline/list,
page-number and OCR-selection corrections, so workspaces re-run analysis while
approved workspaces remain protected. Chapter audio uses `mp3-v7` and
`narration-normalization-v3`; its sidecar v3 records rendering inputs, including
the footnote policy. Existing MP3 audio regenerates on the next `convert`, and
`pack-m4b` treats v2 sidecars as stale. Chunk WAV keys remain unchanged.
When reanalysis applies a hand edit, match chapters by generated start block,
or by the unique new generated range containing the old generated start; never
by chapter number. An unmatched or ambiguous edited chapter is a content-free
conflict. The page-number candidate tie tolerance is 2pt: closer edge distances
are considered tied and both sequences remain for review. CI runs
`pytest -q -ra`; check the skip summary to confirm environment-gated tests ran.
The workflow installs FFmpeg and Tesseract and sets up Node.js 22, so tests
gated on those tools should appear as passed rather than skipped.
`BookManifest.approved` and `Chapter.manually_approved` prevent accidental
destructive reanalysis. Only explicitly accepted, source-anchored
`CleanupEdit` entries affect derived text. OCR and pagination heuristics can
still make mistakes, especially on multi-column layouts, footnotes, tables,
captions and mathematical content.

Audio can use `audio.cover_image` or a per-run `--cover PATH` override; covers
must be JPEG or PNG and at most 5 MiB. `tts.max_retries` defaults to 2 and is
available as `PDF2AUDIOBOOK_TTS_MAX_RETRIES`; chapters still failing after
retries are reported individually and conversion exits 7 after processing
remaining chapters. Voice markers are honored only in approved chapters.
Failed chapter details stay in `reports/conversion_status.json` and are shown
by `inspect`; transient provider errors alone are retried. `inspect` reads that
file through one handle, at most `CONVERSION_STATUS_MAX_BYTES` (1 MiB, in
`cli/` package) plus one byte, and fails with "Conversion status file exceeds safe
size limit" (exit 3) when the read goes over the limit. The decision is made
from the bytes read, so a file that grows or is replaced before it is read is
still reported. A missing, unreadable, malformed, non-object or over-depth
status file is left out of the output. Known limitation: if the status path is
a FIFO or another non-regular file, opening or reading it can block, so
`inspect` can hang. A reviewed manifest
reason can be acknowledged with `convert --accept-review damaged_source`.
`--accept-review` accepts only the book-wide codes `damaged_source` and
`ambiguous_page_numbers`; it validates them before analysis (exit 2), logs a
`review_acknowledged` event per reason, and is honored by `--dry-run` without
rewriting the manifest. Empty chapters require approval of that chapter in the
review UI and are skipped with a report entry. Approval is per chapter: if a
different chapter becomes empty later, it is gated again. A legacy
`empty_chapter` value in `review_acknowledged` is retained in v3 manifests but
ignored, with a content-free `review_warning` event. The review page shows a
separate checkbox for each currently present book-wide reason; a title or
boundary save without its checkbox never acknowledges that reason, and chapter
approval never waives it.
Default stderr of a failed command is its own `Error:` line or one JSON object.
Events print for warnings; `--verbose` or an explicit `general.log_level` adds progress
and `command_failed`. Unexpected exceptions print "Unexpected internal error"; `OSError` and
`ValueError` keep their fixed messages; a busy `review` port reports a fixed message and
Ctrl+C ends `review` with exit 0.

### Machine-readable outputs for other programs

The desktop app (`docs/PDF2AUDIOBOOK_TAURI_SPEC.md`, D2) drives the CLI only through these
outputs, so treat their shapes as contracts: add fields, never rename or remove them.

- `--version` prints the version and exits 0, with or without a command after it.
- `asr list --json` (`desktop/contracts/asr-models.schema.json`) reports each optional speech
  recognizer's readiness without importing it; `asr fetch MODEL... --yes --json` downloads the
  pinned weights and adds `fetched`. `verify-audio MANIFEST --json`
  (`audio-verification.schema.json`) prints the book's verification report, also written to
  `reports/audio_verification.json`. See `docs/PDF2AUDIOBOOK_AUDIO_VERIFICATION_SPEC.md`.
- `resynthesize MANIFEST --chapter N --json` prints `mp3_files` (and `audio_verification` when
  the chapter is re-verified). Every chapter MP3 is encoded to `audio/.staging/`, committed with
  its sidecar through a journal (`audio/commit.py`), and the previous pair is kept in
  `audio/.backup/` (newest three per chapter); conversion first finishes any journaled commit and
  removes unjournaled staged files and leftover `tmp*` folders. Verification results judged with
  other model revisions than the pinned ones are reported stale.
- `audio-report show MANIFEST --json` (`audio-report.schema.json`) prints `report` (the saved
  verification report or null) and `stale` without importing any ASR package;
  `audio-report dismiss MANIFEST --chapter N --flag I [--undo] --json` (`audio-dismiss.schema.json`)
  sets one flag's `reviewed` under the book lock. A re-verification keeps `reviewed` on flags with
  the same kind, position and expected words in the same audio. The desktop app reads these and
  `asr list`; its walkthrough stands in for them with `desktop/e2e/fake_asr.mjs`, built from the
  bridge fixtures, so regenerate those fixtures from real output when these contracts change.
- Audio verification review fixes (`docs/PDF2AUDIOBOOK_AUDIO_VERIFICATION_REVIEW_FIXES_SPEC.md`): the
  reason codes `narration_not_spoken` and `audio_undecodable` and the `ffmpeg_missing` warning are in
  `verification/contracts.py` and both report schemas; `report_json`/`saved_report` are the only places
  the transcript-retention rule is applied; `compare.vote` groups by anchor; `backends.iter_windows`
  is the only way chapter audio is read. Keep these in step with `scripts/asr_benchmark.py score`.
- `inspect MANIFEST --json` includes `analyzed_with_llm`: `false` when the workspace's last
  analysis ran without the LLM (its `llm-analysis` fingerprint is the fixed "disabled" value),
  `true` when it used one, `null` when `reports/analysis_fingerprints.json` is missing or
  unreadable. The desktop app starts a book's options from it, so converting a book analyzed
  with `--no-llm` doesn't switch the LLM back on.
- `doctor --check-llm --json` adds `llm_check`. For Ollama it asks the server what context it
  serves for the configured model (this loads the model) and reports `served_context`,
  `configured_context`, `output_tokens`, `chunk_tokens`, `estimated_tokens_needed` (a window,
  the output cap, 128 tokens of overhead and a 4096-token allowance for instructions) and
  `enough`. Other providers report `"checked": false`. Without the flag doctor never contacts an
  LLM.
- `workspace BOOK [--output DIR] --json` prints `{"workspace", "exists", "warnings"}`. The
  folder uses the same rule as analysis (`pipeline.analysis_workspace_folder`:
  `<output_dir>/<stem>-<first 10 hex of the book's SHA-256>`); the command reads the book to
  hash it and writes nothing.
- Every `--json` error is one stderr object `{"ok": false, "error": {"type", "code",
  "message", "reason"?}, "warnings"}`. `reason` is present only for failures a caller can act
  on, and comes from `AudiobookError.error_reason` (set on a subclass or per raise; the older
  `LLMError.reason` is a separate log tag for `llm_request_failed`). The codes are
  `review_required` (low boundary confidence, or an unapproved empty chapter),
  `review_acknowledgement_required` (`damaged_source`, `ambiguous_page_numbers`),
  `workspace_locked`, `pending_recovery`, `chapter_conflict`, `llm_unreachable` (connection
  refused, or Ollama's served context can't be read), `llm_context_too_small`,
  `llm_output_cap` and `budget_exhausted`. A timeout is not `llm_unreachable`.
- An answer cut off at the output cap part way (`LLMAnswerCutOff`) fails only its window: every
  window-by-window LLM step asks through `advisory_common.WindowAnswers`, which skips that
  window (a warning, and an `answer_cut_off` decision) and raises `llm_output_cap` only when no
  window of the step got an answer. A cap spent before any answer (hidden reasoning) still
  stops the run at once. Found on a research paper where `qwen35-256k` echoed every line back
  as a no-op OCR edit, and lines full of invisible direction marks became long escapes.
  A step that lost windows adds a `CUT_OFF_SUMMARY` manifest warning with the counts and logs
  `llm_answers_cut_off`; `analyze --json` returns those lines as `notices`, which the app shows
  after the run. The cleanup and classification prompts ask only for lines that change or that
  aren't body text, so their answers don't grow with the window, and equation reading sizes its
  windows from the cap (`equations.equation_window_bytes`), since each reading repeats its record.
- `llm models --json` prints `{"provider", "configured", "models", "warnings"}` from the
  server's `/models` list (contracts/llm-models.schema.json); the desktop app's Model fields
  offer that list.
- `review --json` prints one flushed stdout line, `{"url": "http://127.0.0.1:<port>/",
  "port": <port>}`, once the server listens, and nothing else; `--port 0` picks a free port.
- SIGTERM stops any command like Ctrl+C (see the entry point below).
- `edits list --json` carries IDs, chapter, provider and status only; `--with-text` adds
  `original`, `replacement` and `reason` for the desktop app's pending-edits screen. Book text
  never appears in JSON without that flag.
- `voices [--tts-provider P] [--tts-model M] --json` prints `{"provider", "voices",
  "listable", "default_voice", "warnings"}`. Piper speakers are numbers inside the model, so
  Piper reports `"listable": false` and an empty list.
- `thumbnail BOOK --output FILE.png [--width N] --json` writes only that PNG (first page of a
  PDF, first page of an EPUB, where its cover usually is) and prints `{"thumbnail", "width",
  "height", "warnings"}`. The output folder must already exist.
`pack-m4b --cover` applies artwork to the M4B output; freshness checks use the
chapter text hash, independently of conversion voice, speed or cover settings.
Unknown and pending LLM requests count against their recorded worst-case token
and cost bounds. A provider 4xx rejection without usage is recorded as
`rejected`; inspect accounting with `budget show` before resolving ambiguous
requests.
The opt-in real Kitten smoke test requires both the `kitten` extra and
`PDF2AUDIOBOOK_KITTEN_SMOKE=1`; it is intentionally excluded from CI.

## Architecture and extension points

Page-number candidate ranking uses `PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT = 2.0` in
`document/pagination.py` (re-exported by `document/structure.py`): competing edge distances less than 2pt apart are tied
and retained for review. A difference of exactly 2pt is sufficient to select
the nearer candidate.

The executable `pdf2audiobook` maps to `pdf2audiobook.cli:main`
(`src/pdf2audiobook/cli/`, handler in `cli/_core.py`), which makes SIGTERM stop a run exactly as Ctrl+C does (exit 130,
`run_status.json` left as `stopped`, the workspace lock released) and then runs the Typer
`app`. Tests that call `app` in-process don't install that handler. Modules and their boundaries:

1. `config.py`: strict Pydantic TOML/env/CLI settings, provenance and
   validation; `errors.py` and `logging.py` provide domain diagnostics and
   privacy-safe structured events.
2. `pdf.py` and `reading_order.py`: `DocumentExtractor` protocol with the
   default `PyMuPDFExtractor`; PyMuPDF inspection, embedded/OCR extraction,
   provenance, geometry and conservative column-order decisions. `pdf.py`
   keeps extraction and `inspect_pdf`; `pdf_layout.py` classifies each page
   (visuals, text lines, tables, footnotes, special material, block kinds) and
   `pdf_ocr.py` decides when to OCR and runs Tesseract with its line cache.
3. `models.py` and `document/structure.py`: source-aligned models,
   pagination edits, chapter proposals, coverage checks and chapter rendering.
4. `llm/__init__.py`: `LLMProvider` protocol and OpenAI-compatible HTTP
   transport, endpoint validation, structured proposals and deterministic
   proposal verification. PDF text is untrusted user content, not instructions.
5. `tts/__init__.py`: `TTSProvider` protocol and lazily loaded Kitten
   adapter; `audio/__init__.py` is a facade over `audio/speech_text.py`
   (speakability, voice markers, source-aligned sentence chunks),
   `audio/synthesis.py` (the bounded WAV chunk cache and chunked synthesis),
   `audio/wav.py` (the streaming chapter WAV writer) and `audio/encoding.py`
   (`AudioEncoder` protocol, FFmpeg MP3 encoding with `encode_mp3`, and ID3
   metadata); it keeps only the output paths and the cover image.
6. `workspace.py`: SHA-256 identities and atomic JSON writes;
   `pipeline.py`: the facade and entry points (`analyze_book`,
   `convert_book`), stage fingerprints and chapter selection; `analysis/`:
   the analysis steps (state, extraction, cleanup, LLM proposals, hand edits, review and writing,
   and the orchestrator) and approved-edit protection; `conversion.py`: resumable
   synthesis and output checksums.

Typical call path:
`cli.analyze -> pipeline.analyze_book -> pdf.extract_pdf ->
document.structure -> optional llm -> workspace.write_manifest`.
Conversion additionally calls `pipeline.convert_book -> tts.KittenProvider` or
`tts.PiperProvider` ->
audio.synthesize_chunks -> audio.encode_mp3`. The TTS model is not loaded
for an up-to-date cached MP3. `analyze_book`/`convert_book` accept
`extractor=`, `tts_provider=` and `encoder=` replacements; an injected adapter
is folded into the analysis, chunk and MP3 cache identities so it never reuses
artifacts made by the defaults.

**Orchestrators and their steps.** The long pipeline functions are short
orchestrators that call named steps in a fixed order. Shared state passes
through a small private dataclass per run, never module state. When you change
a step, keep the order: several steps are fail-closed checks that must run
before anything is reserved, sent or written.

- Analysis, `analysis._analyze_book_locked` (state in `_AnalysisRun` and
  `_AnalysisState`; every dependency that tests patch on `pipeline` is called
  through `AnalysisServices`, built by `pipeline.analyze_book` at call time):
  1. `_start_analysis`: hash the source and fingerprint each stage.
  2. `_reuse_existing_analysis`: keep, update (`_switch_footnote_policy`) or
     refuse an existing manifest.
  3. `_extract`, then `_deterministic_cleanup`: pagination and the footnote
     policy.
  4. `_llm_proposals`, with `_run_llm_tasks` and `_deterministic_fallback`.
  5. `propose_chapters`.
  6. `_merge_hand_edits`: the hand-edit merge, using `_HandEditMerge`.
  7. `_chapter_review`, then `_write_analysis`.

  `tests/test_patch_targets.py` fails if any `analysis/` module or `conversion.py`
  calls a name that tests patch on `pipeline` directly instead of through its
  services record.
- Conversion, `conversion._convert_analyzed_book` (state in `_ConversionRun`;
  every dependency is called through `ConversionServices`):
  1. Load the manifest and chapter selection.
  2. `_preflight_voice_markers`, then `_initial_status`.
  3. `_plan_synthesis`: decide which MP3s to reuse, including the MP3 tag check.
  4. `_convert_chapter` for each pending chapter: synthesize, encode, then
     `_publish_chapter`.
  5. `_write_conversion_status`.
- Lower-level orchestrators split the same way:
  - `pagination_cleanup`: one named predicate per fail-closed margin rule;
  - `propose_chapters`: state in `_HeadingEvidence`;
  - `audio.synthesis.synthesize_chunks`: validation runs before any engine call or cache
    replay;
  - `CachedLLMProvider._complete_json_call`: request bounds before the cache
    lookup, and server limits before the reservation. A wrapper given a limit but
    no `ledger_path` owns a temporary ledger; `close()` (or `with`) removes it and
    then refuses uncached requests. Analysis always passes the book's ledger, so it
    never makes one; tests that do use the `closing` fixture in `tests/conftest.py`;
  - `OpenAICompatibleProvider._complete_json_request`: each attempt is an
    explicit `_Attempt` that is settled exactly once;
  - `pdf.extract_pdf`: state in `_ExtractionRun`;
  - `llm.structure.propose_llm_contents_boundaries`: state in `_ContentsReview`;
    each window's entries, then its boundaries, are verified against their
    exact source lines before any entry is mapped to a later heading;
  - the CLI `convert` command, through `_run_convert` and `_dry_run_convert`.

**Change safety:** Preserve raw spans/blocks and the one-time prose-coverage
invariant. Introduce schema versions or migrations deliberately; update
analysis/audio fingerprints when changing derived semantics. Keep the LLM
transport consent gate and the separation between untrusted model proposals
and accepted edits. Verify output reuse by fingerprint **and** file checksum,
not by filename or progress-ledger status alone. Test provider failures with
mock transports and audio with synthetic signals before real-model acceptance.

## Development, CI and troubleshooting

```bash
uv lock --check
uv sync --locked --extra dev
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev mypy
uv run --extra dev pytest -q -ra
uv run --extra dev pdf2audiobook --help
uv run --extra dev pdf2audiobook doctor --json
```

Ruff formatting is enforced repository-wide. Mypy checks the explicit `[tool.mypy].files` list in
`pyproject.toml`; add every new module there. `tests/test_function_length.py`
fails when a function under `src/` is over 100 lines. Typer commands are
measured from their first body statement. Its `ALLOWLIST` names the older
functions still over the limit, each with its current line count as a ceiling.
Such a function may shrink but never grow. Remove its entry once the function
is split; the test fails on stale entries. Don't add an entry to make new code
pass; split the function instead. Third-party libraries that print
to stdout (PyMuPDF messages, kittenml's per-chunk echo) are silenced or routed
to stderr at their adapter so `--json` output stays parseable and narration
text never reaches logs.

`.github/workflows/ci.yml` runs these offline checks on `master`, installing
Node.js 22, FFmpeg, Tesseract and English language data. Pytest uses `-ra` so
the CI summary shows whether the Node-, FFmpeg- and Tesseract-gated tests ran.
The apt install is time-bounded,
retried against archive.ubuntu.com and served from an `actions/cache` of the
`.deb` files (bump the `apt-…-v1` key when the package list changes), because
the runners' regional mirror intermittently stalls for hours. It does **not** install Kitten
models, call external LLMs, or validate all real scanned-book layouts. Record
the exact commit SHA and Actions run when claiming CI acceptance. Before
marking a TODO complete, add a deterministic regression test or explicitly
document environment-dependent/manual acceptance evidence.

`.github/workflows/desktop.yml` ("Desktop CI") checks the Tauri app in `desktop/` on Ubuntu
22.04: frontend lint, types, tests and build, `cargo fmt`, `clippy` and `cargo test`, a release
build with the AppImage and `.deb` carrying the built-in engine (uploaded as
`pdf2audiobook-desktop-linux-unsigned`), a clean-machine check, and the `tauri-driver` walkthrough
under Xvfb, of the build and of the AppImage. It shares `ci.yml`'s uv pin (`tests/test_desktop_ci.py`
checks both workflows together) and has its own apt cache key (`apt-…-desktop-webkit-v3`; bump
it when that package list changes). See `desktop/README.md` for running the same checks
locally.

### The desktop app's built-in engine

The AppImage and `.deb` carry their own engine (the
[Self-Contained App Specification](PDF2AUDIOBOOK_SELF_CONTAINED_APP_SPEC.md)): Python 3.11 (python-build-standalone, as
`uv` installs it), this CLI and its locked core packages, Kitten's ONNX voice path without PyTorch, FFmpeg,
English OCR data, the default voice model, the add-on package lists and the licence notices.
Desktop CI builds it (`desktop/scripts/build_engine.py`), smoke-tests it offline
(`smoke_engine.py`), adds it to both installers after `tauri build` (`package_engine.py`, which
writes the sizes to the run summary), and runs the smoke test from inside the AppImage in a stock
Ubuntu 22.04 container with no network (`clean_machine_check.sh`). The AppImage walkthrough then
runs with `E2E_BUNDLED=1`: no CLI configured, real speech from the bundled voice. The commands
for a local build are in [desktop/README.md](../desktop/README.md#building-an-installer).
Downloads and the FFmpeg build are cached in `~/engine-cache` in CI (`tmp/engine-cache`
locally); every cached file is checked against its pinned hash on use.

Everything the engine contains is pinned, and each pin has one place to change:

| What | Where | How to update |
|---|---|---|
| Python packages | `uv.lock` | As for the CLI. The engine follows the lock; `tests/test_addon_lists.py` fails until the add-on lists are regenerated. |
| Add-on package lists | `desktop/engine/addons.lock.json` | `uv run python desktop/scripts/addon_lists.py` (generated from `uv.lock`; `--check` compares). The CPU PyTorch and torchaudio wheels are pinned in `pins.json` (`addons.cpu_wheels`) at the locked versions; update their URLs and SHA-256 together with the lock. |
| Python itself | `pins.json` `python` and `python_build`, and `ENGINE` in `addon_lists.py` | All name the same CPython version. `python_build` is the python-build-standalone `install_only_stripped` archive uv installs, pinned by URL and its release's `SHA256SUMS` entry, so the build doesn't depend on the uv version's download list (CI's uv 0.12.9 doesn't list 3.11.18). Regenerate the add-on lists after changing it. |
| FFmpeg and LAME | `pins.json` `ffmpeg` | Download the new FFmpeg release tarball and its `.asc` from ffmpeg.org, check the signature against the FFmpeg release key (fingerprint `FCF9 86EA 15E6 E293 A564 4F10 B432 2F04 D676 58D8`), then pin its URL and SHA-256. LAME is pinned the same way. |
| FFmpeg's features | `FFMPEG_CONFIGURE` in `build_engine.py` | Only what the engine uses is built in. FFmpeg's `configure` silently ignores a name it doesn't know (the raw PCM formats are `pcm_f32le` and `pcm_s16le`, not `f32le`), so when the engine starts using FFmpeg in a new way, add a check to `FFMPEG_USES` in `smoke_engine.py` too. The build must stay static; it stops if it isn't. |
| English OCR data, the voice model | `pins.json` `tessdata`, `models` | URL or revision, and SHA-256 of each file. |
| OCR languages users can add | `desktop/engine/tessdata.json` | `python3 desktop/scripts/tessdata_catalog.py` (needs `gh`); pinned by size and git blob hash. |
| Copyleft source for the source archive | `pins.json` `sources`, `uv.lock`, `Cargo.lock` | `source_archive.py` takes FFmpeg and LAME from `ffmpeg`, Python packages from their `uv.lock` sdists and crates from `Cargo.lock`. `sources` pins what has neither: espeak-ng and `espeakng-loader` as GitHub archives of the commits under `licenses` (keep them in step). The archive build stops when a copyleft component has no source; add it here. |
| Licence texts the app's crates and npm packages don't ship | `desktop/licenses/` | The SPDX MIT, BSD-3-Clause and MPL-2.0 texts (license-list-data v3.27.0) and the AGPL-3.0 text; `app_notices.py` stops when a package ships no text and its licence has none here. |
| Licence texts a component doesn't ship | `pins.json` `licenses` | The Apache-2.0 text, espeak-ng's GPL-3 (at the exact espeak-ng commit `espeakng-loader` builds) and `espeakng-loader`'s MIT licence. The build stops when a bundled package has no licence text; add one here. |
| The clean machine | `clean_machine_check.sh` | An `ubuntu:22.04` image pinned by digest. |

**Size budget** (spec C8): each installer at most 400 MB compressed, the installed app at most
1 GB, before add-ons. `package_engine.py` fails the build over either. Measured 2026-11-27 in
Desktop CI #140: the AppImage 258 MB, the `.deb` 159 MB compressed and 469 MB installed. The
AppImage carries the build machine's WebKitGTK and GStreamer, so a build on a newer distribution is
larger (356 MB on Debian 13). The largest parts of the engine are ONNX Runtime, PyMuPDF,
NumPy and the voice model.

**Licences** (spec C9): the repository's code is Apache-2.0, but the installers combine it with
copyleft components in the engine: FFmpeg and LAME (LGPL, with their exact build recorded in
`share/licenses/ffmpeg/BUILD.txt`), espeak-ng (GPL-3.0), PyMuPDF (AGPL-3.0), phonemizer (GPL-3.0),
mutagen (GPL-2.0), and certifi and tqdm (MPL-2.0); the app links five MPL-2.0 crates. So the
installers, as a whole, are distributed under the GNU AGPL 3.0, and each one's complete source goes
with it:

- The engine build writes `share/licenses/components.json`, every engine component with its
  licence, source and licence texts. `package_engine.py` adds the app's own list
  (`app_notices.py`) at `usr/lib/pdf2audiobook/licenses`, the app as distributed first. Settings
  → About shows the AGPL statement, both lists and every text.
- Desktop CI builds the source archive (`source_archive.py`) and uploads it in the same artifact as
  the installers. Publish it next to them wherever they go: an installer handed out without its
  source archive is not licence-compliant.
- A new dependency under GPL, LGPL, AGPL or MPL needs its source pinned (an sdist in `uv.lock`
  does it for Python packages); one under a licence that is not compatible with the AGPL 3.0
  (GPL-2.0-only, for example) cannot ship in the installers.

**Add-ons** install with the engine's own `pip` into
`$XDG_DATA_HOME/pdf2audiobook/addons/<engine version>/<component>/`, one folder per group of
packages, so packages both add-ons need are installed once. A component counts only once its
completion record exists, so an interrupted install is ignored and cleaned up. A new engine version
uses a new folder; the app then says the old add-ons are no longer used.

The `ollama_context` pytest marker bypasses the autouse stub for Ollama served
context discovery. Apply it only to tests intended to exercise the live local
Ollama `/api/ps` lookup; the ordinary suite must remain offline. Use
`uv run --extra dev pytest -m ollama_context -q` only when Ollama is available.

If OCR is missing or produces almost no text, check `doctor --json`, OCR
language packs and `--ocr` mode; inspect extracted source spans. If chapters
are unexpectedly merged or rejected, inspect `manifest.json` warnings,
`coverage.json` and confidence thresholds; use
`--allow-single-chapter` only after review. If a local LLM is unreachable,
verify the server URL/model and retry with `--no-llm` to isolate extraction.
If audio is stale, inspect the chapter's `*.cache.json` and rerun with
`--force`; checksum-invalid chunks should be regenerated. If a manually
approved manifest blocks reanalysis, preserve it and use a new output
directory. If FFmpeg or Kitten is unavailable, install the missing dependency
and check `doctor` before rerunning. Keep secrets and full book text out of
bug reports.

## Real-model workflow

`.github/workflows/real-models.yml` runs the opt-in real-model tests on GitHub-hosted runners.
It is started by hand only (`workflow_dispatch`); it never runs on push, pull request or
schedule, and it is not a required check. Main CI (`ci.yml`) stays offline.

Start it from `master` with the Actions UI, or:

```bash
gh workflow run real-models.yml --ref master \
  -f suites=kitten,asr,clone-short,clone-long -f asr_models=wav2vec2,vosk,whisper
```

Suites: `kitten` (Kitten smoke test), `asr` (one job per model in `asr_models`; Whisper needs
8 GiB of RAM and fails fast on smaller runners), `clone-short` and `clone-long` (CPU voice
cloning; the long-form job runs even if the short one fails). The reference voice and its
transcript come from the pinned Kitten 2 voices file and are staged in a runner temporary
folder that is deleted afterwards. Nothing is uploaded as an artifact.

Torch is replaced by its CPU build at the locked versions after `uv sync --locked`
(`.github/scripts/install-cpu-torch.sh`); the job fails if a CUDA build remains. `uv.lock` is
not changed. Model caches are keyed by the pinned revisions (`.github/scripts/pinned-revision.sh`
reads them from `tts/catalog.py` and `verification/models.py`): `real-kitten2-<revision>` and
`real-asr-<model>-<revision>`; the Kitten `mini` cache follows `uv.lock`. A restored file is
still checked against its pinned size and SHA-256 and downloaded again if it fails. Each job
summary lists its cache hit or miss and, per test, wall time and peak RSS. `suites` takes exact
names; a job whose name is not listed is skipped.

A green run shows that the real models load and produce output on a clean runner. It does
not show speaker similarity, pacing or audible quality; those need a person listening. The
accelerator gates (VC0.03, VC8.04) still need a GPU machine.

## Outstanding release gates

The TODO remains authoritative: capable-model
LLM, llama-server and consented OpenAI acceptance, human listening review of
real Kitten audio, and real-book/difficult-scan special-material qualification
are still outstanding. Documentation and offline CI
passing do not close these gates.

## Chapter artifact persistence

`chapter_artifacts.py` plans generated text, records chapter identities, source/rendering
fingerprints, generated digests, observed edits and the footnote policy. It refuses ambiguous
legacy files and edits affected by changes to their rendering inputs. `review_transaction.py`
publishes the manifest and derived artifacts via a committed journal, checks target digests during
recovery, and is invoked while the workspace lock is held. The journal can contain book text and
must be treated as private workspace data. A committed journal is replayed when a workspace lock
is next acquired; if a target changed externally, back it up and restore its pre-transaction bytes
before retrying. Do not delete an unresolved journal as a recovery shortcut.
Transactions larger than 512 MiB are rejected before commit; the encoded journal includes the
manifest and any generated chapter files being published.

`pipeline.py` is the entry point: it delegates analysis to the `analysis/` package and chapter conversion to `conversion.py`.
`analysis_state.py` preserves reviewed decisions, `chapter_selection.py` applies review gates,
and `tts/selection.py` resolves profiles and model identities. The document package separates
chapter detection (`structure.py`), pagination, coverage, list classification and narration.
The audio package separates speech text, synthesis, the chapter WAV writer, progress records, encoding and sidecar validation. The LLM
package separates provider transport, shared advisory schemas, and structure proposals. Existing
imports from `pipeline`, `document.structure`, `audio`, and `llm` remain available. The transaction
and artifact modules keep workspace persistence out of the renderer's domain logic.

Old workspaces without artifact metadata are adopted only where files match the current rendered
text. `resolve_footnote_policy` infers the policy of such a workspace from the manifest's
footnote edits and its recognizable (unedited) chapter files, and refuses when it is ambiguous;
`regenerate-chapter --footnotes` is the explicit escape hatch. Preserve differing files with
`regenerate-chapter` (backups go to `chapter-backups/`, never overwritten) before using a fresh
workspace. The edited flag records only edits that an operation has observed, so it cannot
detect a file edited and deleted between operations.

Read-only access (`workspace.read_manifest`, the review page's `GET /api/manifest`) never takes
the workspace lock, creates files or runs recovery; it raises `PendingRecoveryError` while a
journal exists. Only lock holders recover. `workspace_lock(create=True)` is for writers that may
start a workspace; `recover=False` is reserved for the `recover` command, which completes a
blocked transaction itself (`--back-up-changed` copies changed targets to `chapter-backups/` or
`workspace-backups/` first). Save outcomes carry stable `outcome` codes
(`not_saved_conflict`, `not_saved_pending_recovery`, `committed_needs_recovery`) that the review
page maps to messages; forward only the allowlisted messages of `ChapterConflictError` and
`PendingRecoveryError`. `commit_artifacts` returns without writing a journal when nothing
changes.

## Citation and equation reading

`[reading]` holds two independent, default-on booleans (`process_citations`,
`process_equations`; env `PDF2AUDIOBOOK_PROCESS_*`; paired CLI flags on `analyze` and
`convert`). Equation processing requested explicitly (env, TOML or CLI) with the LLM disabled is a
`ConfigError` (exit 2); left at its built-in default it is quietly set false when the LLM is
off, and the `auto` model resolution also counts it as an LLM consumer.

**Citations** are deterministic. `audio/citations.py` finds bracketed integer lists and
ascending ranges (`citation_ranges`) and `mask_citations` blanks them to spaces, moving any
closing punctuation into the gap, without changing the length. `synthesize_chunks` and
`unspeakable_pause_ranges` take `skip_citations` and mask after the voice markers, exactly like
voice markers, so chunking and the chunk-to-source mapping stay valid. The chapter file is
never touched. Bibliography entry numbers (`[1] Author. Title.`) match the pattern and are
skipped on purpose; a chapter left with no speakable text raises the usual `AudioError`, which
`convert` reports as a content-free `PartialConversionError` for that chapter only (the title
normally keeps a chapter speakable, so this needs a hand-edited chapter file).
`conversion.py` passes `skip_citations` only when on (injected synthesis doubles
need not accept it), records `"citations": true` in the sidecar's `rendering_inputs` and adds a
part to `chapter_audio_fingerprint` only when on, so the identity is byte-identical when off. Being
on by default, existing audio regenerates on its next `convert`.
`pack-m4b` ignores the key.

**Equations** are an LLM task (`llm/equations.py`). `equation_candidates` picks blocks by symbol
test, `verify_reading` rejects unfaithful readings (digit stream, surviving words, length,
markup), and `propose_llm_equation_readings` stores survivors as `CleanupEdit(provider="llm",
accepted=False)`. The analysis hook runs after the other stages. The setting is deliberately
**not** in any stage fingerprint: with it on by default, a fingerprint part would make every
existing workspace stale and refuse re-analysis of approved ones.

**Pending edits** are resolved with `pdf2audiobook edits list|accept|reject` (`edit_review.py`).
`accept` flips the flag in memory and calls `render_chapter_texts(commit_manifest=True)` under
the workspace lock, so manifest and chapter files publish together; a hand-edited chapter is the
usual content-free conflict. `reject` rewrites the manifest without the proposal. Both append
block IDs and actions (no text) to `reports/edit_decisions.json`. A rejected proposal can return
on re-analysis, because the cached model answer is unchanged.

Status is derived by `edit_status`: accepted, rejected (an unaccepted `deterministic` edit, which
starts accepted, so it records a human rejection that reanalysis preserves) or pending. `accept`
and `reject` touch only pending edits, and `accept` refuses a block that already has an accepted
edit because accepted edits apply as a block-to-replacement map. An accepted non-deterministic
edit makes the workspace approved content in `pipeline` (`other_approved_content`), so a later
re-analysis is refused with the existing message. A failed audit write is a `WARNING` event,
`edit_audit_not_written`; the decision itself is already published.

## Request timeout and progress display

`llm.<provider>.timeout_seconds` (Ollama 300, others 60) becomes the `httpx` read/write/pool
timeout in `create_provider`; the connect timeout is `min(10, timeout)` and the Ollama `/api/ps`
lookup always uses 10 s. It is excluded from analysis fingerprints and cache identities.

`progress_display.py` is the only module that imports `tqdm`. Pipeline code receives a
`ProgressReporter` (`analyze_book(progress=)`, `convert_book(progress=)`) and calls
`stage(name, total, unit, initial)`; the CLI passes one only when it is enabled (injected
adapters and test doubles need not accept it). `NullReporter` is the default and is used under
`--json`, `--quiet`, `--no-progress` and, for `auto`, when stderr is not a terminal. Stages:
extraction pages (`pdf.extract_pdf(progress=)`), LLM requests (`CachedLLMProvider.progress`,
with each stage announcing its window count through `llm.advisory_common.planned_windows`),
synthesis characters (`audio.synthesize_chunks(on_chunk=)`, cached and resumed work counted as
`initial`/`cached=True` so it does not distort the estimate) and `pack-m4b` chapters/encode.
The CLI wraps the chosen reporter in `StatusReporter`, installs it with `use_reporter` (a context
variable read by `current_reporter()`, so no new argument is threaded through the pipeline or its
test doubles) and `bind_workspace` tells it where `reports/run_status.json` lives. A daemon thread
refreshes that file and prints the optional heartbeat; `summary()` marks the run `completed` and a
bare `close()` marks it `stopped`. `CachedLLMProvider._observe` emits `llm_request`,
`llm_request_failed` and `llm_slow_request` using per-stage baselines; `LLMError.reason` carries a
stable tag such as `output_cap`.
Bar text may contain only stage names, counts and chapter numbers. Log lines go through
`progress_display.write_stderr` so they do not corrupt an open bar. When the terminal size is
unknown (a pseudo-terminal reporting 0x0), explicit dimensions are passed because tqdm would
otherwise draw nothing.
On platforms without POSIX locking, the existing lock implementation does not serialize processes;
directory fsync is unavailable on Windows. Avoid concurrent workspace operations there.

## Voice cloning contracts

`tts/catalog.py` ships a pinned model/decoder manifest and explicit, integrity-checked setup.
`tts/cloning.py` owns typed selections, bounded canonical snapshots and public hash identities;
`tts/clone_provider.py` binds one reference to a `worker_client` subprocess. `clone_worker` is
offline and receives content only through private pipes. Keep the Kitten 0.8 and Piper paths
unchanged when cloning is inactive. Model preparation may take 15 minutes; cancellation terminates
and reaps the worker after a short grace period, with a Linux parent-death signal for force stops.

Clone fields belong only in active audio identities, never analysis identities. Sidecars carry
only digests and generation settings. Resume may restore recorded identity to reuse valid audio
without loading the SDK or original reference. New synthesis must prepare a real snapshot.
Repair uses existing staging/backups and requires explicit intent to change from a clone.

Kitten 2 sampling temperature (`tts.kitten.temperature`, default `0.2`, range `0.05`–`1.5`;
[spec](PDF2AUDIOBOOK_KITTEN2_TEMPERATURE_SPEC.md)): `create_tts_provider` passes it to
`Kitten2BuiltinProvider` and `KittenCloneProvider`, which send it in each worker request.
`clone_worker` hands it to `generate()` with `preset="stable"` and `seed=0` unchanged. It enters
audio identity in two places: the Kitten 2 model identity in `tts/selection.py`
(`kitten2-model-v2`, which feeds the chunk-cache keys, progress identity and chapter fingerprints),
and the sidecar's `rendering_inputs.kitten2_temperature` (only when Kitten 2 is selected). The
clone reference identity (`GENERATION` and the reference digests) does not include it. Kitten 0.8,
Piper and analysis identities never see it. Changing the default therefore regenerates all Kitten 2
audio made at the old default on its next conversion, for built-in and cloned voices, while other
models' audio and all analysis are kept. Choose a new default with a real-model comparison and a
listening check, as K5 of the spec describes, and record it in that TODO's ledger.

Rust flattens reference options into conversion/repair requests. Typed drafts are written to
restricted files and captured by the child exit hook; Details and Debug redact reference fields.
Startup sweeps only marked unlocked private jobs. React keeps drafts in session memory; shared
configuration paths are saved explicitly. Update CLI schemas, Rust fixtures, TypeScript options
and privacy/lifecycle tests together. Real-model/listening checks are tracked separately in the
[voice cloning backlog](PDF2AUDIOBOOK_VOICE_CLONING_TODO.md).
