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
like outlined text (`pdf.py`): at least `_VECTOR_GLYPH_MIN_PATHS` (40) small
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
by `inspect`; transient provider errors alone are retried. A reviewed manifest
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
`document/structure.py`: competing edge distances less than 2pt apart are tied
and retained for review. A difference of exactly 2pt is sufficient to select
the nearer candidate.

The executable `pdf2audiobook` maps to `pdf2audiobook.cli:app`
(`src/pdf2audiobook/cli.py`). Modules and their boundaries:

1. `config.py`: strict Pydantic TOML/env/CLI settings, provenance and
   validation; `errors.py` and `logging.py` provide domain diagnostics and
   privacy-safe structured events.
2. `pdf.py` and `reading_order.py`: `DocumentExtractor` protocol with the
   default `PyMuPDFExtractor`; PyMuPDF inspection, embedded/OCR extraction,
   provenance, geometry and conservative column-order decisions.
3. `models.py` and `document/structure.py`: source-aligned models,
   pagination edits, chapter proposals, coverage checks and chapter rendering.
4. `llm/__init__.py`: `LLMProvider` protocol and OpenAI-compatible HTTP
   transport, endpoint validation, structured proposals and deterministic
   proposal verification. PDF text is untrusted user content, not instructions.
5. `tts/__init__.py`: `TTSProvider` protocol and lazily loaded Kitten
   adapter; `audio/__init__.py`: `AudioEncoder` protocol, source-aligned
   chunks, WAV validation, PCM assembly, FFmpeg MP3 encoding (`encode_mp3`)
   and ID3 metadata.
6. `workspace.py`: SHA-256 identities and atomic JSON writes;
   `pipeline.py`: analysis, approved-edit protection, stage fingerprints,
   chapter selection, resumable synthesis and output checksums.

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
`pyproject.toml`; add every new module there. Third-party libraries that print
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

`pipeline.py` coordinates analysis and delegates chapter conversion to `conversion.py`.
`analysis_state.py` preserves reviewed decisions, `chapter_selection.py` applies review gates,
and `tts/selection.py` resolves profiles and model identities. The document package separates
chapter detection (`structure.py`), pagination, coverage, list classification and narration.
The audio package separates synthesis, progress records, encoding and sidecar validation. The LLM
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
Bar text may contain only stage names, counts and chapter numbers. Log lines go through
`progress_display.write_stderr` so they do not corrupt an open bar. When the terminal size is
unknown (a pseudo-terminal reporting 0x0), explicit dimensions are passed because tqdm would
otherwise draw nothing.
On platforms without POSIX locking, the existing lock implementation does not serialize processes;
directory fsync is unavailable on Windows. Avoid concurrent workspace operations there.
