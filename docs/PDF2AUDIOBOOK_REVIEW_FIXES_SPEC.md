# PDF2Audiobook — Review Fixes Specification

**Status:** R1–R45 implemented in FX0–FX7 (through 2904f19); R46–R63 (§8) implemented in FX8 (5c8eff7); third review added R64–R79 (§9), implementation pending
**Date:** 2026-10-25
**Baseline:** master at 689eb4937b94e14735298b8e8c3a7cbc71c279de
**Parent specification:** docs/PDF2AUDIOBOOK_SPEC.md
**Companion:** docs/PDF2AUDIOBOOK_REVIEW_FIXES_TODO.md

## 1. Purpose and scope

On 2026-10-25 the code was reviewed against docs/PDF2AUDIOBOOK_TODO.md. That review found security, privacy and text-integrity bugs, items marked `[x]` that are only partly done or not done, and design weaknesses. This document gives the required behaviour and the acceptance tests for every fix that review raised. Each requirement has an ID (R-xx). The companion TODO orders those IDs by dependency.

This document adds to the parent spec and does not replace it. Where the two disagree, the parent spec wins, except for the amendments listed in §6, which get merged into the parent spec as part of the work. File and line references point to the baseline commit and are approximate. Check the current code before editing.

Severity labels come from the review: **H** high, **M** medium, **L** low, **D** design or quality, **T** a TODO item marked done that is actually partial or wrong.

## 2. Ground rules

Everything in parent spec §12 and the CLAUDE.md invariants still applies. In particular:

- **Content-free diagnostics.** Errors, logs and terminal output must never echo book text, private paths, credentials or raw OS/library exception text. Every new error path gets a `tests/test_*_privacy.py` test.
- **No invented or silently dropped text.** Anything removed from narration needs an audit record with a reason. When the code is uncertain, it keeps the text and flags it for review.
- **Content-addressed resume.** Any change to derived semantics must bump the relevant fingerprint or schema version. Old manifest versions are rejected, never migrated.
- **Cache robustness.** A bad cache entry is a miss, never an error or a crash.
- **Fail-closed budget.** The budget ledger fails closed and uses exact `Decimal` math.
- **Offline CI.** CI never needs the network, paid APIs, GPUs or model downloads. Real-engine tests are opt-in.
- **Typed new modules.** Every new module under `src/` goes in `[tool.mypy].files`.
- **One bug, one test.** Each bug fix adds a regression test that fails at the baseline.

## 3. Coordinated breaking changes

Several fixes change persisted formats or fingerprints. Make each of these bumps **once**, inside the phase that introduces it, rather than once per requirement:

| Bump | Covers | Effect on existing workspaces |
| --- | --- | --- |
| Manifest `schema_version` 1 → 2 | R11, R12 (and R9's per-chapter warning) | v1 manifests are rejected with a content-free "re-run analyze" message |
| Extraction/analysis fingerprint version | R3, R4, R5, R6, R7, R13 (fingerprint composition) | Cached analysis is recomputed; approved v2 workspaces are protected as usual |
| Audio (WAV chunk + MP3 sidecar) fingerprint version | R35, R37, R38, R39, R40 | Chapter audio is regenerated on the next convert |
| LLM cache identity v4 | R19–R22 | Old LLM cache entries become misses |

Record each bump in docs/MAINTAINER_GUIDE.md as an upgrade note, so users know to re-run `analyze`/`convert`.

## 4. Requirements

### 4.1 Security and privacy

**R1 — Review UI must check the Host header (H1, F.05).**
*Problem:* `GET /` puts the bearer token into the page, and `GET /api/manifest` returns the book's content, without checking `Host` (review_ui.py:180-185). A page that uses DNS rebinding to point its domain at 127.0.0.1 can read the token and then the book.
*Required:*
- Every request (GET and POST, every route) must have a `Host` header exactly equal to the bound authority (`127.0.0.1:PORT`, `[::1]:PORT` or `localhost:PORT` when bound to loopback by name). Otherwise the server responds 421 (or 403) with a generic body, before rendering the token or reading the manifest.
- `/api/*` GETs must also reject a present `Origin` header that doesn't match the server origin. The existing POST Origin check stays.
*Tests:*
- A wrong `Host` on `/`, `/api/manifest` and POST is rejected, and the response body contains neither the token nor any manifest text.
- The correct `Host` works.
- `Host: 127.0.0.1:PORT` with a mismatched `Origin` on `/api/manifest` is rejected.

**R2 — CLI diagnostics must be content-free (H2, P0.02a).** *Amended by R54 (§8).*
*Problem:* `fail()` prints `str(exc)` for every exception (cli.py:25-44). OS errors leak paths that include the book's filename stem, and `tests/test_cli_json_errors.py:29,43` asserts that leak.
*Required:*
- `fail()` prints the message only for `AudiobookError` subclasses, whose messages are fixed strings.
- For any other exception, the message is a fixed string chosen by exception family, and it may include the exception class name. For example: `OSError` → "A filesystem operation failed", `ValueError` → "Invalid input value", anything else → "Unexpected internal error".
- Text output and `--json` output follow the same rule.
- Where a command performs filesystem operations on user-supplied output paths, wrap them so they raise a typed `AudiobookError` with a context-specific fixed message (e.g. "Could not create the output workspace") and the right exit code.
*Tests:*
- Rewrite `test_cli_json_errors.py` to assert that no path, errno text or filename stem appears.
- Add `tests/test_cli_error_privacy.py`, which drives `analyze --output <file>/sub` in text and JSON modes.

**R26 — `config show` must redact secrets (L, P0.03d).** *Amended by R55 (§8).*
*Problem:* `settings_public` does no masking (config.py:286-288).
*Required:*
- `config show`, with or without `--sources`, replaces URL userinfo and the entire query string with `***`.
- It also masks the value of any field whose name contains `key`, `token`, `secret` or `password`, except fields that hold an env-var *name* (e.g. `api_key_env`, `password_env`).
*Tests:* a URL with `user:sk-SECRET@` set through env and through TOML never appears in the output.

**R15 — Review UI robustness (L, F.05).** *Amended by R62 (§8).*
*Required:*
- Token comparison uses bytes. A non-ASCII or malformed `Authorization` header gets 401, never a handler crash (review_ui.py:154).
- Add tests for:
  - a mismatched POST `Origin` (403);
  - an oversized body (413);
  - the Host check (R1);
  - the exact JSON body the page's own JavaScript builds (R10).

### 4.2 Text integrity

**R3 — Real numerals must never be removed as page numbers (H3, P1.04c).** *Amended by R47 (§8).*
*Problem:* In a 4-page fixture of numbered sonnets (`12`–`15` centred above each poem, real page numbers `40`–`43` at the foot), cleanup removed the poem numbers and kept the page numbers (structure.py:507-587).
*Required:* A standalone numeral can be removed as a page number only if all of these hold:
- it lies in the top or bottom band;
- it is nearer the page edge than the nearest body line on that page;
- its sequence is consistent with the physical page index (and with page labels when present, parent spec §4.2).

If more than one numeric sequence on the same pages still qualifies after these checks, remove none of them. Keep them all and emit a content-free review warning (low-confidence candidates stay in the text, parent spec §4.2).
*Tests:*
- The sonnet fixture keeps `12`–`15` and removes `40`–`43`.
- A fixture with two equally plausible sequences removes nothing and emits a warning.
- The existing pagination tests still pass.

**R4 — Auto OCR must only target pages that need it (M8, P1.02).** *Amended by R48 (§8).*
*Problem:* Any page with fewer than 24 characters is sent to OCR even when it has no images (pdf.py:589-590, 883). Born-digital PDFs with blank or title pages then need Tesseract, and correct embedded text gets replaced by OCR text.
*Required:*
- In `--ocr auto`, a page goes to OCR only if it has raster image coverage above the existing threshold, or its embedded text is unusable (replacement characters, invalid fonts, the existing quality heuristics).
- Short but valid embedded text on an image-free page is kept as embedded text.
- An image-free blank page produces no blocks and never invokes OCR.
*Tests:*
- With Tesseract made unavailable (monkeypatched discovery), a born-digital PDF containing a blank page and a "Part One" title page analyzes successfully, and every block has origin `embedded`.
- The existing hybrid and mixed OCR tests still pass.

**R5 — Hyphen joining must be correct (L, P1.03a).**
*Problem:* Any line ending in `-` is joined to the next lowercase line, so "and so -" + "then" becomes "and so -then" (structure.py:1287). Discretionary hyphenation ("exam-" / "ple") is never joined, which parent spec §4.3 requires.
*Required:*
- A line-end hyphen is a joining candidate only if a letter comes immediately before it and a lowercase letter starts the next line.
- Remove the hyphen (true discretionary hyphen) only when the joined word appears elsewhere in the same document without a hyphen. Otherwise keep it, giving "exam-ple".
- Never join after a dash preceded by a space, or after an en or em dash.
- Use the existing unused `WRAPPED_LINE_END` (structure.py:37), or delete it.
*Tests:* the three cases above, plus legitimate compounds like "well-known" split across lines.

**R6 — Prose must not be classified as headings (L).**
*Problem:* A prose line that starts with prologue/epilogue/introduction/preface, such as "introduction of the new tax was delayed until", becomes `kind=heading` (pdf.py:185-202). `labelled_heading` in structure.py already rejects such lines.
*Required:* There is one heading classifier, shared by extraction and structure analysis (see R44). An unnumbered label word followed by lowercase continuation text is not a heading.
*Test:* that prose line keeps body kind and doesn't force paragraph breaks around it.

**R7 — Repaired or damaged PDFs must be flagged (D, P1.01b, P5.07).** *Amended by R48 (§8).*
*Problem:* PyMuPDF silently repairs truncated files, and pages can lose their text with only a generic "no readable text" warning.
*Required:*
- After opening, if PyMuPDF reports the document was repaired (`is_repaired`) or any page fails to load, record a content-free manifest warning ("source PDF was damaged and repaired; verify page coverage").
- Mark the manifest as needing review, so `convert` requires approval or explicit acknowledgement, the same way the low-confidence chapter gate works.
- Per-page failures carry page numbers only.
*Tests:*
- A truncated fixture produces the warning and the review requirement.
- Add a `tests/test_damaged_pdf_privacy.py` privacy test.

**R8 — Voice markers in unapproved text must not be trusted (D, F.06c).** *Amended by R60 (§8).*
*Problem:* `[[voice:…]]` lines that come from the PDF itself can switch voices (audio/__init__.py:52-94). That conflicts with the rule that PDF text is never instructions.
*Required:*
- Markers are honoured only in chapters with `manually_approved=True`.
- In an unapproved chapter that contains marker syntax, conversion of that chapter fails before synthesis with a content-free error naming only the chapter number. Other chapters proceed, and the run exits 7 (partial).
- Marker voice IDs are checked against the provider's voices before any synthesis starts.
*Tests:* an unapproved chapter with a marker fails; the same chapter approved succeeds; an unknown marker voice fails before any chunk is synthesized.

**R9 — Chapters with nothing to speak must be caught at analysis (T, P2.02a).** *Amended by R53 (§8).*
*Problem:* A chapter whose speakable text is empty fails only during TTS ("no speakable text", audio/__init__.py:261-262).
*Required:*
- `analyze` computes the speakable text of each chapter, after omission policies.
- An empty chapter gets a per-chapter warning (R12) and a coverage-report entry.
- `convert` refuses that chapter before synthesis unless it was explicitly approved.
*Test:* a fixture chapter made entirely of omitted material is reported at analysis time.

### 4.3 Manifest, review and resume

**R10 — Saving in the review UI must keep chapter voices (M4, F.05).**
*Problem:* The page's save request leaves out `voice_id` (review_ui.py:62-66), and the server then clears every chapter's voice (review_ui.py:128-130). The test builds its request by hand (tests/test_review_ui.py:60-61).
*Required:*
- The page sends `voice_id` from its field.
- The server treats a *missing* `voice_id` key as "unchanged" and an explicit empty string or `null` as "clear".
*Test:* POST the exact body the page's script produces (extract the builder or mirror it in a fixture) and assert voices are kept and edited voices are saved.

**R11 — Hand edits must survive reanalysis (M7, P2.03a).** *Amended by R53 (§8).*
*Problem:* Edits to an unapproved manifest (e.g. a changed chapter title) are overwritten on reanalysis (pipeline.py:127-138), which breaks parent spec §145.
*Required:*
- Manifest v2 stores a `generated_fingerprint` for each chapter: a hash of title, start, end and voice as analysis produced them.
- On reanalysis, a chapter whose current values don't match its `generated_fingerprint` is user-edited. It is protected exactly like `manually_approved`, even with `--no-resume` or `--force`.
- A content-free warning lists the protected chapter numbers.
*Tests:* edit a title without approving it, change an analysis setting, and the title survives; unedited chapters are still recomputed.

**R12 — Manifest schema v2 (D, P0.05b, P2.01b).**
*Required:*
- `schema_version` is required and equals 2. A missing or other version is rejected, never defaulted (models.py:84-102).
- `Chapter` gains `generated_fingerprint` (R11) and `warnings: list[str]`, so boundary-specific warnings attach to their chapter instead of only to the book.
- Book-level `warnings` stays for book-wide issues.
*Tests:*
- A manifest with no version, or with v1, is rejected with a content-free message.
- Per-chapter warnings round-trip.
- Boundary warnings from structure analysis land on the right chapter.

**R13 — Analysis fingerprint scope (D).**
*Problem:* Operational settings such as `max_requests`, budgets and `--allow-single-chapter` feed the analysis fingerprint (pipeline.py:107-117). Changing them in an approved workspace is a hard error with no way forward except a new output directory.
*Required:*
- Only settings that change derived text or structure go into the analysis fingerprint.
- These stay out: budgets, request limits, timeouts, retries, gating flags like `allow_single_chapter`, and remote-consent flags.
- When an approved workspace's fingerprint really does change, the error names which stage's inputs changed (extraction, OCR, structure, LLM). It must not include values.
*Tests:*
- Changing `max_requests` or `allow_single_chapter` after approval is accepted.
- Changing the OCR language after approval gives the stage-naming error.
- Covers the confirmed failure "approve in the review UI, then analyze with `allow_single_chapter=True`".

**R14 — `pack-m4b` must not package stale audio, and old MP3s must be cleaned up (M10, D, F.04).** *Amended by R52 (§8).*
*Problem:* `pack-m4b` only checks that the files exist (cli.py:437-443). MP3 names include the title (audio/__init__.py:694-695), so a renamed chapter leaves its old MP3 behind.
*Required:*
- `pack-m4b` checks each chapter MP3's sidecar fingerprint against the fingerprint `convert` would compute for the current manifest chapter. If any don't match, it refuses with exit 6 and lists the stale chapter numbers.
- After `convert` successfully publishes a chapter, it deletes other MP3 files and sidecars in `audio/` *whose valid sidecar records the same chapter ID*. Files without a valid sidecar of ours are never touched.
*Tests:*
- A CLI test for `pack-m4b`, gated on FFmpeg and skipped without it.
- The stale-refusal case.
- The rename-cleanup case.
- An unrelated file in `audio/` survives.

### 4.4 LLM budget, caching and providers

**R16 — Failed connections must not permanently block budgeted runs (M5, P3.06).** *Amended by R49, R50 (§8).*
*Problem:* Every failed call, even a connection refusal, settles as `unknown` (llm/cache.py:259-298). `unknown` rows block every later run that has a token or USD budget (budget.py:112), and the only fix is editing SQLite by hand.
*Required:*
- Add the ledger status `unbilled` for attempts that provably never sent the request body: connection refused, DNS failure, connect timeout, and TLS handshake failure (httpx `ConnectError`/`ConnectTimeout`). `unbilled` rows are not unresolved and don't count against budgets.
- Model discovery (e.g. resolving `"auto"`) runs before reservation and never reserves budget.
- Any other failure still settles as `unknown`, which keeps the fail-closed behaviour.
- Add `pdf2audiobook budget show --output DIR`, which lists ledger rows by ID, status, tokens and cost. It shows no prompt content.
- Add `pdf2audiobook budget resolve --output DIR REQUEST_ID (--tokens PROMPT:COMPLETION | --unbilled) --confirm`, which settles an `unknown` row.
*Tests:*
- A connect error leaves no blocking row.
- A read timeout after the request was sent leaves `unknown`.
- `resolve` unblocks the run.
- Add a `budget` CLI privacy test.

**R17 — Retries must count against budgets (M6, P3.06).** *Amended by R49 (§8).*
*Problem:* Retries happen inside the provider (llm/__init__.py:398-402, 442-446). Three uploads are recorded as one request.
*Required:*
- Each HTTP attempt reserves and settles its own ledger entry and counts toward `max_requests`.
- Move the retry loop into the budgeted wrapper, or give the provider a per-attempt reservation callback.
- If the budget is exhausted between attempts, stop retrying and raise the budget error.
*Test:* with `max_requests=1`, a timeout followed by a retry is refused after the first attempt, and the ledger shows exactly the attempts made.

**R18 — The remote-content warning must state the real scope (L, P3.05).**
*Problem:* The warning fires once, for whichever content goes first. After a vision call, it says "one rendered PDF page", and then all the book's text is uploaded with no further notice (llm/__init__.py:375-384, pipeline.py:212).
*Required:*
- Warn once per distinct data scope: page images (with the page cap) and text analysis windows.
- The text warning says it covers the whole book in bounded windows.
- Each warning names the provider and model (parent spec §6.4).
*Tests:* vision followed by text emits two accurate warnings; text only emits one.

**R19 — llama-server `"auto"` model identity (L, P3.06).**
*Problem:* The cache identity and analysis key hash the literal `"auto"` (pipeline.py:44, 112), not the model the server resolves (llm/__init__.py:184-190).
*Required:*
- Resolve the served model ID before computing cache identity and the analysis key, and include it in the usage report.
- If resolution fails or is ambiguous, raise an `LLMError`, unless a concrete model is configured.
*Test:* switching the stubbed served model changes the cache identity and invalidates the analysis.

**R20 — Capability adaptation (T, P3.01d).** *Amended by R49 (§8).*
*Problem:* Only `response_format` has a fallback (llm/__init__.py:192-210). `max_tokens` and `temperature` are always sent (:362-372).
*Required:*
- If a provider rejects `max_tokens` or `temperature` as unsupported, retry once without that parameter, remember the result for the provider instance, and count the retry under R17.
- Optionally use JSON-schema response format where the provider declares support. Local validation stays mandatory either way.
*Tests:* add contract cases in the provider matrix for each rejected parameter.

**R21 — Audit records for every LLM task (T, P3.03a).**
*Problem:* Only cleanup has decision records (`CleanupDecision`, llm/__init__.py:53-63). Heading, narration and classification rejections appear only as free-text warnings.
*Required:*
- Generalize to an `LLMDecision` record with: task, sanitized block ID, proposal summary, accepted/rejected, reason code, confidence and provider.
- Emit it for every task and persist it in `reports/` next to the existing cleanup audit.
*Test:* each task's accepted and rejected paths produce records.

**R22 — LLM classification of contents-page entries and boundaries (T, P3.02a).** *Amended by R51 (§8).*
*Problem:* The LLM only proposes headings (llm/__init__.py:618-670). Parent spec §6.2 also requires contents-page (TOC) candidates and anchored boundaries.
*Required:*
- Add a bounded task that classifies candidate contents-page blocks and chapter-boundary candidates by anchored block ID, with confidence.
- Treat the results as weak evidence, below outline, printed contents and numbered labels, with the same deterministic verification as headings.
- The task can be toggled independently.
*Tests:* stubbed responses with valid, unknown-ID and invented-text proposals.

### 4.5 Caches

**R23 — A shared bounded JSON loader (M11, P1.02c, P4.04c).**
*Problem:* A deeply nested OCR cache file (pdf.py:800-806) or MP3 sidecar (pipeline.py:495, 516) raises `RecursionError` and aborts the run.
*Required:*
- Add `src/pdf2audiobook/jsonio.py` (and list it in mypy) with `load_bounded_json(path, *, max_bytes, max_depth) -> Any | None`. It:
  - caps the bytes read;
  - pre-scans nesting depth over the raw bytes outside strings before decoding, or catches `RecursionError`;
  - rejects NaN/Infinity;
  - returns `None` for any malformed entry.
- Move the depth check from llm/cache.py (`_bounded_cache_json_structure`) here.
- Use the loader for the OCR cache, MP3 sidecars, the WAV chunk cache metadata and the LLM cache.
*Test:* every one of those caches treats a `b"[" * 100000` entry as a miss and regenerates.

### 4.6 Configuration and CLI

**R24 — Every boolean switch has a positive and a negative form (D, P0.03b, P5.06).**
*Problem:* `--no-llm`, `--allow-remote-content`, `--vision` and `--allow-single-chapter` can only be switched on (cli.py:211-217, 274-292). Nothing on the CLI can override a `true` set in TOML (parent spec §7).
*Required:*
- Use paired options: `--llm/--no-llm`, `--allow-remote-content/--no-allow-remote-content`, `--vision/--no-vision`, `--allow-single-chapter/--no-allow-single-chapter`.
- Audit every command for any other one-way boolean.
- Each defaults to `None` (unset), so precedence resolves explicit false correctly.
*Tests:* CLI-level (not `load_settings`) tests show a TOML `true` overridden by the negative flag for each switch, including revoking remote consent.

**R25 — TTS options apply to the provider actually in use (M9, P0.03c, P4.01b).**
*Problem:* `--voice`, `--tts-model` and `--speed` reach the Piper settings only when `--tts-provider piper` is passed explicitly (cli.py:192-195, 312-333). `PDF2AUDIOBOOK_TTS_VOICE` and `PDF2AUDIOBOOK_TTS_MODEL` always target Kitten (config.py:173, 177).
*Required:*
- First resolve the effective provider from all layers.
- Then apply the generic CLI options and generic env vars to that provider's section. Provider-specific env vars (e.g. `PDF2AUDIOBOOK_TTS_PIPER_SPEED`) win over generic env vars; the CLI wins over both.
- Check values against the target provider (e.g. Piper speaker IDs must be decimal).
*Tests:*
- CLI tests cover `--tts-provider`, `--tts-model`, `--voice`, `--speed`, `--sample-rate` and `--bitrate` with Kitten, and with Piper selected by TOML, by env and by CLI.

**R27 — Config sections that aren't tables (L).**
*Problem:* A TOML file with `general = 5` plus an env override crashes with a traceback (config.py:187-190). The guard only covers `llm` (config.py:253-256).
*Required:* Before overlays are applied, every known top-level section that is present must be a table. Otherwise raise a content-free `ConfigError` (exit 2).
*Test:* a parametrized test over every section.

**R28 — Config directory lookup and path resolution (L, P0.03a, P0.03e).**
*Required:*
- An empty or relative `XDG_CONFIG_HOME` is ignored (XDG Base Directory spec), so the code falls back to `~/.config` (config.py:182).
- Relative paths are resolved the way parent spec §7 says.
*Tests:* `user_config_path` under unset, empty, relative and absolute XDG values; relative `output_dir` from CLI, env and explicit TOML.

**R29 — Env values are parsed by field type (L).**
*Problem:* Every env value is JSON-decoded (config.py:211-217), so `PDF2AUDIOBOOK_LLM_MODEL=7` or `PDF2AUDIOBOOK_OUTPUT_DIR=2024` is rejected.
*Required:*
- String fields take the raw string.
- Booleans accept `true/false/1/0/yes/no` (case-insensitive).
- Numeric fields are parsed as numbers.
- Only list and table fields accept JSON.
*Tests:* a parametrized test over the env table.

**R30 — Only MP3-compatible sample rates are accepted (L).**
*Problem:* `sample_rate` allows up to 96000 (config.py:108). Encoding then fails only after a whole chapter has been synthesized.
*Required:* Restrict it to MPEG audio rates {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000} at config validation, for CLI, env and TOML.
*Test:* 96000 is rejected with exit 2 before any synthesis.

**R31 — Logging levels, `--quiet` and `general.log_level` (L, D, P0.02b).** *Amended by R62 (§8).*
*Problem:* Every event logs at DEBUG and the default level is INFO (logging.py:49, 53), so `--quiet` changes nothing and failures are invisible by default. `general.log_level` is never read.
*Required:*
- Give each event a level: failures ERROR, review/degradation warnings WARNING, stage progress INFO, details DEBUG.
- Default is INFO, `--quiet` is ERROR, `--verbose` is DEBUG.
- When neither flag is given, `general.log_level` applies.
- Output stays allowlist-redacted.
*Tests:* stderr contents at each level, and that `--quiet` suppresses warnings.

**R32 — The unused `cache.directory` setting (D).**
*Required:*
- `cache.directory` (config.py:143) isn't used. While it is still accepted, setting it emits one content-free warning ("cache.directory is not supported and is ignored").
- `config show` labels it unused.
- Remove it from docs and examples.
*Test:* the warning appears when the setting is present and not otherwise.

**R33 — `--help` usage examples (T, P0.04).**
*Required:*
- Every command (`inspect`, `analyze`, `convert`, `doctor`, `config show`, `batch`, `pack-m4b`, `review`, `budget`) has a docstring with at least one example.
- Examples match parent spec §8.
*Test:* each command's `--help` output contains "Example".

**R34 — TTS options for `batch` (T, F.03).** *Amended by R56 (§8).*
*Problem:* `batch` has no TTS options (cli.py:368-412), so the "CLI precedence over per-book profiles" claim can't be exercised.
*Required:*
- Add the R25 TTS options to `batch`.
- Precedence is CLI > per-book profile > config.
*Test:* a CLI-level batch test showing all three tiers.

### 4.7 TTS and audio

**R35 — TTS model identity comes from file content (D, P4.04a).**
*Problem:* Cache keys use the Kitten alias or the Piper `model_path` string (pipeline.py:409-413, 542-557; audio/__init__.py:280; tts/__init__.py:20). Replacing a model file at the same path reuses stale audio.
*Required:*
- For Piper, identity is the SHA-256 of the `.onnx` file and its `.onnx.json` config. Memoize by (resolved path, size, mtime) so the hash isn't recomputed every run.
- For Kitten, identity is the resolved model repository/ID and the installed `kittenml` version.
- Use the identity in both the WAV chunk keys and the MP3 fingerprints.
*Tests:* replacing the model file bytes at the same path invalidates the audio; a run in a different working directory with an equivalent absolute path does not.

**R36 — TTS retries and partial completion (D, P5.07).** *Amended by R61 (§8).*
*Problem:* A single transient TTS failure aborts the whole book (pipeline.py:528-582).
*Required:*
- Add `tts.max_retries` (default 2) with bounded backoff for each chunk.
- Retry only failures explicitly marked transient by the provider. Unknown voices, validation errors and other unmarked failures fail immediately.
- If a chapter still fails after its retries, record it in `reports/conversion_status.json` and continue with the remaining chapters. Do not modify the user-owned manifest. Exit 7 and list failed chapter numbers; `inspect` and `inspect --json` expose the report.
- Completed chunks and chapters stay reusable.
*Tests:* a transient failure succeeds on retry; a persistent failure in chapter 2 of 3 still produces chapters 1 and 3 and exits 7; a resume regenerates only chapter 2.

**R37 — Unspeakable chunks become pauses (D, P4.02).** *Amended by R62 (§8).*
*Problem:* Paragraphs such as `* * *` are sent to the TTS engine as-is (audio/__init__.py:108-124).
*Required:*
- A paragraph that contains no Unicode letters or digits is not synthesized. It becomes a paragraph pause.
- It is recorded in the chunk mapping as `kind="pause"` with its source range, and counted in the conversion report.
- No text is removed from the chapter text.
*Tests:* a scene-break paragraph produces a pause entry and no TTS call, and coverage still passes.

**R38 — Narration normalization (T, P4.02).** *Amended by R57, R58 (§8).*
*Problem:* The only normalization is collapsing whitespace.
*Required:*
- Apply a deterministic, documented normalization table to *spoken* text only. It covers:
  - typographic quotes, dashes and ellipses;
  - ligatures (ﬁ, ﬂ);
  - soft hyphens and zero-width characters;
  - non-breaking spaces.
- Source text and source ranges are unchanged, and the chunk coverage check runs on the normalized form.
- The table's version is part of the audio fingerprint.
*Tests:* each table entry, and a check that source text is untouched.

**R39 — Pronunciation keys with punctuation (L, F.06a).** *Amended by R58 (§8).*
*Problem:* Keys like `Dr.`, `U.S.` and `C++` are accepted but never applied (config.py:115-139 vs audio/__init__.py:51, 61-73).
*Required:*
- Keys must be non-empty, contain no whitespace or marker syntax, and be at most 64 characters. Anything else is rejected at config load.
- Matching works on whitespace-delimited tokens. Strip leading and trailing quotes and brackets (`"'()[]{}<>“”‘’`), and trailing `,;:!?…`. Compare the result exactly to the key; if that fails and the key doesn't end in `.`, also try without one trailing `.`.
- Keys made only of word characters keep their current behaviour.
*Tests:* `Dr.`, `U.S.,`, `(C++)` and `Hermione.` all apply; an invalid key is rejected.

**R40 — Optional cover art (T, P4.03c).** *Amended by R52 (§8).*
*Problem:* There is no cover-art support anywhere. Parent spec §9 requires "optional cover art when available".
*Required:*
- Add `--cover PATH` (convert and batch) and an `audio.cover_image` config key.
- Accept JPEG or PNG, identified by magic bytes, up to 5 MiB.
- Embed it in every chapter MP3 as an ID3 APIC front-cover frame.
- The image's SHA-256 is part of the MP3 fingerprint.
- `pack-m4b` embeds it when given.
- Errors are content-free.
*Tests:* APIC is present and matches; an invalid or oversized image is rejected with exit 2; changing the image regenerates the MP3s (FFmpeg-gated); a privacy test.

**R41 — Chapter audio memory is bounded (D).** *Amended by R59 (§8).*
*Problem:* Each chapter is held in RAM as float32, plus a concatenated copy (audio/__init__.py:228, 392).
*Required:* Stream each validated chunk's PCM into a temporary chapter WAV on disk as it is produced, so peak memory is bounded by chunk size, not chapter length.
*Test:* using tracemalloc with a stubbed TTS, peak memory for N and 4N chunks differs by less than one chunk's worth.

**R42 — Optional real Kitten integration test (T, P4.05).**
*Required:* An opt-in test, skipped unless `PDF2AUDIOBOOK_KITTEN_SMOKE=1` and the `kitten` extra is installed. It synthesizes one short chunk and validates the WAV. It never runs in CI.

**R43 — Pin `kittenml` (T, P0.01a).**
*Required:* Give the `kitten` extra a bounded version range that includes the locked version (pyproject.toml:14), and regenerate `uv.lock` deliberately.

### 4.8 Code health and documentation

**R44 — One heading classifier and a split `extract_pdf` (D).** *Amended by R46 (§8).*
*Required:*
- The extractor and structure analysis share one heading classifier from the structure layer. This also removes the reverse dependency created by pdf.py importing `CHAPTER_WORD`.
- Split `extract_pdf` (pdf.py:819-1064) into a page-strategy step, a block-builder step and a block-kind classifier.
- Either emit `kind="list"` for numbered lists or delete the dead list guards (structure.py:423, 1233).
- No behaviour changes other than R4 and R6. The existing tests must pass unchanged.

**R45 — Documentation and TODO fixes (T, P5.09, review contradictions).**
*Required:*
- README.md:3: remove "Planned features include OCR, chapter detection…".
- docs/PDF2AUDIOBOOK_TODO.md:
  - delete the stale P0.01d note "Retain P0.01b open…";
  - annotate P5.05 so it doesn't read as fully accepted while its live subitems are still open;
  - P5.10 now type-checks 21 modules (update "19 modules");
  - re-mark the items this review found wrong or partial (§5), and record them in the progress ledger.
- MAINTAINER_GUIDE.md: document the new flags, the `budget` command, cover art, TTS retries, the §3 upgrade notes and the `ollama_context` test marker.
- Merge the §6 amendments into PDF2AUDIOBOOK_SPEC.md.

## 5. Traceability

| Review finding | Requirement | Original TODO item(s) to re-mark until fixed |
| --- | --- | --- |
| H1 Review UI rebinding | R1, R15 | F.05 |
| H2 CLI error leak | R2 | P0.02a |
| H3 Numerals removed | R3 | P1.04c |
| M4 Review UI wipes voices | R10 | F.05, F.06b |
| M5 Ledger blocks after a connect failure | R16 | P3.06 |
| M6 Retries bypass the budget | R17 | P3.06 |
| M7 Hand edits overwritten | R11 | P2.03a |
| M8 OCR on image-free pages | R4 | P1.02 |
| M9 TTS flags and Piper | R25 | P0.03c, P4.01b, F.01 |
| M10 Stale pack-m4b audio | R14 | F.04 |
| M11 Nested-cache crash | R23 | P1.02c, P4.04c |
| L config show credentials | R26 | P0.03d |
| L Scalar TOML section | R27 | P0.03b |
| L Remote warning scope | R18 | P3.05 |
| L `"auto"` model key | R19 | P3.06 |
| L Hyphen joining | R5 | P1.03a |
| L Prose taken for a heading | R6 | P1.03b |
| L Pronunciation punctuation | R39 | F.06a |
| L Sample rate above 48 kHz | R30 | P4.03b |
| L Non-ASCII auth header | R15 | F.05 |
| L `--quiet` no-op | R31 | P0.02b |
| L Empty XDG | R28 | P0.03a |
| L Numeric env strings | R29 | P0.03b |
| D One-way booleans | R24 | P0.03b, P5.06 |
| D TTS model identity | R35 | P4.04a |
| D No TTS retries | R36 | P5.07 |
| D PDF-sourced voice markers | R8 | F.06c |
| D Damaged PDFs | R7 | P1.01b, P5.07 |
| D Approved-workspace hard error | R13 | P2.03a |
| D Schema version | R12 | P0.05b |
| D Unused settings | R31, R32 | P0.03 |
| D Duplicate heading logic | R44, R6 | — |
| T Cover art missing | R40 | P4.03c |
| T Per-boundary warnings | R12 | P2.01b |
| T Empty chapters | R9 | P2.02a |
| T No narration normalization | R37, R38 | P4.02 |
| T Capability adaptation | R20 | P3.01d |
| T Contents-page/boundary task | R22 | P3.02a |
| T Audit records | R21 | P3.03a |
| T Help examples | R33 | P0.04 |
| T Batch TTS options | R34 | F.03 |
| T Real Kitten test | R42 | P4.05 |
| T kittenml unpinned | R43 | P0.01a |
| T Stale README/TODO text | R45 | P5.09, P5.10 |
| D Chapter memory | R41 | — |
| T Untested config path resolution | R28 | P0.03e |

## 6. Amendments to PDF2AUDIOBOOK_SPEC.md

Merge these during the work. Each amendment goes into the parent spec in the same commit as the fix it describes.

- **§4.1:** damaged or repaired sources are flagged and require review (R7). Auto OCR is triggered only by raster coverage or unusable text (R4).
- **§4.2:** the numeral rules for "nearer the edge" and "ambiguous sequences are retained" (R3).
- **§4.3:** discretionary hyphens are removed only when the unhyphenated word appears elsewhere in the document (R5).
- **§5:** per-chapter warnings, the empty-chapter gate and protection of user-edited chapters (R9, R11, R12).
- **§6.2:** a separately toggleable bounded task proposes anchored contents entries and body boundary candidates; verified boundary proposals remain weak evidence (R22).
- **§6.3:** ledger statuses including `unbilled`, per-attempt budgeting, and that the analysis fingerprint excludes operational settings (R13, R16, R17).
- **§6.4:** one warning per data scope (R18).
- **§7:** env values parsed by field type, XDG handling, the allowed sample rates, how logging levels map, and that the generic TTS options target the effective provider (R25, R28–R31).
- **§8:** paired boolean flags, `--cover`, `budget show|resolve`, and the 421 response on Host mismatch in the review UI (R1, R16, R24, R40).
- **§9:** voice markers apply only in approved chapters, TTS model identity comes from file content, retries and partial completion, pause chunks, narration normalization, pronunciation matching and cover art (R8, R35–R40).

## 7. Out of scope

These were noted during the review but are not committed to here. Track them separately if wanted:

- Review UI:
  - it can't split or merge chapters;
  - saving keeps the old confidence and evidence;
  - saving re-renders text with the default footnote policy;
  - a missing `Content-Length` returns 413;
  - there is no socket read timeout;
  - concurrent POSTs race on read-modify-write.
- `inspect` doesn't accept `--config`.
- `convert` ignores per-book TTS profiles.
- Book-level warnings embed bookmark titles.
- The OCR cache key uses the Tesseract CLI version, not the version of the linked engine and its tessdata.
- `SourceSpan.confidence` is never set.
- Page-label context isn't used for pagination. (Partly addressed in FX2; R47 governs it.)
- The LLM request timeout is hardcoded and is not a total deadline.
- Live acceptance against llama-server and OpenAI remains deferred, as recorded in PDF2AUDIOBOOK_TODO.md P5.05.

## 8. Second review (FX8)

### 8.1 Context

R1–R45 were implemented in FX0–FX7 and ended at 2904f1975ef131f11ed340264b0b8151e85101a9. At that commit every local gate and every CI run passed. A second review of `7eb4d25..2904f19` against this spec then found:

- regressions introduced by the fixes;
- an existing test whose inputs were changed so a regression would pass;
- fixes that only partly meet their requirement;
- parent-spec amendments that were weakened to match the code.

It also found three places where this spec itself was at fault:

- R16 and R17 together make every retry fail under a token or USD budget;
- R26's "name contains `token`" rule masks ordinary settings;
- R14 and R40 tie `pack-m4b` to convert-time settings it can't know.

This section amends those requirements and adds R46–R63. Where a requirement below says it *amends* an earlier one, it replaces the conflicting text of that one. File and line references point to 2904f19 and are approximate.

Severity labels are the same as in §1. The findings that the second review confirmed by running code are marked **(confirmed)**.

### 8.2 Ground rules added for FX8

- **Never edit an existing test's inputs or expected results to make a change pass.** If a behaviour change is intended, keep the old test as-is or delete it with a reason in the commit message, and add a new test that names the new behaviour.
- **A spec amendment must not weaken a requirement to match the code** unless this section records the decision and its reason.
- **A parent item is `[x]` only when every one of its subitems is `[x]`.**

### 8.3 Text integrity regressions

**R46 — List and heading classification (H, amends R44) (confirmed).** *Amended by R66, R67 (§9).*
*Problem:*
- `_classify_block_kind` checks lists before headings (pdf.py:328), and that turns on the formerly dead guard at structure.py:790.
- Large numbered headings ("1. The Storm", "2. The Calm", "3. The Return") are now kind `list`. The baseline found 3 chapters; 2904f19 finds none.
- "I. THE STORM" is swallowed into front matter because `LIST_LINE` (structure.py:218) accepts a single letter. Lines starting "J. Smith of…" and "A. Smith said" are classified as lists.
- `before.kind == "list"` blocks paragraph joining (structure.py:1324), so a list item's wrapped continuation becomes its own paragraph, and `1990) was` matches the list pattern.
*Required:*
- Heading classification runs before list classification. A line whose font size or weight marks it as a heading, or that stands alone in whitespace on the page, is never a list item.
- A line is a list item only when it is part of a run of at least two consecutive lines with sequential markers (`1.`/`2.`, `a)`/`b)`, `i.`/`ii.`).
- A single capital letter followed by a period and a capitalized word ("J. Smith") is never a list marker. Neither is a bare year or number followed by `)`.
- A list item's wrapped continuation lines join the item.
*Tests (all new; existing tests unchanged):*
- The numbered-heading book yields 3 chapters titled as above.
- "I. THE STORM / II. … / III. …" yields 3 chapters.
- A two-item numbered list with a wrapped second item gives two items, and the wrapped line is joined.
- "J. Smith of the Times said" and "in 1990) was" stay in their sentences.

**R47 — Page-number removal (H, amends R3) (confirmed).**
*Problem:*
- R3's "nearer the page edge than the nearest body line" became a gate on every folio (structure.py:408-430, applied at :588). Folios sitting just under or over the body are no longer removed: tight footer folios, footers with a footnote above them, and header folios close to the body. The baseline removed all of these.
- `test_tight_centered_folios_are_removed_even_when_listed_in_contents` had its folio moved from y=474 to y=500 in b3e6bba so that it still passed.
- When page labels disagree with the printed numbers, all removal is silently turned off (structure.py:432-436, 638-641).
*Required:*
- A single qualifying numeric sequence is removed exactly as it was at the 7eb4d25 baseline: outermost line in its band, consistent with the physical page index.
- Edge distance only breaks ties *between competing sequences* on the same pages. The sequence nearer the paper edge wins. If they are equally near, keep both and emit a review warning.
- Page labels are positive evidence. A sequence that matches the labels wins ties. A disagreement with the labels never turns removal off; it emits one content-free warning saying page labels and printed numbers disagree.
- **Known limitation, to be documented:** a book whose only numeric sequence is poem or section numbers in the margin band looks exactly like folios. It is still removed, and users turn it off with `pdf.remove_page_numbers = false`. Document this in MAINTAINER_GUIDE.md and in parent spec §4.2.
*Tests:*
- Restore `tests/test_scan_text_layer_fragments.py`'s folio geometry to the 7eb4d25 version (y=474) and its original comment.
- Add new tests for the footer-folio, footnote-above-folio and header-folio layouts (all removed).
- The sonnet fixture still keeps 12–15 and removes 40–43.
- Labels 1–4 with printed 40–43 removes 40–43 and warns once.

**R48 — Finish damaged-source handling (M, amends R7 and R4) (confirmed).** *Amended by R69, R73, R74 (§9).*
*Problem:*
- A page that fails to load skips `sizes.append`, which shifts every later page's size (pdf.py:943-966).
- The review gate matches warning strings (pipeline.py:631-646), and there is no review-required field and no acknowledgement path. Approval through the review UI is the only way through, and that isn't tested.
- Pages whose text is drawn as vector outlines, with no text layer and no images, are no longer OCRed. They get only the misleading warning "no readable text (OCR not needed)" (pdf.py:1052).
*Required:*
- Page sizes stay index-aligned. A failed page records a placeholder size and is excluded from geometry-based cleanup.
- The manifest gains `review_required: list[str]`, holding reason codes such as `damaged_source`, `empty_chapter` and `ambiguous_page_numbers`. Gates check those codes, not warning strings. This needs manifest v3 (see §8.8).
- `convert --accept-review REASON` records an explicit acknowledgement for that reason in the manifest, with a content-free log line. Approval in the review UI also clears `damaged_source`.
- In `--ocr auto`, an image-free page whose vector drawings cover more than the raster-coverage threshold, and that has no usable text, is rasterized and OCRed.
*Tests:*
- A 3-page fixture where page 1 fails keeps page 3's own size.
- A damaged source is blocked, then unblocked by `--accept-review damaged_source`, and also by approval.
- A vector-outlined text page is OCRed (Tesseract-gated).

### 8.4 LLM budget and providers

**R49 — Worst-case accounting so retries work under budgets (H, amends R16, R17 and R20) (confirmed).** *Amended by R70 (§9).*
*Problem:*
- Every failed attempt settles as `unknown`, and `reserve` refuses whenever any `unknown` row exists under a token or USD budget (budget.py:111-114).
- Under such a budget, R17's retries and R20's fallbacks therefore always fail after one attempt: 400 "unsupported parameter", 5xx, `ReadTimeout`, `PoolTimeout`.
- R20 drops `max_tokens` entirely instead of substituting `max_completion_tokens`, which removes the output cap (llm/__init__.py:495-509).
*Required:*
- At reservation, record each attempt's conservative upper bound: the existing UTF-8 prompt bound plus the output cap sent with the request. Use the configured cost rates for the USD bound.
- An `unknown` row counts toward budgets *at that upper bound*. It no longer blocks by itself. A new attempt is allowed only if every complete row's actual usage, plus every `unknown` and `pending` row's upper bound, plus the new attempt's upper bound, stays within each configured limit. This keeps the fail-closed property without deadlocking.
- Add the status `rejected` for responses with an HTTP 4xx status other than 408, whose body reports no usage. It counts zero tokens and does not block. (A 4xx means the provider refused the request rather than generating output.)
- 408, 429, 5xx and timeouts after the request was sent stay `unknown`.
- When a provider rejects `max_tokens`, retry with `max_completion_tokens` first. Drop the cap only when no token or USD budget is configured. Under such a budget an uncapped request has no upper bound and is refused with a content-free error.
- Remember a rejected parameter per provider identity, in the LLM cache directory. That way later runs don't repeat the failed attempt.
*Tests:*
- Under `max_reported_tokens`, a 500 then success completes, and the ledger shows both attempts with the upper bound charged for the first.
- A 400 for an unsupported parameter becomes `rejected` and the fallback succeeds.
- Retries stop exactly when the worst-case total would exceed the limit.
- `max_completion_tokens` is substituted.
- An uncapped request under a budget is refused.

**R50 — Correct the `budget` CLI (M, amends R16) (confirmed).** *Amended by R71 (§9).*
*Problem:*
- `budget resolve` reports success after `settle` has rejected the value (cli.py:148-165, budget.py:229).
- Resolved values can overflow SQLite `SUM` (budget.py:67-69), which makes the ledger unreadable and blocks every LLM run permanently.
- `pending` rows can't be resolved (budget.py:298, 316), and resolving uses two transactions.
- `budget show` creates the ledger when given a mistyped `--output`.
- The usage report doesn't name the resolved model (cache.py:128-143).
*Required:*
- `resolve` validates each field, and checks that the cumulative totals stay at or below 2^63−1 *before* writing. It does everything in one transaction and reports the stored status. A rejected value exits 2 and changes nothing.
- `resolve` also accepts `pending` rows when `--confirm` is given. These are rows left by a crash.
- `budget show` and `budget resolve` open the ledger read-only and exit 2 if it doesn't exist.
- The usage report includes the resolved provider model.
*Tests:* one test per item above, plus a privacy test.

**R51 — Anchor contents and boundary proposals (M, amends R22) (confirmed).**
*Problem:*
- Proposals are looked up among all blocks, not the current window (llm/__init__.py:908, 1011). The context-only lookback record can also be nominated.
- Nothing checks that the proposed text looks like a heading. A prose sentence from a block the model never saw can become a chapter title (structure.py:796).
*Required:*
- Accept only block IDs from the request's primary window.
- The proposed title must equal the block's text.
- The block must pass the shared heading classifier from R46, or be at most 12 words long and not end with sentence punctuation.
- Rejected proposals produce `LLMDecision` records (R21).
*Tests:* stubbed proposals for an out-of-window ID, the lookback context ID and a prose sentence are all rejected; a valid heading is accepted.

### 8.5 Manifest, review and packaging

**R52 — `pack-m4b` freshness (H, amends R14 and R40) (confirmed).** *Amended by R76 (§9).*
*Problem:*
- `pack-m4b` recomputes convert's audio fingerprint from config-only settings (cli.py:596-637). Audio made with CLI TTS options, batch profiles or a different `--cover` is reported as stale (exit 6).
- `pack-m4b --cover` itself always fails. No test runs convert followed by pack.
*Required:*
- Each MP3 sidecar records `chapter_id` and `text_sha256`, the SHA-256 of the chapter's narration text as rendered from the current manifest.
- `pack-m4b` checks the sidecar integrity (size and SHA-256 of the MP3), `chapter_id` and `text_sha256` against the current manifest. It does not recompute voice, TTS, speed or cover settings.
- `--cover` on `pack-m4b` applies to the M4B only.
- This needs an audio sidecar format bump (see §8.8).
*Tests:*
- convert with `--voice` and `--speed`, then pack with no options, succeeds (FFmpeg-gated).
- convert with `--cover`, then pack with a different `--cover`, succeeds, and the M4B carries the pack cover.
- Editing a chapter boundary after convert gives exit 6 naming that chapter.

**R53 — Make hand-edit protection robust (M, amends R11 and R9) (confirmed).** *Amended by R73, R75 (§9).*
*Problem:*
- When a chapter has been hand-edited, the merge pins its old boundaries even if only the title was edited (pipeline.py:518-557).
- Any boundary shift next to an edited chapter makes reanalysis fail with a generic coverage error, so a title-only edit can block reanalysis for good.
- `match.warnings = list(edited.warnings)` (pipeline.py:550) overwrites the fresh "no speakable text" warning, which bypasses the R9 gate.
- `coverage.json` decides emptiness with `.strip()` (structure.py:1139-1146) while the gate uses `has_speakable_narration`.
- An approved empty chapter passes the gate, then fails during synthesis.
- On a case-insensitive filesystem, old-MP3 cleanup can delete the file it just published (pipeline.py:933).
*Required:*
- Protect each edited *field* separately:
  - a title-only edit keeps only the title;
  - a boundary edit keeps that boundary and moves the neighbouring chapter's adjacent boundary to meet it;
  - if neither neighbour can absorb the change without becoming empty or overlapping, fail with a content-free error naming the chapter numbers and how to proceed (approve, or revert the edit).
- Warnings and review reasons are always recomputed, never copied from the old manifest.
- `coverage.json` and the gate share one emptiness check.
- An approved empty chapter is skipped with a pause-free report entry, not sent to TTS, and doesn't make the run partial.
- Cleanup compares files with `os.path.samefile` or the inode, never by path string.
*Tests:*
- A title-only edit followed by a boundary change in a neighbouring chapter reanalyses successfully.
- A boundary edit moves its neighbour.
- An impossible merge gives the content-free error.
- An edited chapter that becomes empty is gated.
- An approved empty chapter is skipped.
- A case-only rename (simulated by monkeypatching `samefile`) keeps the new MP3.

### 8.6 Privacy and CLI

**R54 — Catch-all CLI exception handling (M, amends R2) (confirmed by reading).** *Amended by R78 (§9).*
*Problem:* Commands catch only `AudiobookError`, `OSError` and `ValueError`. Typer's pretty-exception handler is left on (cli.py:20), so a `RuntimeError`, `KeyError` or `TypeError` from PyMuPDF, mutagen or kittenml prints its message, and `--json` gets no diagnostic.
*Required:*
- Create the Typer app with `pretty_exceptions_enable=False`.
- Every command routes *any* `Exception` to `fail()`, which prints "Unexpected internal error" and exits 1. `KeyboardInterrupt` exits 130 with a fixed message.
*Tests:* for `analyze`, `convert` and `config show`, a monkeypatched `RuntimeError("SECRET BOOK SENTENCE")` never appears on stdout or stderr, and `--json` gets a JSON diagnostic.

**R55 — Precise `config show` redaction (M, amends R26) (confirmed).** *Amended by R78 (§9).*
*Problem:* Substring matching on `key` and `token` masks `max_context_tokens`, `max_output_tokens`, `chunk_tokens`, cost rates and user-chosen dict keys such as pronunciations (config.py:396-419). URL fragments are never masked.
*Required:*
- Mask by an explicit allowlist of secret field paths. Today that is only the URL-valued fields' userinfo, query and fragment, and any future field marked secret in the config model (e.g. through field metadata).
- Never mask values because of their name, and never mask user-chosen dict keys.
*Tests:*
- Numeric `*_tokens` fields and cost rates are shown unmasked.
- `[tts.pronunciations] Keynes = "Kaynz"` is shown unmasked.
- userinfo, query and fragment secrets are masked, with and without `--sources`.

**R56 — Batch TTS validation (M, amends R34) (confirmed).**
*Problem:* `batch` sets TTS values with `setattr`, which pydantic doesn't validate (cli.py:564). `batch --voice Jasper` with Piper retries every chunk and exits 7.
*Required:* Build per-book settings through model validation. Invalid values exit 2 before any synthesis.
*Test:* `batch --voice Jasper` with a Piper profile exits 2, and no TTS call is made.

### 8.7 Audio and speech

**R57 — Chunk alignment survives normalization (M, amends R38) (confirmed).** *Amended by R64, R65 (§9).*
*Problem:* A whitespace-separated token made only of U+200B, U+00AD or U+FEFF normalizes to an empty string (audio:255). The word alignment then fails with "Narration chunk source alignment failed" for the whole chapter. A leading BOM is enough.
*Required:* Remove zero-width and soft-hyphen characters before tokenizing, consistently on both the source side and the spoken side of the alignment. No token can become empty after tokenizing.
*Tests:* a leading BOM, an isolated U+200B and an isolated soft hyphen all chunk and align.

**R58 — Spoken-text quality (L, amends R38 and R39).** *Amended by R64, R68 (§9).*
*Required:*
- A pronunciation key ending in `.` doesn't re-append the period when the replacement is mid-sentence. The token's own trailing sentence punctuation is kept exactly once.
- Case transfer applies only when the key is alphabetic, so `C++` doesn't become `CPLUSPLUS`.
- Trailing-punctuation stripping recognizes `...` as well as `…`, so `Hermione…` matches.
- Dashes:
  - an en dash between digits becomes " to ";
  - a figure dash (U+2012) becomes "-";
  - an em dash and any other en dash become ", ".
*Tests:* one per rule, including "10–20" read as "10 to 20".

**R59 — Temporary WAV cleanup and the size limit (M, amends R41) (confirmed).** *Amended by R77 (§9).*
*Problem:* Temporary chapter WAVs are removed only on `AudioError` (pipeline:912). An interrupt or an `OSError` leaves them, and nothing cleans them up. A WAV over 4 GiB raises `struct.error`.
*Required:*
- Remove the temporary chapter WAV in a `finally` block.
- At the start of `convert`, delete `.cache/tts/chapters/chapter-*.wav` files older than the current run.
- Before a write would cross the WAV size limit, fail that chapter with a content-free `AudioError` (exit 7 for the run).
*Tests:*
- An injected `KeyboardInterrupt` or `OSError` leaves no temporary WAV.
- A stale file is swept on the next run.
- A monkeypatched small size limit triggers the chapter error.

**R60 — Voice marker validation (L, amends R8).** *Amended by R77 (§9).*
*Problem:*
- Piper marker voices are never pre-checked, because `list_voices()` returns `[]` (tts:174).
- An exception from `list_voices` silently skips validation (pipeline:741-743).
- One bad marker aborts the whole run with a misleading message (pipeline:~721).
*Required:*
- For Piper, validate marker IDs as decimal speaker IDs below the model's `num_speakers` (from its `.onnx.json`).
- A failure to list voices is a content-free error, never a skip.
- A bad marker fails only its own chapter, with a message naming the chapter number and the reason code `invalid_voice_marker`, and the run exits 7.
*Tests:* a bad Piper ID in chapter 2 of 3 gives exit 7 with chapters 1 and 3 produced; a `list_voices` exception is reported.

**R61 — TTS retries and failure reporting (L, amends R36).** *Amended by R77 (§9).*
*Required:*
- Retry only errors the provider marks transient. Unknown voices, invalid speaker IDs and validation errors fail immediately.
- Failed chapters stay in `reports/conversion_status.json`. That is a deliberate decision: the manifest is user-owned and may be approved, so the run must not write to it. `inspect` and `inspect --json` must show the failed chapters from that file.
- Amend R36's text to say all of the above.
*Tests:* an unknown voice makes exactly one TTS call; `inspect --json` lists the failed chapters.

### 8.8 Small fixes, fingerprints and process

**R62 — Small fixes (L).** *Amended by R72, R77 (§9).*
*Required:*
- **Review UI (R15):**
  - a non-ASCII or malformed `Authorization` header on POST returns 401;
  - a `Host` without a port is accepted when bound to port 80;
  - `create_review_server` either serves IPv6 (`::1`) with the correct address family or rejects IPv6 hosts with a content-free error.
- **Logging (R31):** emit INFO events for stage progress and WARNING events for review warnings and degraded output. `command_failed` is logged at ERROR no matter which level is enabled.
- **Pauses (R37):** pause chunks appear in the chunk mapping as `kind="pause"` with their source ranges, and the conversion report counts them.
- **Analysis fingerprint:** bump it for the c5096aa change to emptiness detection. It can share the bump in §8.8's table below.
*Tests:* one per item.

**R63 — Test and process integrity (D).** *Amended by R78, R79 (§9).*
*Required:*
- **Audit test edits.** Go through every change to existing assertions or fixture inputs under `tests/` between 7eb4d25 and 2904f19, including `test_scan_text_layer_fragments.py`, `test_auto_ocr_*` and `test_ocr_cache.py`. For each one, either revert it or record a one-line reason in the FX8 ledger row.
- **Depth tests reach the depth check.** The MP3-sidecar and WAV-metadata depth tests must use a payload that fits inside each cache's size cap.
- **The R10 test uses the page's real builder.** It must post the body the page's own JavaScript builds (extract the builder, or run it), and show that an unchanged save keeps the voice.
- **`uv.lock`.** Regenerate it with the uv version CI uses, so `revision` matches what it was before c5096aa.
- **Original TODO.** Re-open the items in docs/PDF2AUDIOBOOK_TODO.md that map to wrong or partial FX items: P0.03d, P1.04c, P1.03a, P2.03a, P3.02a, P3.06, P4.02, P4.03c, F.04, F.06. Correct P4.04c's citation.
- **This TODO.** Re-open every FX item the second review marked wrong or partial (TODO FX8.01).

**Fingerprint and schema bumps for FX8.** As in §3, make each bump once:

| Bump | Covers | Effect |
| --- | --- | --- |
| Manifest `schema_version` 2 → 3 | R48 (`review_required`, acknowledgements) | v2 manifests are rejected with "re-run analyze" |
| Extraction/analysis fingerprint | R46, R47, R48, R53 (emptiness), R62 | Analysis is recomputed |
| Audio fingerprint and sidecar format | R52 (`text_sha256`), R57, R58 | Chapter audio is regenerated |

### 8.9 Second-review traceability

| Second-review finding | Requirement | FX items to re-open |
| --- | --- | --- |
| Numbered headings lost; list splitting | R46 | FX2.01c, FX2.01d |
| Folio regression; edited test; label mismatch | R47, R63 | FX2.03a, FX2.03b, FX2.01d |
| Retries fail under budget; cap dropped | R49 | FX4.02a, FX4.05a, FX4.05b |
| `pack-m4b` stale rejection; `--cover` | R52 | FX3.04a, FX3.04c, FX6.08a, FX6.08b |
| Uncaught exceptions leak | R54 | FX1.04a |
| `config show` over- and under-masking | R55 | FX1.05a, FX1.05b |
| BOM or zero-width token fails a chapter | R57 | FX6.04a |
| Boundary proposals not anchored | R51 | FX4.07a, FX4.07b |
| `budget resolve` and `show` defects; usage model | R50 | FX4.01c, FX4.04a |
| Hand-edit merge; warnings; emptiness; case-only rename | R53 | FX3.01a, FX3.03a, FX3.04b, FX3.05 |
| Page sizes misaligned; no acknowledgement; vector pages | R48 | FX2.06a, FX2.06b, FX2.04a |
| Batch skips validation | R56 | FX5.06a, FX5.07 |
| Temporary WAV leak; 4 GiB limit | R59 | FX6.09a |
| Voice markers (Piper, whole-run abort) | R60 | FX6.06a |
| Speech quality (period, case, dashes, ellipsis) | R58 | FX6.04a, FX6.05a |
| Retrying errors that can't succeed; failed-chapter visibility | R61 | FX6.07a |
| POST auth 401; port 80; IPv6 | R62 | FX1.03a |
| Logging events | R62 | FX5.08a |
| No pause entries or count | R62 | FX6.03 |
| Depth tests miss the depth path; R10 test copies the body by hand | R63 | FX0.02c, FX1.02b |
| CLI negative-flag tests cover `analyze` only | R63 (add tests for `convert` and `batch`) | FX5.05b |
| Fingerprint stage names and operational fields | R53, R62 | FX3.02a |
| Overclaimed original TODO items; lockfile revision | R63 | FX7.03, FX6.01 |

## 9. Third review (FX9)

### 9.1 Context

FX8 landed in 5c8eff7160f3f02506b7092ac75196860df6bc13 and its CI evidence in 0c198457396821434614b712faf9d8129eb497ef. At 0c19845 every local gate passes (1240 passed, 1 opt-in Kitten skip) and CI runs 40186391382 and 40186508562 succeeded. A third review of `2904f19..0c19845` then found:

- new regressions introduced by FX8 (digit ranges, Roman-letter headings, JSON on default stderr);
- requirements only partly met (R48, R49, R52, R57);
- existing tests rewritten to expect the new behaviour, against §8.2;
- new regression tests that pass against the code they were meant to catch;
- status and ledger entries that don't match git: FX8.01's re-opening never happened in any commit, two ledger rows added in 5c8eff7 carry earlier SHAs, and FX8.18 is checked on a false lockfile claim.

The review also found three places where this spec itself was at fault:

- R58's "an en dash between digits becomes ' to '" changes the token count and so contradicts R57's alignment rule. R64 resolves this.
- R62's "`command_failed` is logged at ERROR no matter which level is enabled", combined with INFO stage events and the default `general.log_level = "INFO"`, puts JSON log lines on default stderr. R72 resolves this.
- R63 asked for `uv.lock` to be regenerated "with the uv version CI uses", but `ci.yml` doesn't pin uv (`astral-sh/setup-uv@v6` installs the latest). R78 resolves this.

This section amends those requirements and adds R64–R79. File and line references point to 0c19845 and are approximate. Findings marked **(confirmed)** were reproduced by running code or checked by reading it.

### 9.2 Ground rules added for FX9

These add to §2 and §8.2; they don't replace them.

- **One fix per commit.** Each FX9 task that changes `src/` lands in its own commit, together with its regression tests. Docs-only status changes land in separate `docs:` commits.
- **Prove the regression test fails.** Before committing a fix, run its new tests against the parent commit (for example `git stash` the `src/` change, or check out the parent in a worktree) and record the failing test IDs in the ledger row. A test that passes at the parent doesn't count as a regression test.
- **Restore, don't rewrite.** The tests listed in R79 are restored to their 2904f19 text in the same commit as the fix that makes them pass. If a restored assertion is truly obsolete, delete it with a reason in the commit message and add a new, truthfully named test.
- **Test names must describe what the test asserts.** A test named `…_blocks_…` must assert that something is blocked.
- **The ledger is append-only.** A row's SHA is the commit whose state it documents, and the row is written after that commit exists. Never add a row labelled with an older SHA, and never edit an existing row; append a correction row instead.
- **Status changes happen in git.** Unchecking or re-checking an item is a commit of its own, so `git log -p` on the TODO shows every transition.

### 9.3 Text integrity and speech

**R64 — Speech rewrites keep alignment (H, amends R57 and R58) (confirmed).**
*Problem:*
- R58's rewrite of "10–20" to "10 to 20" turns one source token into three spoken tokens. The chunk alignment requires matching token counts, so "Read 10–20 pages today." and "In 1990–91 it rained." raise "Narration chunk source alignment failed" and the whole chapter fails (audio/__init__.py:137).
- An em dash becomes ",", giving "pause,then" with no space.
*Required:*
- Alignment works on source token spans, not on equal token counts. Every spoken-side rewrite records which source token (or span) it came from, so a rewrite may change the number of tokens without breaking alignment. Alternatively, apply token-count-changing rewrites after the source ranges have been computed. Either way the rule is: no R58 rewrite can fail alignment.
- An em dash, and an en dash not between digits, become ", " with exactly one following space, and no space before the comma.
- An alignment failure stays a content-free chapter error (never silently dropped text), but no valid R58 input may trigger it.
*Tests (new):* "Read 10–20 pages today.", "In 1990–91 it rained.", "pp. 3–4.", "wait—then" spoken as "wait, then", "wait — then", and a property-style test that runs every R58 rule through `chunk_source_ranges` on generated sentences.

**R65 — Isolated invisible characters (M, amends R57) (confirmed).**
*Problem:* FX8 only strips invisible characters inside a word. A whitespace-separated token made only of U+FEFF, U+200B, U+200C, U+200D, U+2060 or U+00AD still normalizes to empty, and "﻿ Hello there world." and "Hello ​ world." fail alignment. The R57 test covers only the in-word case and passes at 2904f19.
*Required:* Remove those characters before tokenizing, on both the source and spoken sides, so no token can be empty. A token that becomes empty is dropped from both sides together.
*Tests (new):* a leading BOM followed by a space, an isolated U+200B, U+2060 and U+00AD, and a chapter made only of such a token plus one word. Each test must fail at 0c19845.

**R66 — Roman-letter headings (H, amends R46) (confirmed).**
*Problem:* The Roman-title pattern `[IVXLCDM]{1,8}[.)]\s+[A-Z][A-Z\s'’:-]{2,80}` (structure.py:209) accepts any one Roman-numeral letter. Epigraph attributions such as "C. DICKENS", "M. LEBLANC", "D. H. LAWRENCE" and "L. FRANK BAUM" become chapter headings and split the book.
*Required:* A single-letter numeral ("C.", "D.", "L.", "M.", "V.", "X.") counts as a Roman heading only when the book also has a sequence of at least two consecutive Roman headings that includes it, or when its block passes the font-size or whitespace heading test. Numerals of two or more letters keep the current rule.
*Tests (new):* each attribution above stays body text; "I. THE STORM / II. … / III. …" still gives 3 chapters; "IV. … / V. … / VI. …" keeps "V." as a heading.

**R67 — Wrapped lines and list ends (L, completes R46).**
*Problem:* A wrapped line that starts with "J. Smith" or "1990)" still splits a paragraph (structure.py:1476), because the join check uses the old list pattern. The last item of a list swallows the paragraph that follows it.
*Required:* The join check uses the same sequential-marker rule as classification (R46). A list ends at a blank line, a font change or a line that isn't indented like its items.
*Tests (new):* "…reported by\nJ. Smith of the Times." joins; "…from 1985 to\n1990) was…" joins; a two-item list followed by a body paragraph keeps the paragraph separate.

**R68 — Remaining speech rules (L, completes R58).**
*Problem:* `Dr.` is still spoken as "Doctor." mid-sentence and `U.S.` as "USA." (the period rule isn't implemented). "Hermione..." gains an extra period.
*Required:* As R58: a key ending in `.` doesn't re-append its period mid-sentence, and the token's own sentence-ending punctuation is kept exactly once. `...` and `…` are stripped and restored identically.
*Tests (new):* "Dr. Watson arrived.", "the U.S. army", "the U.S.", "Hermione...", "Hermione…".

### 9.4 Extraction

**R69 — OCR for vector-outlined text (H, amends R48) (confirmed).**
*Problem:* A full page of text drawn as outlines covers 0.143 of the page area, which is under the hard-coded 0.15 threshold (pdf.py:714). It isn't OCRed and still gets the "no readable text (OCR not needed)" warning. The FX8 fixture is a grid of rectangles at about 17% coverage, so it never tested a real outlined page.
*Required:*
- In `--ocr auto`, an image-free page with no usable text is OCRed when its drawings look like glyphs: at least a configured number of small filled paths (defaulting to a value that a single outlined text line exceeds), or drawing coverage above a lower threshold. Name the constants and document them in MAINTAINER_GUIDE.md.
- Never say "OCR not needed" for a page with no readable text. A page that isn't OCRed gets a warning that says why (OCR disabled, or no drawings) and sets the `damaged_source` review reason only when the page has drawings.
*Tests (new):* a fixture of real outlined glyphs (made with Ghostscript `-dNoOutputFonts`, or by drawing glyph paths, and committed as a small binary) whose coverage is below 0.15 is OCRed (Tesseract-gated); a page with one horizontal rule isn't. Check the skip summary in CI shows the Tesseract test ran.

### 9.5 LLM budget

**R70 — Budget accounting fails closed (H, amends R49) (confirmed).**
*Problem:*
- If a provider rejects `max_tokens` and then `max_completion_tokens`, the second is popped and the request is sent with no output cap, even under a token or USD budget (llm/__init__.py:506-512).
- Legacy `unknown` or `pending` rows with no recorded bound count as `upper_tokens or 0` (llm/budget.py:109), and `reserve` defaults `upper_bound_tokens` to 0 (llm/budget.py:216). Old unresolved attempts therefore count as free. `test_llm_budget_integer_bounds.py:30` was rewritten to assert exactly that.
- After retries run out, a 429 falls into the "4xx other than 408" branch and is settled `rejected` with zero tokens. R49 says 429 stays `unknown`.
- `rejected` is signalled by putting `{"rejected": True}` into the provider's `usage` dict, mixing control flow with reported data.
- The image part of the upper bound is based on compressed PNG bytes, which isn't conservative.
*Required:*
- Under a token or USD budget, never send a request without an output cap. When both cap parameters are rejected, settle the attempt `rejected` and fail with a content-free error saying the provider doesn't accept an output cap.
- `reserve` has no zero default. Decision recorded in FX9.02: its bound parameter is `None` by default, which stores the row as unbounded; existing tests reserve without a bound, so the parameter is not made mandatory. Production callers (`cache.py`) always pass a bound. An `unknown` or `pending` row without a bound blocks new requests under a token or USD budget, as before R49, with a message pointing to `budget resolve`.
- `rejected` applies only to 4xx responses other than 408 and 429. A 429 after the last retry stays `unknown`.
- Settlement takes a typed outcome (`completed`, `unknown`, `rejected`) separate from usage.
- The image bound comes from decoded pixel dimensions using the most expensive tile rule among supported providers, and is never less than the encoded request's UTF-8 byte length.
*Tests:* restore the tests listed in R79 for the budget; add a "both cap parameters rejected under a budget" test, a legacy-NULL-bound test, a 429-exhaustion test, and an image-bound test with a small PNG of a large image.

**R71 — `budget resolve` can't break the ledger (M, amends R50) (confirmed).**
*Problem:* The cumulative check in `resolve_unknown` ignores the upper bounds of other open rows. Resolving huge values succeeds, after which the stored sums overflow, `budget show` fails and every LLM run fails.
*Required:* Before writing, check that every stored total (including all other rows' actual usage and open rows' upper bounds) stays within SQLite's 64-bit integer range and the `Decimal` limits used for costs. On failure exit 2 and change nothing. Anything `resolve` accepts, `show` can display.
*Tests (new):* resolving a value that would overflow with another open row present exits 2, leaves the row unchanged, and `budget show` still works.

### 9.6 Manifest, review and packaging

**R72 — Clean stderr (M, amends R62 and R31) (confirmed).**
*Problem:* With the default `general.log_level = "INFO"`, R62's INFO stage events and ERROR `command_failed` event print JSON lines to stderr before "Error: …". In `--json` mode stderr holds several JSON objects. The 2904f19 assertions `json.loads(captured.err)` and `not result.stderr.lstrip().startswith("{")` (tests/test_cli_json_errors.py) were changed to `splitlines()[-1]` and removed. R62's wording caused this.
*Required:*
- In human mode, log events are rendered as human-readable lines, never JSON. Default human-mode stderr for a failed command starts with "Error:".
- In `--json` mode, stderr contains exactly one JSON value for a failed command unless `--verbose` is given. Structured events are emitted only with `--verbose` or an explicitly configured `general.log_level`.
- `command_failed` uses the ERROR level, but is printed only when logging output is enabled as above.
*Tests:* restore the 2904f19 assertions in `tests/test_cli_json_errors.py` unchanged; add a test that `--verbose` emits the structured events.

**R73 — Review gate uses current state (M, amends R48 and R53) (confirmed).**
*Problem:*
- The empty-chapter gate reads `review_required` as computed at analysis time. A chapter emptied later by a hand edit is neither gated nor skipped.
- Any review-UI save, even title-only, adds `damaged_source` to `review_acknowledged` and removes it from `review_required` (review_ui.py:146-149).
*Required:*
- `convert` recomputes the review reasons from the current manifest with the same emptiness function used by analysis and `coverage.json`, before gating.
- The review UI clears `damaged_source` only when the user ticks an explicit "I have checked the damaged pages" control. A plain save never acknowledges a reason.
*Tests (new):* hand-empty a chapter after analysis, then convert is gated; a title-only save keeps `damaged_source`; the acknowledgement control clears it.

**R74 — `--accept-review` behaviour (M, amends R48) (confirmed).**
*Problem:* It writes no log event, an unknown reason exits 6 only after a full analysis, and `--dry-run` ignores it.
*Required:* Validate reasons at option parsing (exit 2 before any work). Emit a content-free `review_acknowledged` event with the reason codes. `--dry-run` applies it and reports which reasons would be acknowledged.
*Tests (new):* unknown reason exits 2 with no workspace changes; the event is logged; dry-run with and without the flag.

**R75 — Match hand edits by chapter identity (M, amends R53).**
*Problem:* Hand-edited chapters are matched to reanalysed ones by chapter number. When reanalysis changes the chapter count, an edit lands on the wrong chapter.
*Required:* Match by chapter `id` and `generated_fingerprint`. An edit with no match is a content-free conflict error naming the old chapter number; it is never applied to another chapter.
*Tests (new):* reanalysis that inserts a chapter before an edited one keeps the edit on the right chapter; a removed chapter with an edit raises the conflict.

**R76 — `pack-m4b` hashes manifest-rendered text (H, amends R52) (confirmed).**
*Problem:* `pack-m4b` hashes `chapters/NNN.txt` as it is on disk (cli.py:699-708), not text rendered from the current manifest. After a hand edit of the manifest's boundaries without re-rendering, `pack-m4b` exits 0 and packages stale audio. The FX8 test re-renders the chapter files itself, so it can't catch this.
*Required:* `pack-m4b` renders each chapter's narration text in memory from the current manifest, with the same function `convert` uses, and compares its SHA-256 with the sidecar. It doesn't read `chapters/*.txt`.
*Tests (new):* edit a boundary in `manifest.json` only, then `pack-m4b` exits 6 naming the chapter; the test must not call `render_chapter_texts`.

### 9.7 Audio, TTS and CLI

**R77 — Run-scoped WAV cleanup, retries and resume counts (M/L, amends R59, R60, R61 and R62).**
*Problem:*
- The start-of-convert sweep deletes every `chapter-*.wav` older than the run, including one a concurrent `convert` on the same workspace is writing.
- No real TTS provider marks any error transient, so `tts.max_retries` never retries.
- A misplaced voice marker still aborts the whole run instead of failing its own chapter.
- `pause_count` is 0 on resumed runs.
*Required:*
- `convert` takes an exclusive workspace lock; a second `convert` exits with a content-free error. The sweep runs only while holding the lock.
- Each provider adapter maps its documented transient failures (timeouts, connection resets, HTTP 429 and 5xx for remote providers) to transient errors. MAINTAINER_GUIDE.md lists providers that have none.
- A bad voice marker fails only its chapter (exit 7, reason `invalid_voice_marker`). Piper's speaker-count check stays deferred with FX8.14c.
- The conversion report counts pauses from the chunk mapping, including resumed chapters.
*Tests (new):* concurrent convert is refused and the other run's WAV survives; a fake provider's transient error is retried; a misplaced marker fails one chapter; a resumed run reports the same `pause_count`.

**R78 — CLI error mapping and small fixes (L, amends R54, R55 and R63).**
*Problem:*
- The catch-all maps `OSError` and `ValueError` to "Unexpected internal error", losing useful content-free messages such as "port in use" for `review`. The original mapping test was rewritten.
- Stopping `review` with Ctrl+C exits 130.
- `_SECRET_CONFIG_PATHS = {"pdf.password"}` (config.py:391) names a field that doesn't exist.
- `ci.yml` doesn't pin uv, so R63's lockfile requirement can't be met as written. `uv.lock` revision went from 5 to 3 in c5096aa, and FX8.18 claims it was 3 before.
- The restored folio-test comment says "appear on page"; the original says "appear as page".
*Required:*
- Known `OSError` cases keep their content-free messages ("A filesystem operation failed", "Review server port is unavailable"); only unknown exceptions say "Unexpected internal error".
- Ctrl+C on `review` is a normal shutdown: exit 0 with a fixed message.
- Secret fields are marked on the config model (for example `json_schema_extra={"secret": True}`); `_SECRET_CONFIG_PATHS` is derived from the model, and a test checks every listed path exists.
- Pin uv in `ci.yml` (`with: version:`), regenerate `uv.lock` with that version, and record the resulting revision and the decision in the ledger. Don't claim it matches an earlier revision unless `git show` proves it.
- Restore the comment text exactly.
*Tests:* restore the 2904f19 error-mapping parametrization; add a `review` port-in-use test and a Ctrl+C test.

### 9.8 Test and process integrity

**R79 — Restore tests and correct the record (D) (confirmed).**
*Required:*
- **Restore rewritten tests** to their 2904f19 text, each in the commit of the fix that makes it pass:
  - `tests/test_llm_budget_integer_bounds.py` (the assertion that an `unknown` row costs 0 tokens is removed);
  - `test_overspent_token_budget_still_fails_closed` and the exact-exhaustion test in `tests/test_llm_exact_budget_boundary.py`;
  - `tests/test_llm_budget_settlement_types.py`: tests named `…_blocks_…` assert that a request is blocked, or are renamed with a reason;
  - `tests/test_cli_json_errors.py` (R72, R78);
  - the page-number tests from before FX2 whose expectations FX8 inverted;
  - every other file the FX8.02b re-audit (below) lists.
- **Re-audit with one line per change.** For every changed assertion or fixture input under `tests/` between 2904f19 and 0c19845, append one ledger row line (file, test, old → new, reason). Category reasons aren't enough.
- **Regression tests must catch their bug.** Replace FX8's R46 chapter test, R47 folio test and R57 test with versions that fail at 2904f19. The MP3-sidecar and WAV-metadata depth tests must use nested dicts that reach the depth check and fail with the check disabled. The R10 test runs the page's own JavaScript (with Node when available, skipped otherwise) and also statically checks that the request builder in `_HTML` sends `voice_id`.
- **Correct the status record**, in a docs commit before any FX9 fix:
  - Uncheck the FX8 items found wrong or partial (TODO FX9.00a) and their parents.
  - Uncheck FX8.19a, and original-TODO F.06 while its deferred dependencies are open.
  - Append a correction row to the ledger saying the rows labelled `2904f19` (FX8.01) and "a176375 (review baseline source)" were written in 5c8eff7, the FX8.01 re-opening never happened in git, and FX8.18's lockfile claim is false. Don't edit or delete those rows.

### 9.9 Fingerprint bumps for FX9

Make each bump once, as in §3:

| Bump | Covers | Effect |
| --- | --- | --- |
| Extraction/analysis fingerprint | R66, R67, R69 | Analysis is recomputed |
| Audio fingerprint | R64, R65, R68 | Chapter audio is regenerated |
| Budget ledger | R70 (`reserve` requires a bound; typed outcome) | No schema change; legacy NULL-bound rows block until resolved |

No manifest schema change is needed: `review_required` and `review_acknowledged` already exist in v3.

### 9.10 Third-review traceability

| Third-review finding | Requirement | FX8 items to re-open |
| --- | --- | --- |
| Digit ranges and em-dash spacing fail alignment | R64 | FX8.13b, FX8.13c |
| Isolated invisible characters | R65 | FX8.13a, FX8.02c |
| "C. DICKENS" headings | R66 | FX8.04a, FX8.04b |
| "J. Smith"/"1990)" joins; list end | R67 | FX8.04a |
| `Dr.`/`U.S.`/`...` speech rules | R68 | FX8.13b |
| Vector-outlined text not OCRed | R69 | FX8.06c, FX8.06d |
| Uncapped request; legacy rows free; 429 `rejected`; image bound | R70 | FX8.08a, FX8.08b, FX8.08c |
| `budget resolve` overflow | R71 | FX8.09a, FX8.09c |
| JSON on default stderr; test rewritten | R72 | FX8.15b, FX8.15d, FX8.03a |
| Stale review gate; UI auto-acknowledge | R73 | FX8.06b, FX8.12b |
| `--accept-review` log, parse-time check, dry-run | R74 | FX8.06b, FX8.06d |
| Edits matched by number | R75 | FX8.12a, FX8.12c |
| `pack-m4b` hashes on-disk text | R76 | FX8.11a, FX8.11b |
| WAV sweep race; no transient errors; marker abort; `pause_count` | R77 | FX8.14b, FX8.14d, FX8.15c |
| `OSError` mapping; Ctrl+C; secret paths; uv pin; comment | R78 | FX8.03b, FX8.18, FX8.02a |
| Rewritten tests; weak regression tests; status and ledger | R79 | FX8.01, FX8.02b, FX8.16a, FX8.16b, FX8.19a |
