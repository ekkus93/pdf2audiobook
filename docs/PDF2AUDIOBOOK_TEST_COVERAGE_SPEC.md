# PDF2Audiobook — Test Coverage Specification

**Status:** Draft; T1–T9 not implemented
**Date:** 2026-11-13
**Baseline:** master at 7ca1b3907f965372fd5ebb80ee88755fb2278bf8
**Parent specification:** `docs/PDF2AUDIOBOOK_SPEC.md` (§12 engineering principles)
**Companion:** `docs/PDF2AUDIOBOOK_TEST_COVERAGE_TODO.md`

## 1. Purpose and scope

A branch-coverage run at the baseline reported 93% overall (8,217 statements, 2,942 branches; 2060 passed, 1 skipped). The gaps cluster in a few modules, and several of them are fail-closed, crash-recovery or privacy paths: code that exists precisely to refuse bad input and that no test has ever run.

This work adds tests for those paths. **It is tests only: no source change.** If a test shows that the code is wrong, record it (§5) for a separate fix and mark the test `xfail(strict=True)` with the recorded reason.

| ID | Module | Branch coverage at baseline | What is untested |
| --- | --- | --- | --- |
| T1 | `src/pdf2audiobook/llm/budget.py` | 87% | Settlement rollback, `resolve_unknown` validation, double settlement, schema handling |
| T2 | `src/pdf2audiobook/llm/vision.py` | 61% | `_has_visual_content`, which decides which page images go to a remote vision model |
| T3 | `src/pdf2audiobook/review_transaction.py` | 86% | Rejecting invalid or tampered journals, blocked recovery, size and race guards |
| T4 | `src/pdf2audiobook/audio/progress.py` | 82% | About 15 fail-closed rejections in `read_synthesis_progress` |
| T5 | `src/pdf2audiobook/audio/encoding.py` | 78% | Input validation, missing FFmpeg, M4B packaging failures, zero-duration MP3 |
| T6 | `src/pdf2audiobook/tts/selection.py`, `document/listing.py`, `pdf_ocr.py` | 84%, 77%, 87% | Model identity fallbacks, TTS profile branches, list-marker rules, OCR error branches |

T7–T9 are cross-cutting (§4).

**Out of scope:** changing any source file; adding `coverage` or `pytest-cov` as a project dependency; a coverage threshold in CI; tests that need the network, a live LLM or the real Kitten model.

## 2. Ground rules

- **Tests only.** No file under `src/` changes. Bugs found go to §5.
- **Assert behaviour, not lines.** Each test asserts the observable outcome: the exception type and its fixed message, the returned value, the ledger rows, or the files left on disk. Executing a line is not enough.
- **Privacy.** Every new error-path test also asserts that the message holds no path, file name, book text or OS error text, matching the existing `tests/test_*_privacy.py` style.
- **Offline and deterministic.** No sleeps or timing races. Simulate failures with `monkeypatch` or hand-written fixture files. Tests that need `ffmpeg` or `tesseract` use the existing skip markers, and the evidence states whether they ran.
- **Extend before adding.** Put tests in the existing file for that module when one exists (§3). New files follow `tests/test_<area>_<topic>.py`.
- **One area per commit:** `test(<scope>): cover <area>`. Each commit passes `/verify` and mypy on 3.11, 3.12 and 3.13.

## 3. Requirements

### T1 — Budget ledger (`llm/budget.py`)

Existing tests: `tests/test_llm_book_budget_ledger.py`, `tests/test_llm_budget_fail_closed.py`, `tests/test_llm_budget_resolve_overflow.py` and related `test_llm_budget_*` files.

- **T1.a Settlement rollback** (lines 377–384): settling a verified call whose totals would make the ledger statistics fail leaves that row `unknown` with its token and cost columns null. Other rows are unchanged.
- **T1.b `resolve_unknown` validation** (lines 443, 448, 461, 472): invalid counts, a total below prompt plus completion, a cumulative total above the supported range, and invalid prices each raise their fixed `LLMError` and leave the row unchanged.
- **T1.c Double settlement** (lines 323, 374, 406): settling, rejecting or marking unbilled a call that is already settled, or doesn't exist, raises "LLM ledger request was already settled or missing" and changes no row.
- **T1.d Schema handling** (lines 29–30, 49, 65–67, 228, 253): an unsupported `user_version` is refused; a version-1 or version-2 ledger without the upper-bound columns is migrated to version 3 with its rows intact; an unreadable ledger raises "Cannot access per-book LLM budget ledger".
- **T1.e Unreachable code**: line 52 (a repeated version check) and line 300 (`lastrowid` is `None`) look unreachable. Show it or record why not, in §5; don't test them through mocks of `sqlite3`.

### T2 — Vision page selection (`llm/vision.py`)

Existing tests: `tests/test_llm_vision.py`.

- **T2.a** `_has_visual_content` returns True for a page with an image, for a page with three or more drawings, and for a two-column page (at least two text blocks on each side of the centre line). It returns False for a single-column text page and for a page with two drawings.
- **T2.b** Each of its three `try` blocks falls back safely when PyMuPDF raises: an image-inventory error moves on to the drawings check, a drawings error moves on to the column check, and a column-check error returns False.
- **T2.c** Malformed text blocks (non-numeric or non-finite coordinates, fewer than five fields) are ignored, not counted.
- **T2.d** `review_visual_pages` sends no page image for pages where `_has_visual_content` is False (lines 96–155), checked with a recording provider.

### T3 — Review transactions (`review_transaction.py`)

Existing tests: `tests/test_review_save_outcomes.py`, `tests/test_chapter_recovery_commands.py`, `tests/test_pending_recovery_privacy.py` and others that call `recover_review_transaction`.

- **T3.a Invalid journals** (lines 67, 72, 101, 114, 121–126, 134, 173, 176): a journal with an unsafe target (absolute, `..`, outside the workspace), bad base64, a wrong type or missing field, or non-JSON content is refused with the fixed content-free message, and no workspace file changes.
- **T3.b Blocked recovery** (line 154): a target that changed since the journal was written blocks recovery and names only the safe label, unless `back_up_changed=True`, which backs it up and restores it (cover both).
- **T3.c Guards** (lines 202, 229, 255, 261): a non-manifest workspace, metadata that changes during planning, a transaction over the size limit, and a pending journal each raise their fixed error.

### T4 — Progress reader (`audio/progress.py`)

Existing tests: `tests/test_tts_progress.py`, `tests/test_audio_cache_bounded_io.py`.

- **T4.a** One parametrized test covers every rejection in `read_synthesis_progress` (lines 113–183): an over-long record, a line without a newline, too many records, a non-object or over-depth record, a duplicate header, a chunk without a mapping, a duplicate chunk number, an update for an unknown chunk, an invalid update status, `completed_chunks` before the header, a status before the header, an invalid status, an unknown event, malformed JSON, and no header at all. Each case returns `None` and emits the one "progress unavailable" warning.
- **T4.b** Lines 46 and 56–57 (the writer side) are covered or recorded in §5.

### T5 — Encoding (`audio/encoding.py`)

Existing tests: `tests/test_m4b_packaging.py`, `tests/test_mp3_output_failures.py`, `tests/test_long_chapter_wav_streaming.py`, `tests/test_cover_art.py`.

- **T5.a Input validation** (lines 33–41): a sample rate that isn't an integer from 8000 to 192000, a non-mono buffer, a buffer that can't be converted, and empty or non-finite samples each raise their fixed `AudioError` before FFmpeg runs and leave no temporary WAV.
- **T5.b Missing FFmpeg** (lines 125, 232): `encode_mp3` and `encode_m4b` raise "FFmpeg executable not found in PATH" and write nothing.
- **T5.c M4B failures** (lines 234–272, 322–351): no chapters, an invalid chapter duration, a non-zero FFmpeg exit (the message gives only the exit status), an FFmpeg timeout, and empty or invalid MP4 audio each raise their fixed error and leave no partial output.
- **T5.d MP3 checks** (lines 69–75, 176, 195–197): a temporary WAV with the wrong settings, an encoded MP3 with zero duration, and an MP3 without an ID3 tag (the `add_tags` branch).

### T6 — Lower priority

- **T6.a `tts/selection.py`**: `_tts_model_identity` for Piper with no model path (line 28), a missing model or config file (lines 35–36) and Kitten not installed (lines 43–44); each gives a stable identity that differs from the normal one. `settings_for_book_tts` applies a profile's voice and speed to Piper (lines 60, 67, 72), and an explicit command-line option overrides the profile.
- **T6.b `document/listing.py`**: the three-digit `123)` rule (line 25), and sequential markers for letters, bullets and Roman numerals (lines 32–37), through `is_list_line`.
- **T6.c `pdf_ocr.py`**: the Tesseract version fallbacks (lines 204, 213–217), the OCR cache refusing a missing source hash (line 318), the language-listing failure (lines 417, 426–429), and the raster and vector heuristics' early returns (lines 98–144, 172–192). Skip any that need a real Tesseract when it is absent, and say so.

## 4. Cross-cutting requirements

- **T7 Mutation proof.** For every requirement, break the code it covers in place (one deliberate change, such as removing a check, inverting a condition or changing a message), run the new tests with `PYTHONDONTWRITEBYTECODE=1`, confirm at least one fails for the expected reason, and restore the file byte for byte (`cmp`). Record each break and its result in the TODO.
- **T8 Coverage evidence.** Measure before and after with `COVERAGE_FILE=<scratchpad>/.coverage uv run --extra dev --with coverage coverage run --branch --source=src/pdf2audiobook -m pytest -q` and `coverage report`. Record each module's branch coverage. Targets: T1–T5 modules at least 95%, T6 modules at least 92%, except lines §5 records as unreachable.
- **T9 No regressions.** The full suite, the golden snapshot and the patch-target guard pass unchanged; no existing test is edited except to add cases.

## 5. Found while testing

Record each bug or unreachable line with `file:line`, a concrete scenario and the test (if any) marked `xfail(strict=True)`. Fixes are a separate round.

## 6. Acceptance criteria

- Every requirement in §3 has a named test and a recorded mutation result (T7).
- The coverage targets in T8 are met, or each shortfall is listed in §5.
- `/verify` and exact-head CI pass for every commit.
