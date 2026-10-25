# PDF2Audiobook — Review Fixes TODO

**Status:** FX0–FX7 complete
**Date:** 2026-10-25
**Baseline:** master at 689eb4937b94e14735298b8e8c3a7cbc71c279de
**Specification:** docs/PDF2AUDIOBOOK_REVIEW_FIXES_SPEC.md (requirement IDs R1–R45)
**Parent TODO:** docs/PDF2AUDIOBOOK_TODO.md

## Working rules

- Work dependency-first, phase by phase, including every subtask. Use [x] only when the implementation exists and the regression test(s) it names pass; otherwise leave [ ].
- Every bug fix starts with a regression test that fails at the baseline. Every new error path gets a `tests/test_*_privacy.py` test that proves the output contains no book text, paths, credentials or raw exception text.
- Make each fingerprint and schema bump in spec §3 once, in the phase that introduces it, and record it as an upgrade note in docs/MAINTAINER_GUIDE.md. Never migrate old manifests; reject them.
- Merge each spec §6 amendment into docs/PDF2AUDIOBOOK_SPEC.md in the same commit as the fix it describes.
- Add every new `src/` module to `[tool.mypy].files`. Run `/verify` before each commit. CI must stay offline.
- Commit directly to master using Conventional Commits with a scope (`fix(review-ui): …`, `fix(pdf): …`). After CI finishes for a pushed fix, record the evidence in a separate `docs: record … CI evidence` commit, adding a row to the progress ledger below. Never invent CI results.
- Once a fix is verified, re-check the original item in docs/PDF2AUDIOBOOK_TODO.md that spec §5 maps it to.

## Phase FX0 — Foundations and honest status

- [x] FX0.01 Record the review's findings in docs/PDF2AUDIOBOOK_TODO.md (R45).
  - [x] FX0.01a Reopen items found wrong or partial in spec §5; add a ledger row citing review spec and baseline SHA.
  - [x] FX0.01b Remove stale P0.01d text, annotate P5.05's deferred live checks, and correct the prior mypy module count.
- [x] FX0.02 Add a shared bounded JSON loader (R23).
  - [x] FX0.02a Add `src/pdf2audiobook/jsonio.py` with bounded byte reads, non-recursive nesting checks, nonfinite-number rejection and malformed-cache misses; add it to mypy.
  - [x] FX0.02b Use it in LLM, OCR and MP3 caches and add bounded JSON metadata for WAV chunks; move the in-memory depth check into jsonio.
  - [x] FX0.02c Deeply nested entries in all four caches miss and regenerate without `RecursionError`.
- [x] FX0.03 Add manifest schema v2 (R12; this is the manifest bump in spec §3).
  - [x] FX0.03a Require `schema_version=2`; add `Chapter.generated_fingerprint` and `Chapter.warnings`.
  - [x] FX0.03b Analysis fingerprints generated chapter title/ranges/voice and stores low-confidence boundary warnings on the affected chapter.
  - [x] FX0.03c Missing/v1 manifests fail content-free; per-chapter warnings round-trip and structure tests verify boundary warnings are attached.
  - [x] FX0.03d Add the MAINTAINER_GUIDE upgrade note: v1 workspaces require re-analysis in a fresh output directory.

**FX0 gate:** the original TODO shows its true status; every JSON cache read goes through the bounded loader; the v2 manifest is in place.

## Phase FX1 — Security and privacy

- [x] FX1.01 Fix the review UI's Host and token exposure (R1).
  - [x] FX1.01a Check `Host` against the bound loopback authority on every request, and respond 421 or 403 with a generic body before rendering the token or reading the manifest.
  - [x] FX1.01b Reject an `Origin` header that doesn't match the server on `/api/*` GET requests.
  - [x] FX1.01c Tests: a wrong Host on `/`, `/api/manifest` and POST is rejected without the token or book text in the response; the correct Host works; a mismatched Origin on GET is rejected.
- [x] FX1.02 Stop the review UI from wiping voices on save (R10).
  - [x] FX1.02a Make the page's script send `voice_id`. On the server, a missing key means unchanged and an empty string or `null` means clear.
  - [x] FX1.02b Test with the exact request body the page's script builds (extract the builder or mirror it in a fixture): existing voices are kept and edited voices are saved.
- [x] FX1.03 Harden the review UI (R15).
  - [x] FX1.03a Compare tokens as bytes. A non-ASCII or malformed `Authorization` header gets 401 instead of crashing the handler.
  - [x] FX1.03b Tests: mismatched POST Origin (403), oversized body (413), non-ASCII auth (401).
- [x] FX1.04 Make CLI diagnostics content-free (R2).
  - [x] FX1.04a Change `fail()` to print exception text only for `AudiobookError`. Every other exception gets a fixed message for its exception family, which may include the class name.
  - [x] FX1.04b Wrap filesystem operations on output paths so they raise typed errors with fixed, context-specific messages and the right exit codes.
  - [x] FX1.04c Rewrite `tests/test_cli_json_errors.py` so it asserts no path or errno text appears. Add `tests/test_cli_error_privacy.py` covering `analyze --output <file>/sub` in text and JSON modes.
- [x] FX1.05 Redact secrets in `config show` (R26).
  - [x] FX1.05a Mask URL userinfo, query strings, and fields whose names suggest secrets (keep env-var-name fields such as `api_key_env`).
  - [x] FX1.05b Tests: a credential-bearing URL set through env and through TOML never appears in `config show` or `config show --sources`.
- [x] FX1.06 Merge the review-UI part of the spec §6 §8 amendment (the 421 on Host mismatch) into the parent spec.

**FX1 gate:** a DNS-rebinding request learns nothing; no CLI path prints OS text or paths; `config show` prints no secrets; all new privacy tests pass.

## Phase FX2 — Text integrity (extraction)

- [x] FX2.01 Refactor first, with no behaviour change (R44).
  - [x] FX2.01a Move to one heading classifier in the structure layer, used by pdf.py, and remove pdf.py's import of structure internals.
  - [x] FX2.01b Split `extract_pdf` into page-strategy, block-builder and block-kind steps.
  - [x] FX2.01c Emit `kind="list"` for numbered lists or delete the dead list guards (structure.py:423, 1233).
  - [x] FX2.01d The full test suite passes unchanged.
- [x] FX2.02 Stop classifying prose as headings (R6). Test: "introduction of the new tax was delayed until" stays body text and forces no paragraph breaks.
- [x] FX2.03 Never remove real numerals as page numbers (R3).
  - [x] FX2.03a Require all three: the numeral is in the top or bottom band, it is nearer the page edge than the nearest body line, and its sequence is consistent with the page index and page labels. If more than one sequence qualifies, remove none and emit a review warning.
  - [x] FX2.03b Add a sonnet fixture (`12`–`15` above poems, `40`–`43` folios): the poem numbers are kept and the folios removed. Add an ambiguous-sequence fixture: nothing removed and a warning emitted. The existing pagination tests still pass.
- [x] FX2.04 Send pages to auto OCR only when they need it (R4).
  - [x] FX2.04a Trigger OCR only for raster coverage or unusable embedded text. Keep short valid text, and never OCR image-free blank pages.
  - [x] FX2.04b Test with Tesseract made unavailable: a born-digital PDF with a blank page and a "Part One" page analyzes, and every block has origin `embedded`.
- [x] FX2.05 Fix hyphen joining (R5).
  - [x] FX2.05a Join only a hyphen preceded by a letter and followed by a lowercase continuation. Drop the hyphen only when the unhyphenated word appears elsewhere in the document. Never join after a spaced dash or an en/em dash.
  - [x] FX2.05b Tests: "and so -" + "then"; "exam-" + "ple" with and without a supporting occurrence; "well-" + "known".
- [x] FX2.06 Flag damaged and repaired PDFs (R7).
  - [x] FX2.06a When the document reports repair or a page fails to load, add a content-free manifest warning, mark the manifest review-required, and include only page numbers in per-page warnings.
  - [x] FX2.06b Tests: a truncated fixture triggers the warning and the review gate; add `tests/test_damaged_pdf_privacy.py`.
- [x] FX2.07 Bump the extraction/analysis fingerprint version (spec §3), add the MAINTAINER_GUIDE upgrade note, and merge the spec §6 amendments for §4.1, §4.2 and §4.3.

**FX2 gate:** acceptance #3 in the parent spec holds on the sonnet fixture; text PDFs never need Tesseract; damaged sources can't pass silently.

## Phase FX3 — Manifest, review and resume

- [x] FX3.01 Protect hand-edited chapters (R11).
  - [x] FX3.01a Treat a chapter whose current values don't match `generated_fingerprint` as user-edited, and protect it like `manually_approved` under `--no-resume` and `--force`. Warn with the chapter numbers only.
  - [x] FX3.01b Test: an unapproved title edit survives a settings change and reanalysis, while unedited chapters are still recomputed.
- [x] FX3.02 Narrow the analysis fingerprint (R13).
  - [x] FX3.02a Leave budgets, request limits, timeouts, retries, `allow_single_chapter` and consent flags out of the fingerprint. When it really does change, name the changed stage without giving values.
  - [x] FX3.02b Tests: after approval, changing `max_requests` or `allow_single_chapter` is accepted; changing the OCR language gives the stage-naming error; the confirmed case "approve in the review UI, then analyze with `allow_single_chapter=True`" now works.
- [x] FX3.03 Catch chapters with nothing to speak at analysis (R9).
  - [x] FX3.03a Compute each chapter's speakable text at analysis time. For an empty chapter, add a per-chapter warning and a coverage-report entry, and have `convert` refuse it before synthesis unless it is approved.
  - [x] FX3.03b Test: a chapter made entirely of omitted material is reported by `analyze`.
- [x] FX3.04 Make `pack-m4b` safe and clean up old MP3s (R14).
  - [x] FX3.04a Have `pack-m4b` check every sidecar fingerprint against the current manifest, and refuse with exit 6 and the stale chapter numbers.
  - [x] FX3.04b After publishing a chapter, delete any older MP3 and sidecar that carry the same chapter ID in a valid sidecar. Never touch files without our sidecar.
  - [x] FX3.04c Tests: a `pack-m4b` CLI happy path (FFmpeg-gated); stale refusal; rename cleanup; an unrelated file in `audio/` survives.
- [x] FX3.05 Merge the spec §6 §5 amendment into the parent spec; §5 warnings, empty-chapter approval, and manual-edit preservation are present.

**FX3 gate:** acceptance #8 in the parent spec holds for unapproved edits; approved workspaces tolerate operational setting changes; `pack-m4b` can't package stale audio.

## Phase FX4 — LLM budget, caching and providers

- [x] FX4.01 Stop failed connections from permanently blocking budgeted runs (R16).
  - [x] FX4.01a Add the `unbilled` ledger status for attempts that never sent the request (connect errors, DNS and connect timeouts, TLS handshake failure). Everything else stays `unknown`.
  - [x] FX4.01b Move model discovery before reservation so it never reserves budget.
  - [x] FX4.01c Add `pdf2audiobook budget show --output DIR` and `budget resolve … (--tokens P:C | --unbilled) --confirm`.
  - [x] FX4.01d Tests: a connect error leaves no blocking row; a read timeout leaves `unknown`; `resolve` unblocks the run; a `budget` CLI privacy test.
- [x] FX4.02 Count every retry against the budget (R17).
  - [x] FX4.02a Make each HTTP attempt reserve and settle its own ledger row and count toward `max_requests`, and stop retrying when the budget runs out.
  - [x] FX4.02b Test: with `max_requests=1`, a timeout is not retried, and the ledger matches the attempts made.
- [x] FX4.03 Warn once per data scope (R18).
  - [x] FX4.03a Give page images and text windows separate warnings, with an accurate whole-book wording for text, plus the provider and model.
  - [x] FX4.03b Tests: vision followed by text gives two warnings; text only gives one.
- [x] FX4.04 Resolve llama-server's `"auto"` model before keying the caches (R19).
  - [x] FX4.04a Resolve the served model before computing cache identity and the analysis key. Raise `LLMError` when it is ambiguous or unavailable and no concrete model is configured.
  - [x] FX4.04b Test: changing the stubbed served model invalidates the cache and the analysis stage fingerprint.
- [x] FX4.05 Adapt to unsupported provider parameters (R20).
  - [x] FX4.05a When a provider rejects `max_tokens` or `temperature`, retry once without it, remember that per provider instance, and count it under R17. Optionally use JSON-schema mode where the provider declares support.
  - [x] FX4.05b Add provider-matrix contract cases for each rejected parameter.
- [x] FX4.06 Record LLM decisions for every task (R21).
  - [x] FX4.06a Generalize to an `LLMDecision` record, emitted for the heading, cleanup, classification and narration tasks, and persist it in `reports/`.
  - [x] FX4.06b Tests: accepted and rejected records for each task.
- [x] FX4.07 Add the LLM task for contents-page entries and chapter boundaries (R22).
  - [x] FX4.07a Add a bounded, anchored, toggleable task whose results are weak evidence below outline, printed contents and numbered labels, verified the same way as headings.
  - [x] FX4.07b Tests with stubbed responses: valid proposals, unknown IDs and invented text.
- [x] FX4.08 Bump the LLM cache identity (spec §3); verify the spec §6.2–§6.4 amendments and §8 budget command are merged into the parent spec.

**FX4 gate:** budgets reflect every attempt and never deadlock on provably unsent requests; consent warnings are accurate; P3.01d, P3.02a, P3.03a and P3.06 are fully met.

## Phase FX5 — Configuration and CLI

- [x] FX5.01 Reject config sections that aren't tables (R27). Parametrized CLI tests cover every top-level section and assert exit 2 with content-free diagnostics.
- [x] FX5.02 Fix the config directory lookup and path resolution (R28).
  - [x] FX5.02a Ignore an empty or relative `XDG_CONFIG_HOME`.
  - [x] FX5.02b Tests: `user_config_path` under unset, empty, relative and absolute values; relative `output_dir` from CLI, env and explicit TOML.
- [x] FX5.03 Parse env values by field type (R29). Regression covers every declared environment variable, including numeric-looking model and output-directory strings.
- [x] FX5.04 Accept only MP3-compatible sample rates (R30). CLI, env and TOML values of 96000 fail with exit 2 before synthesis.
- [x] FX5.05 Give every boolean switch both forms (R24).
  - [x] FX5.05a Add paired `--llm`, remote-consent, vision and single-chapter options with unset defaults; audit recursion and resume for paired forms.
  - [x] FX5.05b CLI tests prove negative flags override TOML `true`, including revoking remote consent.
- [x] FX5.06 Apply TTS options to the provider in use (R25).
  - [x] FX5.06a Resolve the effective provider first; provider-specific environment values override generic ones, and CLI options override both. Validate Piper speaker IDs before synthesis.
  - [x] FX5.06b CLI tests cover Kitten and Piper selected by TOML, environment and CLI.
- [x] FX5.07 Add TTS options to `batch` (R34). CLI options override per-book profile values while non-overridden profile values still apply.
- [x] FX5.08 Fix logging levels (R31).
  - [x] FX5.08a Failures are ERROR, warnings WARNING, command starts DEBUG; `--quiet` selects ERROR, `--verbose` DEBUG, and `general.log_level` applies otherwise.
  - [x] FX5.08b Tests cover configured levels, quiet warnings and visible default CLI failures.
- [x] FX5.09 Warn about the unused `cache.directory` (R32). Explicit settings warn once, `config show` labels it unused, and examples no longer recommend it.
- [x] FX5.10 Merge the configuration/environment/path amendments into parent spec §7 and the paired-flag/CLI amendment into §8; §6 requirements remain merged from FX4.

**FX5 gate:** acceptance #6 in the parent spec passes at the CLI level for every switch; every TTS option reaches the provider that is actually used.

## Phase FX6 — TTS and audio

- [x] FX6.01 Pin `kittenml` to a bounded range that includes the locked version, and regenerate `uv.lock` deliberately (R43).
- [x] FX6.02 Identify TTS models by content (R35).
  - [x] FX6.02a For Piper, hash the `.onnx` and `.onnx.json` files, memoized by path, size and mtime. For Kitten, use the resolved model ID plus the `kittenml` version. Use this in both the WAV and MP3 keys.
  - [x] FX6.02b Tests: replacing the model bytes at the same path invalidates the audio; changing the working directory with an equivalent absolute path does not.
- [x] FX6.03 Turn unspeakable paragraphs into pauses (R37). Test: a `* * *` paragraph makes a pause entry and no TTS call, and coverage still passes.
- [x] FX6.04 Add narration normalization (R38).
  - [x] FX6.04a Add a deterministic table for spoken text only (quotes, dashes, ellipses, ligatures, soft and zero-width characters, NBSP), and put its version in the audio fingerprint.
  - [x] FX6.04b Tests for each table entry, plus a check that the source text is unchanged.
- [x] FX6.05 Apply pronunciation keys that contain punctuation (R39).
  - [x] FX6.05a Validate keys (no whitespace or marker syntax, at most 64 characters) and match whole tokens with the spec's punctuation stripping.
  - [x] FX6.05b Tests: `Dr.`, `U.S.,`, `(C++)` and `Hermione.` apply; an invalid key is rejected at load.
- [x] FX6.06 Trust voice markers only in approved chapters (R8).
  - [x] FX6.06a Honour markers only in approved chapters. An unapproved chapter with markers fails before synthesis, while the others continue and the run exits 7. Check marker voice IDs before any synthesis.
  - [x] FX6.06b Tests for the unapproved, approved and unknown-voice cases.
- [x] FX6.07 Add TTS retries and partial completion (R36).
  - [x] FX6.07a Add `tts.max_retries` (default 2) with bounded backoff. A chapter that still fails is marked failed and the run continues, exiting 7 with the failed chapter numbers.
  - [x] FX6.07b Tests: a transient failure is retried; a persistent failure in chapter 2 of 3 still produces 1 and 3 and exits 7; a resume regenerates only chapter 2.
- [x] FX6.08 Add optional cover art (R40).
  - [x] FX6.08a Add `--cover PATH` (convert and batch) and `audio.cover_image`. Accept JPEG or PNG by magic bytes, up to 5 MiB, embed it as an ID3 APIC front cover, include its hash in the MP3 fingerprint, and embed it in `pack-m4b`.
  - [x] FX6.08b Tests: APIC is present and matches (FFmpeg-gated); an invalid or oversized image exits 2; a changed image regenerates the MP3s; a cover privacy test.
- [x] FX6.09 Bound chapter audio memory (R41).
  - [x] FX6.09a Stream validated chunk PCM to a temporary chapter WAV on disk.
  - [x] FX6.09b tracemalloc test: peak memory for N and 4N chunks differs by less than one chunk.
- [x] FX6.10 Add an optional real Kitten test (R42), skipped unless `PDF2AUDIOBOOK_KITTEN_SMOKE=1` and the `kitten` extra is installed. It never runs in CI.
- [x] FX6.11 Bump the audio fingerprint version (spec §3), add the MAINTAINER_GUIDE upgrade note, and merge the spec §6 §8 cover-flag amendment and the §9 amendment.

**FX6 gate:** acceptance #7 and #10 in the parent spec still pass; P4.02, P4.03c, P4.05, F.03 and F.06 are fully met.

## Phase FX7 — Documentation and closure

- [x] FX7.01 Add a `--help` usage example to every command, including `budget` and `--cover` (R33). Test: each command's `--help` contains "Example".
- [x] FX7.02 Update the docs (R45).
  - [x] FX7.02a README.md:3: remove the stale "Planned features…" sentence and document the new flags and commands.
  - [x] FX7.02b MAINTAINER_GUIDE.md: paired flags, the `budget` command, cover art, TTS retries, the `ollama_context` test marker, and all spec §3 upgrade notes.
  - [x] FX7.02c Confirm that every spec §6 amendment has been merged into docs/PDF2AUDIOBOOK_SPEC.md.
- [x] FX7.03 Re-check the original TODO items that spec §5 maps to each fixed requirement, citing this TODO's ledger evidence.
- [x] FX7.04 Final gate: `/verify` is green on Python 3.11–3.13 for mypy; the wheel/sdist smoke passes; exact-head Python CI passes on all three versions; record the SHA and run ID below.

**FX7 gate:** every R1–R45 is implemented with passing tests; the original TODO has no item checked without evidence; exact-head CI is green.

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
| 2026-10-25 | 689eb4937b94e14735298b8e8c3a7cbc71c279de | Review fixes spec and TODO drafted; no fixes implemented | Not run | None identified |
| 2026-10-25 | 826a5cbb69284351e4d797a015c67ea42aaf85cb | FX0.02–FX0.03 (bounded cache JSON; manifest v2) | CI run [40173850676](https://github.com/ekkus93/pdf2audiobook/actions/runs/40173850676), success | None |
| 2026-10-25 | 9ab2c88034a1f85f1f4ac32d02a2029b7f3464a0 | FX1.01–FX1.06 (review UI security, voice saves, CLI privacy, config redaction) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1038 tests; CI run [40174161319](https://github.com/ekkus93/pdf2audiobook/actions/runs/40174161319) passed | None |
| 2026-10-25 | 5ee08690ab2f0577175551b088b6cd31ceaa4f82 | FX2.01a, FX2.01c, FX2.02, FX2.04–FX2.05 (shared heading/list classification, OCR selection, hyphen joining) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1041 tests; CI run [40174435021](https://github.com/ekkus93/pdf2audiobook/actions/runs/40174435021) passed | FX2 continues |
| 2026-10-25 | b3e6bbadcd83e4388474b113d3bf6feaa47d739a | FX2.03, FX2.06–FX2.07 (safe folio detection; damaged-source review gate; extraction fingerprint v19) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1045 tests; CI run [40174780336](https://github.com/ekkus93/pdf2audiobook/actions/runs/40174780336) passed | FX2 extraction refactor FX2.01b and final phase gate remain |
| 2026-10-25 | 471e17c29d41424d6ca2fe619dc00449f3f543b0 | FX2.01 (extraction strategy/block construction refactor) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1045 tests; CI run [40174895909](https://github.com/ekkus93/pdf2audiobook/actions/runs/40174895909) passed | FX3+ remain |
| 2026-10-25 | f1a447b9bda2ab5cf8b35ee260f891b7b793c94f | FX3.01 (preserve unapproved hand-edited chapter values during reanalysis) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1047 tests; CI run [40175123119](https://github.com/ekkus93/pdf2audiobook/actions/runs/40175123119) passed | FX3 continues |
| 2026-10-25 | 96ad884c521c12699b479212e026847b59287b19 | FX3.02 (ignore operational settings in analysis identity; report changed stages safely) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1049 tests; CI run [40175307319](https://github.com/ekkus93/pdf2audiobook/actions/runs/40175307319) passed | FX3 continues |
| 2026-10-25 | 267f0085063102a2b8de381c27e48909c797256a | FX3.03 (report empty chapters during analysis and gate synthesis) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1050 tests; CI run [40175448872](https://github.com/ekkus93/pdf2audiobook/actions/runs/40175448872) passed | FX3 continues |
| 2026-10-25 | b7caf90a382f4cd7cac62e541ac1313be5851d59 | FX3.04 (validate M4B inputs and remove only verified obsolete chapter audio); FX3.05 (§5 amendment confirmed) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1053 tests; CI run [40175653997](https://github.com/ekkus93/pdf2audiobook/actions/runs/40175653997) passed on Python 3.11–3.13 | FX4–FX7 remain |
| 2026-10-25 | c8987b5295fc4a6cfb679c3370de6becea5a7eaf | FX4.01 (unbilled request state, content-free budget commands, pre-reservation model discovery); FX4.04 (served model participates in LLM cache and analysis identity) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1062 tests; CI run [40176048905](https://github.com/ekkus93/pdf2audiobook/actions/runs/40176048905) passed on Python 3.11–3.13 | FX4 continues |
| 2026-10-25 | 608f5388d3f540d1157319b4d25d6a69036b971a | FX4.02 (per-attempt ledger reservations); FX4.03 (separate image and whole-book text consent warnings) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1064 tests; exact-head CI [40176305990](https://github.com/ekkus93/pdf2audiobook/actions/runs/40176305990) passed on Python 3.11–3.13 | None |
| 2026-10-25 | cb6cae6325496bb991f7cd8c695be82a0e507a0c | FX4.05 (provider-specific fallback for unsupported `max_tokens` and `temperature`) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1070 tests; exact-head CI [40176433550](https://github.com/ekkus93/pdf2audiobook/actions/runs/40176433550) passed on Python 3.11–3.13 | None |
| 2026-10-25 | d1af74a9a06b2e0e758dcf2aa6a2df3b10e08ae3 | FX4.06 (privacy-preserving decision records for heading, cleanup, classification and narration) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1074 tests; exact-head CI [40176714028](https://github.com/ekkus93/pdf2audiobook/actions/runs/40176714028) passed on Python 3.11–3.13 | None |
| 2026-10-25 | 9144ecbc0d030de452ab5599e299d40a492417d2 | FX4.07 (bounded, optional contents-entry and chapter-boundary proposals) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1081 tests; exact-head CI [40177029369](https://github.com/ekkus93/pdf2audiobook/actions/runs/40177029369) passed on Python 3.11–3.13 | None |
| 2026-10-25 | c93d7904a3750bf95b43e136ad79538febbbc1ea | FX4.08 (LLM cache identity v4; parent spec §6.2–§6.4 and §8 amendments confirmed) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1081 tests; exact-head CI [40177115817](https://github.com/ekkus93/pdf2audiobook/actions/runs/40177115817) passed on Python 3.11–3.13 | None |
| 2026-10-25 | 51d9a72f55387185b02bc9d959445d72da018f1f | FX5.01–FX5.10 (strict config sections, paths and typed env parsing, paired switches, provider-specific TTS precedence, batch options, logging, cache warning, parent spec amendments) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1125 tests; exact-head CI [40177704630](https://github.com/ekkus93/pdf2audiobook/actions/runs/40177704630) passed on Python 3.11–3.13 | None |
| 2026-10-25 | c5096aa1cd1893c26130ff24e6c8443f496bc923 | FX6.01–FX6.11 (model-aware cache identities, narration normalization, retries/partial status, approved voice markers, cover art, bounded-memory WAV streaming and optional Kitten smoke) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1181 passed and 1 skipped; exact-head CI [40178615306](https://github.com/ekkus93/pdf2audiobook/actions/runs/40178615306) passed on Python 3.11–3.13 including wheel/sdist smoke | FX7 remains |
| 2026-10-25 | 5dc5d4abbd98f3829abef06e36e8f76562f7063c | FX7.01–FX7.04 (examples on every command, README/maintainer updates, original-TODO traceability and final release gate) | Local `/verify`: Ruff, formatting, mypy (22 modules), 1192 passed and 1 skipped; `uv build --wheel --sdist` succeeded; exact-head CI [40178823078](https://github.com/ekkus93/pdf2audiobook/actions/runs/40178823078) passed on Python 3.11–3.13, including wheel/sdist clean-environment smoke | Live OpenAI and llama-server remain deferred per user instruction; optional Piper work remains deferred |
| 2026-10-25 | 9ce20e1fe5beb8ebef68f2c783bb64f844f0a929 | Ran the opt-in real Kitten smoke after installing the locked `kitten` extra (`kittenml` 0.9.6) | `PDF2AUDIOBOOK_KITTEN_SMOKE=1 uv run --locked --extra dev --extra kitten pytest -q tests/test_kitten_real_smoke.py`: 1 passed | None |
