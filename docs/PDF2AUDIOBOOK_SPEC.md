# PDF2Audiobook — Technical Specification

**Status:** Initial design, implementation-ready  
**Date:** 2026-10-16  
**Repository:** https://github.com/ekkus93/pdf2audiobook  
**Companion:** docs/PDF2AUDIOBOOK_TODO.md

## 1. Purpose

Build a Python command-line application that converts PDF books into high-quality, chapter-separated MP3 audiobooks. It must handle digitally typeset PDFs, scanned/image-only PDFs, and mixed PDFs; strip pagination noise; recover readable prose; locate exact chapter boundaries; and synthesize audio using Kitten TTS initially. Intelligent document analysis uses a configurable LLM provider: OpenAI API, Ollama, or llama-server. All four major subsystems (extraction/OCR, structure analysis, text preparation, and speech generation) must have clean interfaces.

The target is an **offline-first, inspect-before-synthesize, resumable** utility. Remote LLM requests require explicit content-upload consent.

## 2. Product requirements

### 2.1 Functional requirements

| ID | Requirement | MVP |
| --- | --- | --- |
| FR-001 | Accept one PDF via Python CLI, output one MP3 for each detected chapter in a deterministic directory | Yes |
| FR-002 | Extract selectable text and preserve block order, style, coordinates, and PDF page identity | Yes |
| FR-003 | Detect image-only/scanned pages, run OCR automatically at configurable language/DPI, and support mixed PDFs | Yes |
| FR-004 | Detect/remove page numbers and repeated running headers/footers without removing ordinary text | Yes |
| FR-005 | Repair line wraps, safe end-of-line hyphenation, and paragraph continuity | Yes |
| FR-006 | Detect chapter start/end from bookmarks, TOC, typographic/layout patterns, and LLM analysis | Yes |
| FR-007 | Support chapter boundaries mid-page and preserve text spans exactly once | Yes |
| FR-008 | Let a user inspect/edit the proposed chapter structure and cleaned text before synthesis | Yes |
| FR-009 | Support OpenAI API, Ollama, llama-server via replaceable LLM provider interface | Yes |
| FR-010 | Support a TOML defaults file plus environment overrides and CLI arguments | Yes |
| FR-011 | Use Kitten TTS through a provider interface and allow future TTS engines | Yes |
| FR-012 | Synthesize in sentence-aware chunks and produce one playable tagged MP3 per chapter | Yes |
| FR-013 | Resume interrupted work using content-addressed stage caches and an explicit manifest | Yes |
| FR-014 | Permit running with --no-llm; report weaker chapter-detection confidence where applicable | Yes |
| FR-015 | Output structured logs, progress, error diagnostics, and optional usage/cost accounting | Yes |
| FR-016 | Validate external dependencies, model availability, and local/remote connectivity using doctor | Yes |
| FR-017 | Batch convert directories, GUI, EPUB, cloud sync, and multilingual automatic translation | No (future) |

### 2.2 Nonfunctional requirements

- Python >=3.11, Linux first; CLI and core implementation should remain portable to macOS/Windows.
- Process book contents locally by default. OpenAI content upload must be gated by a deliberate --allow-remote-content flag or saved explicit opt-in; do not infer consent from choosing OpenAI.
- No unsupported claim that an LLM can perfectly recognize every document. Expose uncertain results, diagnostics, and manual fixes.
- Keep source PDF intact. Never alter the raw source transcript; preserve page and block provenance through all transformations.
- No silent omission, duplication, arbitrary summarization, hallucinated sentences, or text rewriting. Every cleanup modification is explainable and auditable.
- Repeated conversions with identical inputs/settings must produce stable chapter IDs and reuse valid caches. Model nondeterminism must not alter an already-approved manifest.
- No hardcoded API keys, tokens, or user documents in logs. Respect reasonable API rate limits and set timeouts, retry limits, and cost budgets.
- Fail with specific actionable errors if FFmpeg, Tesseract, TTS model, or the selected LLM is missing.

## 3. Architecture and data flow

```text
PDF
  |
  +--> PDF inspector (metadata, outline/bookmarks, TOC, page geometry)
  |
  +--> Page extractor (PyMuPDF text spans and reading-order heuristics)
           |                                  |
           +--> text usable ------------------+
           +--> inadequate -> Tesseract OCR --+
                                               |
                                      normalized document blocks
                                               |
                              deterministic layout/pagination cleanup
                                               |
                   LLM-assisted structure/correction proposals (optional)
                                               |
                          verifier + confidence + user overrides
                                               |
                      chapter manifest + inspectable chapter text
                                               |
                      narration normalization / chunk planning
                                               |
                      TTS provider -> PCM chunks -> FFmpeg MP3
                                               |
                         tagged chapter MP3 + progress manifest
```

### 3.1 Module boundaries

- **config/**: typed models, built-in defaults, TOML read, environment and CLI overlay, effective-config display (with redaction).
- **pdf/**: PyMuPDF adapter, page inspection, text geometry, reading-order recovery, PDF bookmarks/TOC, image/region OCR fallback.
- **document/**: normalized block/span models, deterministic cleanup, pagination classifiers, segmentation, chapter override validation, source mapping.
- **llm/**: provider protocol, OpenAI/Ollama/llama-server implementations, prompts, schema validation, bounded-request orchestration.
- **tts/**: provider protocol and initial Kitten adapter; device/model/voice selection; text-to-audio chunk service.
- **audio/**: chunk stitching, silence/pause policy, normalization if enabled, FFmpeg encoding, Mutagen/ID3 metadata, output naming.
- **pipeline/**: stage orchestration, cache invalidation, resuming, checkpoints, atomic filesystem writes, manifests.
- **cli/**: Typer commands, output/progress formatting, diagnostics, consistent exit codes.

Suggested package layout: src/pdf2audiobook/{cli,config,pdf,document,llm,tts,audio,pipeline}; tests/{unit,integration,fixtures,golden}; docs/.

### 3.2 Canonical intermediate representation

Use typed/Pydantic structures with schema_version for persistence:

- **SourceSpan:** PDF page index (0-based internally), displayed page label when known, bounding box, extraction origin (embedded/OCR), raw text, optional font/style, confidence, stable ID.
- **DocumentBlock:** stable ID, ordered SourceSpan IDs, kind (heading/paragraph/list/table/footnote/caption/unknown), reading order and normalized text; maintain provenance.
- **CleanupEdit:** block/span IDs, original/new substring or anchored range, edit type, reason, confidence, stage/provider/model and human-approval state.
- **Chapter:** stable ID, ordinal, displayed title, start/end block offsets (inclusive start/exclusive end), PDF page range, source evidence, confidence and optional explicit override.
- **NarrationChunk:** chapter ID, sequence, source/text hash, speakable text, TTS provider/model/voice/settings cache key, output artifact/checksum, status.
- **BookManifest:** schema/version, input SHA-256, title/author, extraction settings, effective provider settings (secrets redacted), chapter list, cached stage fingerprints, warnings and approval status.

Canonical raw text and intermediate files must remain independently inspectable. Separate **source text**, **cleaned transcription**, and **speakable narration text**.

## 4. Extraction, OCR, and cleanup

### 4.1 Page-by-page extraction

1. Read document metadata, outline/bookmarks, page labels, page dimensions, and text blocks with PyMuPDF.
2. Choose a per-page or per-region strategy using text quantity, replacement characters, coverage, font/text validity and image coverage. A text layer can exist but be unusable; do not assume all selectable text is good.
3. Extract with coordinates and recover reading order for one- or two-column pages; keep headings and body blocks distinct. Retain explicit uncertain-order warnings.
4. For missing/bad regions, rasterize at configured DPI and OCR with installed Tesseract language packs. Avoid OCR duplication when embedded text is adequate; do not mix duplicates into the transcript.
5. Cache page extraction/OCR keyed by PDF bytes, page index, crop/rotation, DPI, languages and extractor/OCR version. Keep per-page confidence/diagnostics.
6. For encrypted/password-protected files, allow a password input without logging it; fail if password is unavailable. Do not bypass DRM.
7. If the parser reports repair or a page cannot be loaded, retain a content-free warning with affected page numbers where known and require chapter review before synthesis.

OCR modes: **auto** (default), **always**, **never**. OCR languages default to eng; user can override. Orientation correction, deskew and preprocessing may be added as needed; keep all rasterizations ephemeral or cached locally.

In auto mode, OCR only pages with raster coverage above the configured trigger, unusable embedded text, or dense vector drawings without usable text. Keep short valid selectable text, and do not invoke OCR for image-free blank pages. A drawing-only page is dense vector artwork when it has at least 40 small filled glyph-sized paths (outlined text) or at least 100 paths covering 15% of the page. A text-free page with at least 10 drawn paths that is not OCRed is reported as unreadable drawings and sets `damaged_source`; it is never described as not needing OCR.

### 4.2 Page-number and header/footer detection

- Use positional signals (top/bottom bands), repeated text patterns across pages, changing numeric sequences, mirrored even/odd page styles, Roman numerals and page-label context.
- Distinguish headers containing chapter titles from a heading appearing once within the content body.
- Remove pagination artifacts at block/span level, not by blindly deleting all numeric-only lines.
- Preserve legitimate standalone numbers, ordered lists, captions, poetry, footnotes and quoted content.
- Remove a single qualifying sequence in the outermost margin band when it is consistent with physical page order. Use edge distance only to break ties between competing sequences; when tied, keep both and warn. Explicit PDF page labels are positive evidence, while disagreement warns once without disabling removal.
- A poem or section-number sequence placed in the only margin band is indistinguishable from folios and can be removed; disable page-number removal with `pdf.remove_page_numbers = false` when needed.
- Maintain reason/confidence for every removal; low-confidence candidates remain in text and are surfaced for review.
- Default removal of running headers, footers and page numbers; all individually toggleable.

### 4.3 Text restoration and special material

- Reflow paragraphs and line breaks using geometry, indentation and punctuation. Do not merge section headings into body text.
- Classify headings before list items. Treat numbered/lettered lines as list items only within a run of at least two sequential markers; preserve initials such as `J. Smith` and years such as `1990)` as prose. Join a wrapped list continuation to its list item. A one-letter Roman numeral title (`C.`, `D.`, `L.`, `M.`, `V.`, `X.`) is a heading only beside a neighbouring numeral heading or by typography, so `C. DICKENS` stays body text. A list ends at a blank line, a font change or an outdented line.
- Join a line-end hyphen only when it follows a letter and the next line begins with a lowercase letter. Remove the hyphen only when the unhyphenated word appears elsewhere in the document; otherwise preserve the compound spelling. Never join a spaced hyphen or an en/em dash.
- Preserve quotations, scene breaks, emphasis cues, lists and paragraph boundaries. Treat footnotes/endnotes via configurable policy: omit, inline at anchor, or end of chapter; default to warn/omit ancillary material only when explicitly classified.
- For tables, figures, formulas, sidebars and diagrams, default to a warning and conservative narration, not invented descriptions. A future vision-capable provider may describe these under explicit opt-in.
- Avoid introducing new prose. Flag anomalous OCR tokens, huge edits, repeated/missing spans or nonmonotonic reading order.

## 5. Chapter discovery

Order of evidence:
1. Valid PDF outline/bookmarks, checking that entries align to true chapter starts.
2. Explicit table of contents with parsed title/page references (account for PDF page labels vs physical indices).
3. Layout clues: heading font/size, whitespace, page transitions, numbered headings, “Chapter”, “Part”, Roman numerals and typographic patterns.
4. Bounded LLM-assisted ranking/classification of candidate headings and boundaries.
5. User-supplied chapter overrides in a human-editable manifest.

Support books without a TOC, front matter, prologue/epilogue and mid-page transitions. Normalize chapter spans as ordered, nonoverlapping half-open intervals. Detect holes, overlapping chapters, duplicate text and empty chapters; produce a coverage report. Never silently treat the entire book as one chapter when detection fails. Require user review or explicit --allow-single-chapter.

Provide a confidence value and evidence list for each proposed boundary. Schema v3 chapters retain the generated title, start/end boundaries and voice as field-level baselines. Reanalysis protects only fields whose current values differ from those baselines, even under `--force` or `--no-resume`; a boundary edit moves the adjacent boundary of its neighboring chapter. Reject impossible overlaps with a content-free error naming the chapter numbers. Recompute warnings and review reason codes after reanalysis. A manual chapter manifest is authoritative after validation; reanalysis must not clobber manual edits.

Before applying any hand edit or moving a neighbor boundary, match old chapters to newly generated chapters by generated start block; if no start matches, use the unique new generated range containing the old generated start. If a hand-edited chapter cannot be matched uniquely, fail with a content-free conflict naming its chapter number. Never match by chapter number. Apply title, voice and both boundary edits as a set, then validate contiguous coverage. Conflicts name the affected chapters and end with the fixed approve-or-revert instruction. Keep the generated field baselines and their fingerprint in sync after boundary merges; a neighbor moved by a hand edit is not itself reported as edited on the next reanalysis.

At analysis time, compute speakable text for each chapter after accepted cleanup. A chapter with no narration receives a per-chapter warning and appears in the coverage report; synthesis must wait for explicit chapter approval.

Review reason codes are structured results from extraction and structure; gate decisions never depend on warning wording. Empty chapters are cleared only by approving that chapter. `--accept-review` accepts only the book-wide reasons `damaged_source` and `ambiguous_page_numbers`; chapter approval never acknowledges a book-wide reason. An approved empty chapter is skipped and named in the conversion report. In schema v3 manifests, a legacy `empty_chapter` acknowledgement is ignored and retained, and conversion emits a content-free warning that empty chapters require chapter approval.

While a book-wide reason is present in `review_required` and absent from `review_acknowledged`, conversion refuses every chapter, even if the chapter was approved in the review UI. The UI provides a separate acknowledgement checkbox for each currently present book-wide reason. A title or boundary save without that checkbox does not acknowledge the reason. `convert --accept-review REASON` is the other explicit acknowledgement path.

## 6. LLM layer

### 6.1 Providers

A stable LLMProvider protocol exposes health/model discovery (when available), text completion with typed response, token usage when returned, model identity, and capability hints. Providers:

| Provider | Default base URL | Credential | Model |
| --- | --- | --- | --- |
| openai | Official OpenAI API | OPENAI_API_KEY environment variable | Configurable |
| ollama | http://127.0.0.1:11434/v1 | None for local endpoint | Configurable Ollama model tag |
| llama-server | http://127.0.0.1:8080/v1 | Optional configured key/env | Server's served model or configured ID |

Use the OpenAI Python SDK or an equivalent HTTP client with OpenAI-compatible chat/completions when supported. Do not assume every Ollama/llama-server build supports every OpenAI parameter, JSON-schema mode, endpoint or model-list response: use provider capability adaptation and local Pydantic/JSON validation, with bounded repairs and explicit error messages. Provider adapters must have contract tests using stubbed responses.

If a provider explicitly rejects `max_tokens` or `temperature`, retry once without that parameter and remember the unsupported capability for that provider instance. Treat the fallback as a new HTTP attempt for budget accounting; keep local response validation enabled. When `max_tokens` is rejected, substitute `max_completion_tokens`; under a token or USD budget a request is never sent without an output cap, and a provider that accepts neither is refused.

### 6.2 LLM tasks

- **Structure detection:** classify headings and TOC candidates; return anchored block IDs and confidence, never free-form chapter text.
- **Contents and boundary proposals:** when independently enabled, classify printed contents entries and body boundary candidates using exact existing block IDs. Verify source titles and page references; accepted boundaries remain weak evidence below PDF outlines, matching printed contents and numbered labels.
- The contents/boundary task is independently controlled by `llm.contents` (TOML or `PDF2AUDIOBOOK_LLM_CONTENTS`); it is disabled by default.
- **OCR/cleanup suggestions:** propose precise edits to anchored source blocks, with original substring, replacement, reason and confidence.
- **Content classification:** distinguish running headers, body prose, footnotes, bibliographies, page labels, captions and ornamental material.
- **Narration policy:** flag terms that need pronunciation/speech normalization while retaining source text unchanged.

Use bounded requests with nearby-context overlap, stable IDs and prompt versioning; avoid sending entire books to small-context models. Reserve configured output capacity before each request, use a conservative UTF-8-byte upper bound for prompt content plus explicit chat-message overhead, and pass max_tokens to the compatible API. This is a fail-closed preliminary bound, not a model-specific tokenizer guarantee; incompatible parameter support and live served-model context windows require real-model checks. Use low temperature when supported. Treat book text as **untrusted data**: embedded instructions may not change prompts, run tools, exfiltrate text or alter policy.

### 6.3 Verification and fallbacks

- Structured model output must satisfy schemas, reference known block/span IDs and pass deterministic integrity checks.
- Reject hallucinated spans, unanchored chapter boundaries, edits with mismatched originals, large deletions and chapter coverage changes.
- Expose rejected edits and ambiguous decisions via inspect/report; keep source unchanged when uncertain.
- Configuration supports selective use of LLM for structure, cleanup, classification and narration tasks.
- --no-llm always works and uses deterministic heuristics; unavailable providers fail informatively or fall back **only when explicitly configured**.
- Cache by source/stage hash, prompt schema/version, provider/model, context and generation parameters; do not mix incompatible cache entries.
- Report approximate token/cost metrics when known; enforce optional per-book request/token/USD budgets. Cost estimates are advisory unless authoritative pricing is configured.
- Persist pending, complete, unknown and unbilled request rows. Only provably unsent connection failures are unbilled; unresolved sent/ambiguous calls block token and cost budgets until reviewed. Model discovery occurs before reservation. `budget show --output DIR` exposes row IDs, statuses and accounting only; `budget resolve` requires explicit confirmation and verified token counts or a confirmed unbilled result. Each attempt records its worst-case token and USD bound at reservation and is charged at that bound until settled; an open row with no recorded bound (legacy ledgers) blocks token and USD budgets until resolved. A 4xx response other than 408 and 429 without usage settles as `rejected`; 408, 429, 5xx and timeouts stay unknown. `budget resolve` refuses any value that would make a stored total unrepresentable.
- Every HTTP attempt, including compatibility fallbacks and retries, gets its own reservation and settlement. Attempts count toward `max_requests`; a retry stops when the next reservation would exceed a configured budget.
- Each heading, cleanup, classification and narration task writes sanitized accepted/rejected `LLMDecision` records to `reports/llm_decisions.json` and the cleanup audit. Records include task, safe block ID, a fixed proposal summary, reason code, confidence and provider; they never include proposed or source prose.
- Analysis fingerprints include content-affecting settings, not operational limits, consent toggles, chapter-gate thresholds or disabled-LLM provider/model settings. An approved workspace with unchanged analysis stages keeps its approved analysis under `--no-resume`; a rejected deterministic cleanup decision is preserved by block identity and cleanup kind when stages change, or fails with a content-free chapter conflict if it cannot be matched. When other approved workspaces cannot be reused, diagnostics name changed stages without exposing setting values.

### 6.4 Data privacy

Selecting openai does not automatically permit uploading book text: require --allow-remote-content or a persistent explicit configuration choice. Before upload, warn once per distinct data scope and name the provider and selected model. Page-image review is capped at 12 rendered pages; text analysis may upload the whole book in bounded windows. Image and text uploads receive separate warnings. Never log plaintext API keys, auth headers or full text by default. Local hosts other than loopback or URLs using insecure HTTP beyond loopback require deliberate opt-in.

## 7. Configuration

Default config path: `~/.config/pdf2audiobook/config.toml` on Unix; platform-appropriate user configuration directory elsewhere. Empty or relative `XDG_CONFIG_HOME` is ignored. Search optional project config only when explicitly supplied via `--config`, to avoid surprising uploads/settings. Resolve all relative output paths from the process working directory, including values from explicit config.

Resolution (highest wins): **explicit CLI option > PDF2AUDIOBOOK_* environment setting > user TOML > built-in defaults**. Environment values are parsed by field type: strings stay strings, booleans accept true/false, 1/0 or yes/no, numeric fields parse numbers, and only list/table values accept JSON. Generic TTS environment values apply to the selected provider; provider-specific values override them. Credentials are *only* taken from environment variables or an OS credential mechanism, never printed by config show. Boolean setting switches use paired positive/negative forms and preserve an unset state. Support `--config FILE`, `--no-config`, and `config show --sources` with secrets redacted.

Logging assigns ERROR to command failures, WARNING to review and degradation warnings, INFO to stage progress, and DEBUG to details. The default level is INFO, `--quiet` selects ERROR, and `--verbose` selects DEBUG; when neither flag is set, `general.log_level` applies. Default human output renders warnings as `Warning:` lines and reports command failures as `Error:`; JSON output carries warning event codes in its `warnings` array. `--quiet` suppresses warning and progress output while retaining the command's error diagnostic. Structured events are shown with `--verbose` or an explicitly configured `general.log_level`.

Example (models/voices are illustrative and must be checked against what is installed):

```toml
[general]
output_dir = "./audiobooks"
resume = true
log_level = "INFO"

[pdf]
ocr = "auto"
ocr_language = "eng"
ocr_dpi = 300
remove_page_numbers = true
remove_headers = true
remove_footers = true
footnotes = "warn"

[chapters]
min_boundary_confidence = 0.75
allow_single_chapter = false

[llm]
enabled = true
provider = "ollama"
temperature = 0.1
max_context_tokens = 16384
max_output_tokens = 1024  # reserved output, also sent as max_tokens
chunk_tokens = 4000
max_retries = 3
structure = true
cleanup = true
classification = true
narration = true
allow_remote_content = false

[llm.openai]
model = "gpt-4.1-mini"
api_key_env = "OPENAI_API_KEY"

[llm.ollama]
base_url = "http://127.0.0.1:11434/v1"
model = "qwen3.5:9b"

[llm.llama_server]
base_url = "http://127.0.0.1:8080/v1"
model = "auto"
api_key_env = "LLAMA_SERVER_API_KEY"

[tts]
provider = "kitten"
output_format = "mp3"
bitrate = "128k"
sample_rate = 24000
pause_ms = 250

[tts.kitten]
model = "mini"
voice = "Jasper"
speed = 1.0

[cache]
enabled = true
```

Example environment names: `PDF2AUDIOBOOK_LLM_PROVIDER`, `PDF2AUDIOBOOK_LLM_MODEL`, `PDF2AUDIOBOOK_LLM_URL`, `PDF2AUDIOBOOK_TTS_PROVIDER`, `PDF2AUDIOBOOK_TTS_MODEL`, `PDF2AUDIOBOOK_TTS_VOICE`, `PDF2AUDIOBOOK_TTS_SPEED`, and `OPENAI_API_KEY`. Reject unknown configuration keys, non-table sections, and unsupported combinations with content-free actionable messages. Only MPEG-compatible sample rates are accepted. `cache.directory` is retained for compatibility, but ignored with a warning when explicitly set.

## 8. CLI contract

Entry point: **pdf2audiobook**, implemented with Typer. Examples:

```bash
pdf2audiobook inspect book.pdf
pdf2audiobook convert book.pdf
pdf2audiobook convert book.pdf --llm-provider openai --llm-model gpt-4.1-mini --allow-remote-content
pdf2audiobook convert book.pdf --llm-provider ollama --llm-model qwen3.5:9b --ocr auto
pdf2audiobook convert book.pdf --llm-provider llama-server --llm-url http://127.0.0.1:8080/v1
pdf2audiobook convert book.pdf --no-llm --tts-provider kitten --voice Jasper
pdf2audiobook convert book.pdf --chapter 5 --resume
pdf2audiobook convert book.pdf --config ./settings.toml --output ./audiobook
pdf2audiobook analyze book.pdf --output ./audiobook
pdf2audiobook inspect ./audiobook/manifest.json
pdf2audiobook doctor
pdf2audiobook config show --sources
```

**analyze** performs extraction, OCR, cleanup and chapter plan generation without TTS; **inspect** prints metadata, chapter boundaries, confidence, warnings and coverage; **convert** reuses analysis and synthesizes; **doctor** checks FFmpeg/Tesseract/TTS/LLM connectivity and lists useful diagnostics. A loopback-only **review** UI lets users inspect and save validated chapter titles/boundaries, marking them manually approved. **batch** processes directories and accepts the same provider/model/voice/speed/sample-rate/bitrate options as `convert`; explicit CLI values override per-book profiles, which override config. **pack-m4b** packages chapter MP3s with navigation metadata. Provide `--dry-run`, `--json`, `--verbose`, `--quiet`, `--force`, `--resume/--no-resume`, `--recursive/--no-recursive`, `--chapter N`, `--chapter-range A:B`, `--ocr auto|always|never`, `--ocr-language`, `--llm/--no-llm`, `--allow-remote-content/--no-allow-remote-content`, `--vision/--no-vision`, `--allow-single-chapter/--no-allow-single-chapter`, `--llm-provider`, `--llm-model`, `--llm-url`, `--tts-provider`, `--tts-model`, `--voice`, `--speed`, `--sample-rate`, `--bitrate`, `--output` and `--cover`. Boolean setting pairs default to unset so config and environment values remain effective unless a flag is supplied. Resolve the chapter-selection convention (human-friendly 1-based indices) consistently.

The review UI validates the `Host` authority on every request against its bound loopback address and port before returning a page, token, or manifest data. A mismatch receives a generic 421 response. API GET requests reject a present mismatched `Origin`, and save requests require the matching origin and bearer token.

The `budget show --output DIR` and `budget resolve --output DIR REQUEST_ID` commands inspect and resolve content-free per-book accounting records; resolving a request requires `--confirm` and exactly one of `--tokens PROMPT:COMPLETION` or `--unbilled`.

`convert --accept-review REASON` takes `damaged_source`, `empty_chapter` or `ambiguous_page_numbers`, validates them before any work (exit 2), logs a content-free `review_acknowledged` event per reason, and is applied by `--dry-run` without rewriting the manifest. Real conversion, dry-run and `pack-m4b` share chapter selection: they recompute empty-chapter reasons and refuse unapproved empty chapters; conversion and packaging skip approved empty chapters, and dry-run and packaging report skipped chapter numbers. Dry-run does not write the manifest. The review UI clears `damaged_source` only through its explicit checkbox. A failed command's stderr is its own `Error:` line, or one JSON object with `--json`; JSON results include a `warnings` array of warning event codes, while human-mode warnings use `Warning:` lines. `--quiet` suppresses warnings and progress. INFO progress and structured `command_failed` events appear only with `--verbose` or an explicitly configured `general.log_level`. `convert`, `analyze` and each `batch` book hold the same exclusive per-workspace lock before analysis and writes. Review saves acquire it without blocking and return HTTP 409 with a fixed body when it is held. `pack-m4b` judges freshness from narration text rendered in memory from the manifest, never from `chapters/*.txt`. Ctrl+C ends `review` with exit 0, and a busy port reports a fixed message.

Exit codes: 0 success, 2 invalid CLI/config, 3 unreadable/unsupported PDF, 4 extraction/OCR/structure failure, 5 LLM failure, 6 TTS/audio failure, 7 partial conversion (manifest contains details). Never claim success when requested chapters are incomplete.

## 9. Audio, output files and resumability

Kitten is the default TTS provider and loads lazily. The provider protocol also supports an optional Piper CLI adapter configured with a local ONNX voice model; Piper is not installed or downloaded by the default environment. Its adapter reads the model's sample rate, invokes Piper without a shell, validates mono PCM output and suppresses backend diagnostics. The review UI can set a voice ID per chapter; only manually approved chapter text may use paragraph-level `[[voice:VOICE_ID]]` markers on their own lines between blank lines. Markers are excluded from speech and preserve source offsets; marker IDs are checked against provider voices when enumerable. A single-token pronunciation dictionary changes spoken chunks without changing source text and supports punctuation-wrapped tokens. Decorative or punctuation-only paragraphs produce pauses without TTS calls. Spoken text uses a versioned deterministic normalization table, while source text and offsets remain unchanged. TTS requests retry with bounded backoff; chapters that still fail are recorded in `reports/conversion_status.json`, other chapters continue, and the command exits 7 with failed chapter numbers. EPUB is accepted as a reflowable book source through the same provenance-aware extraction path; generated page numbering is renderer-dependent. Other engines can implement the TTS protocol; no non-Kitten engine is required for MVP.

Prepare speakable text in sentence-aware bounded chunks that honor TTS model input limits; do not split words or markup commands, and do not lose punctuation. Track exact chunk sequence and text hash. Generate chunks atomically, validate duration and nonempty audio, normalize sample rate/channels, stream validated chunk PCM and configurable inter-chunk pauses to a temporary chapter WAV, and **encode once per chapter** through FFmpeg rather than concatenating compressed MP3 streams. This keeps synthesis memory bounded by chunk size. Add ID3 book, author, chapter title, chapter sequence and optional cover art when available. `--cover PATH` overrides `audio.cover_image`; covers are JPEG or PNG up to 5 MiB and are embedded as ID3 APIC front covers. Cover content participates in chapter audio fingerprints and is embedded in M4B packaging. Deterministic names (zero-padded index, sanitized title) and collision avoidance are required. The optional `pack-m4b` command may package completed chapter MP3s as AAC in an M4B container with book metadata and chapter navigation. Chunk alignment follows source words, so a source word may speak as several tokens (`10–20` as `10 to 20`) or none (a bare dash or an isolated zero-width character). An em dash or non-digit en dash reads as `, `; a pronunciation key ending in `.` owns its period, restored only when the word ends its paragraph; `...` and `…` are stripped for lookup and restored unchanged. TTS retries apply only to errors a provider marks transient (the Piper timeout); a misplaced voice marker fails only its chapter.

Each published chapter MP3 has a bounded sidecar containing its chapter ID, audio fingerprint, byte length and SHA-256. `pack-m4b` verifies every current chapter against its sidecar and refuses stale or missing chapters with their chapter numbers. After publishing a renamed chapter, conversion removes older MP3/sidecar pairs only when a valid sidecar identifies the same chapter; files without a valid owned sidecar are left untouched.

Proposed tree:

```text
audiobooks/
  Example Book/
    manifest.json
    analysis.json
    chapters/
      001-introduction.txt
      002-the-beginning.txt
    audio/
      001 - Introduction.mp3
      002 - The Beginning.mp3
    reports/
      inspection.json
      warnings.json
```

Cache extraction, OCR, LLM decisions, approved chapters, text chunks, and generated audio separately. Store schema versions and stage input fingerprints. TTS model identity includes local model content (Piper model/config digests) or the resolved Kitten model ID plus installed `kittenml` version. The chapter audio fingerprint is `mp3-v6` with sidecar version 2 and chapter-text SHA-256 checks; its upgrade invalidates older chapter MP3 cache entries. A changed voice reuses PDF/OCR/LLM results but invalidates TTS/audio; changed OCR parameters invalidate downstream analysis; an edited chapter boundary invalidates affected chapters only. Write manifest/audio via temporary files plus atomic rename; resume must ignore partial/corrupt artifacts and never destroy completed valid chapters. `--force` requests explicit recomputation; `--no-resume` skips derived caches while keeping approved analysis when its stage fingerprints are unchanged.

## 10. Testing and quality gates

### Unit tests
- Config precedence, path resolution, invalid combinations, secret redaction and --no-llm.
- Footer/page-number detection across Arabic/Roman, alternating left/right and numbered legitimate content.
- Paragraph/hyphen recovery, structured provenance and edit audit records.
- Chapter boundary half-open offsets, mid-page split, coverage/no duplication, empty chapters and manual overrides.
- LLM output validation on invalid JSON, unknown IDs, fabricated replacements, overlong edits, timeout/rate limit and missing provider.
- Chunking stable sentence boundaries, idempotent resume, cache invalidation and output sanitization.

### Integration fixtures
Construct tiny non-copyright synthetic PDFs for: selectable text, scanned pages, mixed text+scan, two-column reading order, TOC with page offset, bookmarks, front matter with Roman numerals, chapters starting mid-page, running headers, legitimate numbered lists, damaged OCR, no chapters, and embedded images/tables. Stub LLM responses and TTS samples so CI does not require a paid API, GPU, preinstalled voice model or real credentials. Add opt-in local smoke tests for Tesseract, FFmpeg, Kitten, Ollama and llama-server, plus a consented OpenAI smoke test.

### Release acceptance
1. From a selectable-text book with known chapter boundaries, generate one valid MP3 per chapter with chapter titles/order correct.
2. From a scanned or mixed fixture, OCR only the necessary regions in auto mode and provide source confidence.
3. Page numbers/running headers are removed while legitimate body text remains intact.
4. Every source prose span maps to exactly one chapter or has a recorded, approved exclusion; no text is silently duplicated or omitted.
5. OpenAI, Ollama and llama-server pass mocked contract tests; local integration where available; no outbound book text without consent.
6. TOML defaults and CLI/environment overrides work, including explicit false.
7. A killed conversion resumes without regenerating validated previous chunks.
8. An edited chapter manifest controls the final output and is not overwritten.
9. --no-llm works on standard well-structured fixture.
10. All generated MP3s decode successfully, carry expected ID3 tags and correspond to their approved chapter text.

## 11. Milestones and exclusions

- **M0** Foundation: CLI, config, typed models, diagnostics and test harness.
- **M1** Text pipeline: PDF extraction, OCR, cleanup and provenance.
- **M2** Chapters: heuristics, overrideable manifest and coverage validation.
- **M3** LLM: three providers, schemas, verification, safety, caching and privacy gates.
- **M4** Audio: Kitten, chunk engine, MP3/ID3 and resume.
- **M5** Hardening: real fixtures, usability, docs, packaging and end-to-end acceptance.

Out of initial scope: DRM circumvention, translating a book, generating alternate abridgments, speech cloning, exact reproduction of complex mathematics/graphs without a pronunciation policy, commercial audiobook publishing workflow, and full GUI.

## 12. Engineering principles

**No invented text; auditable edits; one MP3 per chapter; manual review when uncertain; local-first privacy; content-addressed resume; provider-swappable internals; no network-dependent CI.** This specification is authoritative for the linked dependency-ordered TODO.
