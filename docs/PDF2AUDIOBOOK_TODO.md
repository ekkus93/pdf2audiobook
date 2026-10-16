# PDF2Audiobook — Implementation TODO

**Status:** In progress (M0–M4 initial implementation; hardening and manual acceptance pending)  
**Date:** 2026-10-16  
**Specification:** docs/PDF2AUDIOBOOK_SPEC.md  
**Target:** Python CLI, chapter MP3s, Kitten TTS, optional OpenAI/Ollama/llama-server intelligence.

## Working rules

- Work dependency-first, including every subtask. Use [x] only with implementation and the corresponding verified test/evidence; otherwise leave [ ].
- Prefer direct commits to master under the project's established workflow. Never invent tests, CI status or hardware acceptance.
- The spec defines contracts and precedence if an implementation detail is unclear. Record meaningful design deviations here and in the spec.
- Keep raw transcript and source mapping intact; never silently delete prose, invent book content or bypass remote-content consent.
- Do not let a missing external model/API prevent deterministic fixture tests. Mark actual integration gaps as explicit manual checks.

## Phase 0 — Repository and tooling (M0)

- [ ] P0.01 Set Python >=3.11 project packaging (pyproject.toml, src layout), CLI entry point pdf2audiobook, reproducible dependency groups, README quick start.
  - [x] P0.01a Add Typer, Pydantic, PyMuPDF, HTTP/OpenAI-compatible client, Rich, Mutagen, FFmpeg interaction, Kitten TTS integration and OCR dependency declarations (separate optional heavyweight/model dependencies).
  - [ ] P0.01b Add formatting, lint, type checking and pytest configuration; ensure clean install from repository checkout.
  - [x] P0.01c Add GitHub Actions lint/unit CI with no remote keys/model downloads.
- [ ] P0.02 Establish src/pdf2audiobook/{cli,config,pdf,document,llm,tts,audio,pipeline} and public adapter protocols.
  - [ ] P0.02a Define model and provider error types, exit codes and consistent JSON diagnostics.
  - [ ] P0.02b Add structured logging with text/key redaction and --verbose/--quiet controls.
- [x] P0.03 Implement typed TOML configuration models with built-in defaults, validation and provenance.
  - [x] P0.03a Implement lookup of per-user config directory; --config and --no-config.
  - [x] P0.03b Implement precedence CLI > PDF2AUDIOBOOK_* env > TOML > built-ins, including explicit boolean false.
  - [x] P0.03c Support named OpenAI/Ollama/llama-server and TTS sections, model URLs, OCR and chapter/output options.
  - [x] P0.03d Implement config show --sources with secret masking; no secrets in TOML examples.
  - [x] P0.03e Unit-test overlay precedence, parsing, missing/unknown keys and path resolution.
- [x] P0.04 Implement CLI skeleton for inspect, analyze, convert, doctor and config show, with --help examples and validation.
- [ ] P0.05 Implement atomic output workspace/manifest schema, input hash, stable IDs and versioned per-stage caching.
  - [x] P0.05a Define SourceSpan, DocumentBlock, CleanupEdit, Chapter, NarrationChunk and BookManifest models.
  - [x] P0.05b Unit-test manifest schema migration/rejection, atomic file writes and stage fingerprints.

**M0 gate:** installable CLI; --help/doctor/config work without a model; offline CI green.

## Phase 1 — PDF extraction and OCR (M1)

- [ ] P1.01 Inspect PDF, metadata, pages, page labels, outlines, TOC and embedded text using PyMuPDF.
  - [x] P1.01a Preserve page geometry, font/style and stable span/block provenance.
  - [ ] P1.01b Handle rotation, empty pages, malformed files and password-protected files gracefully.
- [ ] P1.02 Implement usable-text scoring per page/region; choose embedded extraction vs OCR in auto mode.
  - [x] P1.02a Support --ocr auto|always|never, OCR language and DPI settings.
  - [ ] P1.02b Integrate Tesseract and verify system language packages/model availability.
  - [ ] P1.02c Avoid duplicate text from embedded and OCR layers; cache OCR by source page and settings.
  - [ ] P1.02d Detect low-confidence OCR/reading-order cases and emit review warnings.
- [ ] P1.03 Reconstruct reading order and paragraphs, handling one- and two-column layout.
  - [ ] P1.03a Recover paragraph soft wraps and safe end-of-line hyphenation.
  - [ ] P1.03b Preserve dialogue, section breaks, legitimate line breaks and special content markers.
- [ ] P1.04 Detect repeated headers, footers, Arabic/Roman page numbers and alternate-page layouts.
  - [x] P1.04a Remove only confidently identified pagination noise, with source-linked CleanupEdit records.
  - [x] P1.04b Add toggles to retain/remove headers/footers/page numbers independently.
  - [ ] P1.04c Never remove numbered lists, quoted standalone numbers or substantive body text.
- [ ] P1.05 Implement footnote/table/image/math handling policies, conservative warnings and audit.
- [ ] P1.06 Add synthetic PDF fixtures for text, scans, mixed pages, two-column, Roman numbering, repeated headers, numbered lists and difficult OCR.
  - [ ] P1.06a Unit and integration tests verify correct extraction/coverage without network dependency.

**M1 gate:** text/OCR pipeline yields traceable clean transcript from text, scanned and mixed fixtures, with no duplication.

## Phase 2 — Chapter detection and inspection (M2)

- [ ] P2.01 Detect candidates from bookmarks, TOC/page offsets, typography, heading patterns and whitespace.
  - [ ] P2.01a Handle prologues, epilogues, front matter, multiple parts and mid-page starts.
  - [ ] P2.01b Rank evidence and attach confidence/warnings to each boundary.
- [x] P2.02 Build nonoverlapping stable chapter spans and enforce full prose coverage exactly once.
  - [x] P2.02a Reject overlapping/missing/empty chapter spans and source holes; emit a coverage report.
  - [x] P2.02b Require review for low-confidence/no-chapter books; allow explicit --allow-single-chapter.
- [ ] P2.03 Persist editable chapter manifest plus per-chapter UTF-8 text files and inspection report.
  - [x] P2.03a Implement manifest override validation and preserve user edits across reruns.
  - [ ] P2.03b Support inspect, analyze, --dry-run, --json, --chapter and --chapter-range.
- [ ] P2.04 Test bookmark, no-TOC, TOC-offset, prose heading and chapter-mid-page fixtures.

**M2 gate:** correct, auditable chapter boundaries; authoritatively editable pre-TTS analysis.

## Phase 3 — LLM providers and safeguards (M3)

- [ ] P3.01 Define LLMProvider interface, model discovery, typed structured-response API, health checks, request timeout, retry and usage telemetry.
  - [x] P3.01a Implement OpenAI API adapter; load key only from OPENAI_API_KEY or designated env.
  - [x] P3.01b Implement Ollama adapter with configurable local base URL/model.
  - [x] P3.01c Implement llama-server adapter with configurable local base URL/model and optional auth.
  - [ ] P3.01d Probe or adapt capabilities for JSON/schema response and provider-specific unsupported parameters.
- [ ] P3.02 Implement bounded prompt/context splitting with stable block references and schema versioning.
  - [x] P3.02a Structure classification: proposed headings, TOC and anchored boundaries.
  - [ ] P3.02b Cleanup proposals: anchored exact-match OCR corrections and pagination classification.
  - [ ] P3.02c Narration-preparation suggestions: pronunciation/speech normalization with source text unchanged.
- [ ] P3.03 Implement deterministic verifier: reject unknown IDs, unmatched originals, unanchored boundaries, invented text and excessive deletion.
  - [ ] P3.03a Track accepted/rejected edits, evidence, confidence, review flags and provenance.
  - [ ] P3.03b Support independently toggleable structure, cleanup, classification and narration LLM tasks.
- [ ] P3.04 Implement local-only behavior (--no-llm); fail-safe provider errors and explicitly configured fallback.
- [ ] P3.05 Enforce remote-data opt-in (--allow-remote-content/config) and warning before sending book content.
  - [x] P3.05a Validate TLS/loopback rules; block accidental external HTTP upload.
  - [ ] P3.05b Treat PDF text as untrusted and never let embedded instructions control model/tool behavior.
  - [x] P3.05c Ensure logs, crash reports and config show redact credentials and full text.
- [ ] P3.06 Add content-addressed LLM cache, provider/model/prompt fingerprints and cost/token budget reporting.
- [ ] P3.07 Create stubbed contract tests for all three providers (success, invalid JSON, truncation, API errors, timeouts, schema incompatibility).
- [ ] P3.08 Add opt-in real backend smoke checks for local Ollama/llama-server and explicitly consented OpenAI.

**M3 gate:** all three provider adapters pass offline contract tests and model-assisted analysis cannot silently alter or invent source prose.

## Phase 4 — TTS, MP3 and resume (M4)

- [ ] P4.01 Define TTSProvider protocol (models, voices, synthesis, sample rate, chunk bounds and health) with lazy loading.
  - [ ] P4.01a Implement Kitten TTS adapter, selectable model and voice; test valid voice/model resolution.
  - [ ] P4.01b Expose --tts-provider, --tts-model, --voice, --speed, --sample-rate, --bitrate.
- [ ] P4.02 Build narration normalization with preservation policy and stable sentence-aware chunking.
  - [ ] P4.02a Keep punctuation/paragraph pauses and preserve source-to-audio chunk mapping.
  - [x] P4.02b Handle oversized sentences and TTS failures without silently dropping text.
- [x] P4.03 Generate validated PCM/WAV chunks; normalize channels/rate, join at PCM level and encode once per chapter via FFmpeg.
  - [x] P4.03a Produce playable, deterministic, zero-padded chapter MP3 filenames.
  - [x] P4.03b Apply configurable inter-chunk pauses, suitable default bitrate and correct chapter order.
  - [x] P4.03c Add ID3 book/author/chapter title/track tags, optional cover artwork.
- [ ] P4.04 Track per-chunk progress, checksums, cache keys and completion; persist atomically.
  - [ ] P4.04a Implement --resume/--no-resume and --force with precise cache invalidation.
  - [ ] P4.04b Restart interrupted conversion without regenerating validated completed audio chunks.
  - [x] P4.04c Detect corrupt/incomplete intermediate audio and regenerate only affected artifacts.
- [x] P4.05 Add mocked TTS tests using synthetic sine/audio fixtures; optional actual Kitten model integration test.
- [ ] P4.06 Decode all generated MP3 fixtures with FFmpeg and inspect expected tags/durations.

**M4 gate:** one playable, tagged MP3 per approved chapter; resumes cleanly after interruption.

## Phase 5 — End-to-end acceptance and release (M5)

- [ ] P5.01 End-to-end text PDF -> inspect/analyze -> chapter MP3 acceptance.
- [ ] P5.02 End-to-end scanned and mixed PDF, with OCR auto selection and page-number removal.
- [ ] P5.03 Validate no-text-loss/duplication invariants and mid-page chapter boundaries.
- [ ] P5.04 Verify manual chapter manifest overrides and chapter-specific regeneration.
- [ ] P5.05 Test each LLM backend with mocks; perform environment-dependent real-model acceptance when available.
- [ ] P5.06 Verify default config + CLI overrides, explicit false, no-LLM and remote-consent denial/approval.
- [ ] P5.07 Stress-test long books, retries, partial failures, invalid PDFs and clean restart.
- [ ] P5.08 Document install, Tesseract language packs, FFmpeg, Kitten model setup, OpenAI/Ollama/llama-server setup, config samples, privacy and troubleshooting.
- [ ] P5.09 Add complete CLI usage examples, development workflow and maintainer architecture notes.
- [ ] P5.10 Run lint, types, unit/integration and exact-head CI; record SHA/test evidence and unresolved external acceptance gaps.

**M5 gate:** all ten release acceptance criteria in the spec pass, with evidence; no unchecked implementation-critical subtasks.

## Future backlog (not required for MVP)

- [ ] F.01 Additional pluggable TTS engines (Piper, Kokoro, others).
- [ ] F.02 Optional vision LLM for figures, diagrams, equations and complicated page order.
- [ ] F.03 Directory/batch conversion and per-book voice profiles.
- [ ] F.04 EPUB ingestion and additional audiobook containers/metadata formats.
- [ ] F.05 Optional GUI and user-assisted chapter editor.
- [ ] F.06 Multi-speaker narration and pronunciation dictionaries.

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
| 2026-10-16 | 84cd664 | Specification and TODO drafted; no implementation yet | Not run | None identified |
| 2026-10-16 | 21954bae6b6fb012ccf86338858f6fb1dd3f454e | uv Python CLI, config, models, PDF/OCR, conservative pagination, chapter boundaries/overrides, LLM provider adapters, Kitten/MP3 chunk pipeline | Python CI run 38889941369 passed; mocked LLM/TTS, real FFmpeg, mixed scanned/text OCR | Real Kitten model and real LLM provider acceptance not yet run; lockfile unavailable from current local PyPI-restricted environment |

| 2026-10-16 | fcbb51d3bea71cc96641b649a13bc53188d8509a | Added provenance-validated cleanup edits, coverage.json, checksum-verified WAV/MP3 resume, and streaming input hashes; restored concise CI after uv lock generation check | Python CI runs 38891383049, 38891702908 and 38891853410 passed | uv.lock still uncommitted; real Kitten and LLM acceptance pending |\n\n| 2026-10-16 | 7519c7f9f0a0a989443ce8398df948cb12f6fc64 | Added schema-version rejection, atomic persistence and stage-fingerprint tests | Python CI run 38892375209 passed | Schema migration is intentionally rejected until a migration path is specified |\n\n**Definition of done:** A checked item has implementation + applicable automated tests and/or recorded manual evidence on current master. A milestone is not complete merely because files exist. Keep this checklist synchronized with actual delivered behavior.
