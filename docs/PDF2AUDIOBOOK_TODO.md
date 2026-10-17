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
  - [x] P0.02a Define model and provider error types, exit codes and consistent JSON diagnostics.
  - [x] P0.02b Add structured logging with text/key redaction and --verbose/--quiet controls.
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
  - [x] P1.01b Handle rotation, empty pages, malformed files and password-protected files gracefully.
- [ ] P1.02 Implement usable-text scoring per page/region; choose embedded extraction vs OCR in auto mode.
  - [x] P1.02a Support --ocr auto|always|never, OCR language and DPI settings.
  - [x] P1.02b Integrate Tesseract and verify system language packages/model availability.
  - [x] P1.02c Avoid duplicate text from embedded and OCR layers; cache OCR by source page and settings.
  - [x] P1.02d Detect suspicious OCR/extraction text and possible side-by-side reading-order cases; emit explicit review warnings (heuristics, not engine confidence).
- [x] P1.03 Reconstruct reading order and paragraphs, handling one- and two-column layout.
  - [x] P1.03a Recover paragraph soft wraps and safe end-of-line hyphenation.
  - [x] P1.03b Preserve dialogue, section breaks, legitimate line breaks and special content markers.
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
  - [x] P2.01a Handle prologues, epilogues, front matter, multiple parts and mid-page starts.
  - [x] P2.01b Rank evidence and attach confidence/warnings to each boundary.
- [x] P2.02 Build nonoverlapping stable chapter spans and enforce full prose coverage exactly once.
  - [x] P2.02a Reject overlapping/missing/empty chapter spans and source holes; emit a coverage report.
  - [x] P2.02b Require review for low-confidence/no-chapter books; allow explicit --allow-single-chapter.
- [ ] P2.03 Persist editable chapter manifest plus per-chapter UTF-8 text files and inspection report.
  - [x] P2.03a Implement manifest override validation and preserve user edits across reruns.
  - [x] P2.03b Support inspect, analyze, --dry-run, --json, --chapter and --chapter-range.
- [ ] P2.04 Test bookmark, no-TOC, TOC-offset, prose heading and chapter-mid-page fixtures.

**M2 gate:** correct, auditable chapter boundaries; authoritatively editable pre-TTS analysis.

## Phase 3 — LLM providers and safeguards (M3)

- [ ] P3.01 Define LLMProvider interface, model discovery, typed structured-response API, health checks, request timeout, retry and usage telemetry.
  - [x] P3.01a Implement OpenAI API adapter; load key only from OPENAI_API_KEY or designated env.
  - [x] P3.01b Implement Ollama adapter with configurable local base URL/model.
  - [x] P3.01c Implement llama-server adapter with configurable local base URL/model and optional auth.
  - [x] P3.01d Probe or adapt capabilities for JSON/schema response and provider-specific unsupported parameters.
- [ ] P3.02 Implement bounded prompt/context splitting with stable block references and schema versioning.
  - [x] P3.02a Structure classification: proposed headings, TOC and anchored boundaries.
  - [x] P3.02b Cleanup proposals: anchored exact-match OCR corrections and pagination classification.
  - [ ] P3.02c Narration-preparation suggestions: pronunciation/speech normalization with source text unchanged.
- [ ] P3.03 Implement deterministic verifier: reject unknown IDs, unmatched originals, unanchored boundaries, invented text and excessive deletion.
  - [ ] P3.03a Track accepted/rejected edits, evidence, confidence, review flags and provenance.
  - [ ] P3.03b Support independently toggleable structure, cleanup, classification and narration LLM tasks.
- [ ] P3.04 Implement local-only behavior (--no-llm); fail-safe provider errors and explicitly configured fallback.
- [ ] P3.05 Enforce remote-data opt-in (--allow-remote-content/config) and warning before sending book content.
  - [x] P3.05a Validate TLS/loopback rules; block accidental external HTTP upload.
  - [x] P3.05b Treat PDF text as untrusted and never let embedded instructions control model/tool behavior.
  - [x] P3.05c Ensure logs, crash reports and config show redact credentials and full text.
- [ ] P3.06 Add content-addressed LLM cache, provider/model/prompt fingerprints and cost/token budget reporting.
- [x] P3.07 Create stubbed contract tests for all three providers (success, invalid JSON, truncation, API errors, timeouts, schema incompatibility).
- [ ] P3.08 Add opt-in real backend smoke checks for local Ollama/llama-server and explicitly consented OpenAI.

**M3 gate:** all three provider adapters pass offline contract tests and model-assisted analysis cannot silently alter or invent source prose.

## Phase 4 — TTS, MP3 and resume (M4)

- [ ] P4.01 Define TTSProvider protocol (models, voices, synthesis, sample rate, chunk bounds and health) with lazy loading.
  - [x] P4.01a Implement Kitten TTS adapter, selectable model and voice; test valid voice/model resolution.
  - [x] P4.01b Expose --tts-provider, --tts-model, --voice, --speed, --sample-rate, --bitrate.
- [ ] P4.02 Build narration normalization with preservation policy and stable sentence-aware chunking.
  - [x] P4.02a Keep punctuation/paragraph pauses and preserve source-to-audio chunk mapping.
  - [x] P4.02b Handle oversized sentences and TTS failures without silently dropping text.
- [x] P4.03 Generate validated PCM/WAV chunks; normalize channels/rate, join at PCM level and encode once per chapter via FFmpeg.
  - [x] P4.03a Produce playable, deterministic, zero-padded chapter MP3 filenames.
  - [x] P4.03b Apply configurable inter-chunk pauses, suitable default bitrate and correct chapter order.
  - [x] P4.03c Add ID3 book/author/chapter title/track tags, optional cover artwork.
- [x] P4.04 Track per-chunk progress, checksums, cache keys and completion; persist atomically.
  - [x] P4.04a Implement --resume/--no-resume and --force with precise cache invalidation.
  - [x] P4.04b Restart interrupted conversion without regenerating validated completed audio chunks.
  - [x] P4.04c Detect corrupt/incomplete intermediate audio and regenerate only affected artifacts.
- [x] P4.05 Add mocked TTS tests using synthetic sine/audio fixtures; optional actual Kitten model integration test.
- [x] P4.06 Decode all generated MP3 fixtures with FFmpeg and inspect expected tags/durations.

**M4 gate:** one playable, tagged MP3 per approved chapter; resumes cleanly after interruption.

## Phase 5 — End-to-end acceptance and release (M5)

- [x] P5.01 End-to-end text PDF -> inspect/analyze -> chapter MP3 acceptance.
- [ ] P5.02 End-to-end scanned and mixed PDF, with OCR auto selection and page-number removal.
- [ ] P5.03 Validate no-text-loss/duplication invariants and mid-page chapter boundaries.
- [x] P5.04 Verify manual chapter manifest overrides and chapter-specific regeneration.
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

| 2026-10-16 | fcbb51d3bea71cc96641b649a13bc53188d8509a | Added provenance-validated cleanup edits, coverage.json, checksum-verified WAV/MP3 resume, and streaming input hashes; restored concise CI after uv lock generation check | Python CI runs 38891383049, 38891702908 and 38891853410 passed | uv.lock still uncommitted; real Kitten and LLM acceptance pending |
| 2026-10-16 | 7519c7f9f0a0a989443ce8398df948cb12f6fc64 | Added schema-version rejection, atomic persistence and stage-fingerprint tests | Python CI run 38892375209 passed | Schema migration is intentionally rejected until a migration path is specified |
| 2026-10-16 | 0dc41445cfd8066bb5f1d014dd08c26cc37794c5 | Added validated chapter ranges, dry-run, speed/sample rate CLI settings, LLM JSON-mode adaptation and retry controls, unapproved provenance-bound OCR cleanup proposals, and conservative PDF line-wrap reflow | Python CI runs 38895209653, 38895441231, 38895732178, 38896085092 passed | Full real Kitten and live LLM acceptance still pending; no uv.lock; two-column/footnote robustness incomplete |

| 2026-10-16 | 92de84cb17dd72589d42ea4a749404cf49da90d7 | Combined verified PDF bookmarks with heading-pattern matches; persisted page labels, checked Tesseract language packs, and added secure encrypted-PDF password-env support | Python CI runs 38896503272, 38896830639, 38897284075 passed | More complex reading order, OCR caching, real Kitten/LLM acceptance and uv.lock still outstanding |

| 2026-10-16 | 728538af578438a846a076d38dcade033aa2e5ad | Prevented automatic replacement of manually approved chapter/cleanup edits on changed-settings or no-resume reanalysis; automatically restored missing derived transcript files on unchanged analysis | Python CI run 38897766822 passed | Full approval-aware force/rebuild workflow remains for follow-up; live model acceptance and uv.lock still pending |

| 2026-10-16 | 7374cf87f6290ccd5e2f7d467311d71a6e038389 | Added source/page/settings-keyed OCR cache, validation and corruption recovery; embedded-text pages bypass OCR in auto mode | Python CI run 38929486545 passed; deterministic OCR-cache regression tests | Real-model acceptance, two-column order, uv.lock still pending |

| 2026-10-16 | a432fb828bc763a1461a863a1e1e3475b2ed9746 | P1.01b: normalized rotated-page text geometry for pagination, exposed inspection geometry, and added malformed/encrypted/blank-page regression coverage with actionable domain errors | Python CI run 38936953817 passed (exact head) | Broader multi-column reconstruction and real OCR/model acceptance remain open |\n\n| 2026-10-16 | d755dc29106004a54c905af0305d0ae1f99a8ae2 | Added conservative margin safeguards for numbered list markers, quotations and headings | Python CI 38937306757 passed | Broader substantive-text protection remains open |\n| 2026-10-16 | fda05113c86396da6f2df0a467e606339c751891 | Auto OCR now detects damaged selectable-text mappings and falls back to OCR while --ocr never preserves raw text | Python CI 38937654566 passed | Region-level quality scoring and real OCR acceptance remain open |\n\n| 2026-10-16 | 8e3829c63c3024ad9df39d48ae7b235ffb5f072e | P1.03b: prevent soft-wrap reflow across dialogue starts, section/scene markers, list entries and typed special blocks; preserve original source text | Python CI run 38937925590 passed; reflow boundary regression tests | Full paragraph reconstruction and two-column reading order remain open |\n\n| 2026-10-16 | 889370f58d3e4628664503ab3f2e804830f1383d | P2.01a: tested front matter, prologue, epilogue, multiple parts and exact mid-page boundaries with contiguous chapter coverage | Python CI 38938245614 passed | TOC offsets and ambiguous heading detection remain for P2.04 |
| 2026-10-16 | d2950eeda8c2e7151484666241071b2b8d0aa24f | Added fail-closed pagination guards for repeated substantive margin prose and bracketed reference markers | Python CI 38938496225 passed | P1.04c remains open pending broader substantive-text false-positive acceptance |
| 2026-10-16 | 2e34201c86a28c3bb82b0a5b0e3b8b04d13d8ed5 | Do not cache empty OCR as a successful result; retry and cache subsequent valid recognition | Python CI 38938669729 passed | Real OCR quality and Tesseract version qualification remain open |

| 2026-10-16 | 3723056b87d6ed38b7e9c2458e745396af0f434d | P3.05b: JSON-escape untrusted PDF block records before LLM prompts; maintain separate system/user roles, no model tools, deterministic anchor verification and human review of edits. Also added pagination false-positive guards and special-material warnings | Python CI 38979811740, 38979921642, 38980054474, 38980313990 passed at respective exact heads | LLM can still misclassify legitimate headings; full P3.05 and P1.04c/P1.05 acceptance remain open |\n\n| 2026-10-17 | 03ea2274255a4fa1d76600a97d17a71902d7d353 | P0.02b: wired allowlisted structured JSON events to global --verbose/--quiet CLI controls, with safe error-code events and stderr-only logging; added CLI JSON-isolation and redaction regression tests | Python CI run 39012191856 passed on exact head | CLI structured logging is complete; remaining P0.02 parent adapter work and other unchecked tasks still pending |\n\n**Definition of done:** A checked item has implementation + applicable automated tests and/or recorded manual evidence on current master. A milestone is not complete merely because files exist. Keep this checklist synchronized with actual delivered behavior.

| 2026-10-16 | e4d1c3cecf05de75cf48407a9d763baad142dc14 | Added non-destructive extraction review warnings for suspicious OCR output and possible side-by-side reading order; offline tests cover normal and ambiguous cases | Python CI 38898782355 passed | Heuristics cannot substitute for engine OCR confidence or full two-column reconstruction |
| 2026-10-16 | 9af6839fbaab155d866255afa80f2316d8836ea6 | P1.03: integrated conservative two-column ordering into embedded/OCR extraction, preserving span/block provenance; single-column and ambiguous layouts retain original order with review warnings. Bumped analysis fingerprint to v4 so stale manifests are not silently reused | Python CI runs 38959880545 and 38960031431 passed at exact respective heads; synthetic two-column extraction, OCR, single-column and existing reflow regression tests | Dense tables, sidebars and ambiguous multi-column pages remain review-required; approved manifests cannot be automatically rewritten |
| 2026-10-16 | edb7907a51117bca38eed309a0d4ba69c820e630 | P1.05 partial: high-confidence small-type footnotes classified as typed source blocks; warn/inline preserve text; explicit omit creates source-anchored accepted CleanupEdits, with false-positive guards for numbered body lines | Python CI 38989706523 passed at exact head; synthetic extraction and policy regression tests | Footnote continuation/anchor relocation, figure captions, formula narration and full special-material acceptance remain open |

| 2026-10-16 | ae18259a3b3b7b1637ac57d17802d8a69b287447 | P4.04b: verified interrupted synthesis checkpoints and fresh-provider resume without regenerating valid WAV chunks; verified --no-resume regenerates all chunks. P4.06: qualified FFmpeg-decoded MP3 fixtures with sample-rate/duration/ID3 assertions (prior commit b381c2d) | Python CI 38993383868 passed exact head; Python CI 38990016197 passed exact head | Full P4.04 chunk progress manifest and P4.04a precise invalidation remain open; actual Kitten model acceptance pending |

| 2026-10-16 | 5eae9f12b643bf51ca585eafecca185a355d4cce | P4.01a: qualified existing lazy Kitten adapter, model aliases/custom model IDs, voice validation, model-load failures and invalid audio with a mocked Kitten package (no model download) | Python CI 38993506977 passed at exact head | Real Kitten model acceptance and full P4.01 provider discovery/health protocol remain open |

| 2026-10-16 | 76994bba8789e692051ea136b1e5da2aa9c0cb51 | P0.02a: typed domain error codes now produce consistent machine-readable JSON stderr diagnostics for --json commands; human-readable CLI errors retained | Python CI 38997597162 passed exact head; JSON CLI and domain exit-code regression tests | Structured logging/redaction and verbose/quiet controls remain open under P0.02b |

| 2026-10-16 | ab17301c88325930951be75dab165155081c1d9f | P4.04a: verified --resume/--no-resume/--force chapter cache policy, voice/model/speed PCM invalidation, and MP3 fingerprint invalidation for audio settings plus book/chapter ID3 metadata; metadata-aware MP3 fingerprint bumped to v3 | Python CI 38997774864, 38997861361 and 38997928419 passed at exact respective heads | Full P4.04 per-chunk progress manifest remains open; real Kitten model acceptance pending |

| 2026-10-17 | af48ec15e026e5ba8d395babc4870cf99132cf74 | P4.04: per-chapter atomic, text-free TTS chunk progress ledger (cache keys, WAV bytes, SHA-256, pending/completed/failed states); pipeline wiring and restart/corruption/cache-invalidation tests | Python CI 39013122952 passed at exact head (lint, tests) | A full real-model Kitten acceptance remains pending; ledger does not bypass WAV checksum verification |

| 2026-10-17 | 89ef9fa63df24453ef309f2bb74f75138c19e8bc | P4.02a: preserve paragraph chunk boundaries, distinct pauses and exact source-character offsets per chunk in atomic progress ledger; no chapter text stored there | Python CI 39013343810 passed on exact commit, including source-alignment and pause-sample regressions | P4.02 parent narration-normalization policy remains open |

| 2026-10-17 | 05d763d608f1af64e2e035bff6f05d8525c23581 | P5.01: synthetic two-chapter selectable-text PDF through analysis, chapter boundaries and FFmpeg/ID3 MP3 synthesis; verified repeat-cache skip and corrupt-output repair without fresh speech generation | Python CI 39013862697 passed at exact head | Real Kitten model and scanned/mixed E2E acceptance remain outstanding under P5.02/P5.05 |

| 2026-10-17 | 34dfec4790c19f24250f612e2f6cab491a22b693 | P5.04: verified approved mid-page chapter boundary survives reanalysis, selected chapter metadata override regenerates the chosen MP3, and unaffected previous MP3 plus checked WAV chunks are reused | Python CI 39014044365 passed exact head with synthetic PDF and mocked Kitten voice | Real Kitten and scanned/mixed PDF tests still required elsewhere |
