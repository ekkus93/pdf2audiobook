# PDF2Audiobook — Test Coverage TODO

**Status:** Open; no task started
**Date:** 2026-11-13
**Baseline:** master at 7ca1b3907f965372fd5ebb80ee88755fb2278bf8
**Specification:** `docs/PDF2AUDIOBOOK_TEST_COVERAGE_SPEC.md` (T1–T9)

## Working rules

- Work in the order below. Use `[x]` only when the tests exist, pass, and have a recorded mutation result (spec T7). Check a parent only when all its subitems are checked.
- Tests only: no file under `src/` changes. A test that exposes a bug is marked `xfail(strict=True)` and the bug goes in "Found while testing".
- Every error-path test asserts the fixed message and that no path, file name, book text or OS error text leaks.
- One area per commit: `test(<scope>): cover <area>`, no body, no `Co-Authored-By` trailer. Run `/verify` and mypy on 3.12 and 3.13 before each commit.
- After CI finishes, add a ledger row in a separate `docs:` commit with the full SHA and the real run ID, to this file and to `docs/PDF2AUDIOBOOK_TODO.md`. The ledgers are append-only.

## Phase TC0 — Baseline

- [ ] TC0.01 Run the T8 coverage command at the baseline and record each target module's statement and branch coverage in the ledger.

## Phase TC1 — Budget ledger (T1)

- [ ] TC1.01 T1.a: settlement rollback leaves the row `unknown` with null counts; other rows unchanged.
- [ ] TC1.02 T1.b: each `resolve_unknown` validation error, with the row unchanged.
- [ ] TC1.03 T1.c: double settlement through `settle`, `settle(rejected=True)` and `settle_unbilled`, and a missing call ID.
- [ ] TC1.04 T1.d: unsupported schema version, migration from versions 1 and 2, unreadable ledger.
- [ ] TC1.05 T1.e: show lines 52 and 300 are unreachable, or record why not, in "Found while testing".
- [ ] TC1.06 T7 mutation results for TC1.01–TC1.04.

## Phase TC2 — Vision page selection (T2)

- [ ] TC2.01 T2.a: true for an image, three or more drawings and two columns; false for one column and for two drawings.
- [ ] TC2.02 T2.b: each `try` block's fallback when PyMuPDF raises.
- [ ] TC2.03 T2.c: malformed text blocks are ignored.
- [ ] TC2.04 T2.d: `review_visual_pages` sends no image for a page without visual content.
- [ ] TC2.05 T7 mutation results for TC2.01–TC2.04.

## Phase TC3 — Review transactions (T3)

- [ ] TC3.01 T3.a: each invalid-journal case is refused with the fixed message and no workspace change.
- [ ] TC3.02 T3.b: a changed target blocks recovery; `back_up_changed=True` backs it up and restores it.
- [ ] TC3.03 T3.c: non-manifest workspace, metadata changed during planning, size limit, pending journal.
- [ ] TC3.04 T7 mutation results for TC3.01–TC3.03.

## Phase TC4 — Progress reader (T4)

- [ ] TC4.01 T4.a: one parametrized test covering every `read_synthesis_progress` rejection; each returns `None` with one warning.
- [ ] TC4.02 T4.b: writer-side lines 46 and 56–57 covered or recorded.
- [ ] TC4.03 T7 mutation results for TC4.01–TC4.02.

## Phase TC5 — Encoding (T5)

- [ ] TC5.01 T5.a: sample-rate, shape, conversion and empty or non-finite input errors, with no temporary WAV left.
- [ ] TC5.02 T5.b: missing FFmpeg for `encode_mp3` and `encode_m4b`.
- [ ] TC5.03 T5.c: M4B failures: no chapters, invalid duration, non-zero exit, timeout, empty or invalid MP4 audio.
- [ ] TC5.04 T5.d: wrong WAV settings, zero-duration MP3, MP3 without an ID3 tag.
- [ ] TC5.05 T7 mutation results for TC5.01–TC5.04; state whether the FFmpeg-gated tests ran.

## Phase TC6 — Lower priority (T6)

- [ ] TC6.01 T6.a: `_tts_model_identity` fallbacks and Piper profile branches in `settings_for_book_tts`.
- [ ] TC6.02 T6.b: list-marker rules in `document/listing.py`.
- [ ] TC6.03 T6.c: OCR error branches and heuristic early returns in `pdf_ocr.py`; state whether the Tesseract-gated tests ran.
- [ ] TC6.04 T7 mutation results for TC6.01–TC6.03.

## Phase TC7 — Closure

- [ ] TC7.01 T8: rerun coverage; record each module's branch coverage against its target, and list any shortfall in "Found while testing".
- [ ] TC7.02 T9: the full suite, golden snapshot and patch-target guard pass; no existing test edited except to add cases.
- [ ] TC7.03 Final gate: `/verify` passes with mypy on 3.11, 3.12 and 3.13; exact-head CI passes for every commit; "Found while testing" is reviewed with the user.

## Found while testing

None yet.

## Progress ledger

| Date | Commit SHA | Completed tasks | Tests/CI evidence | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-13 | Not committed | Spec and TODO drafted; no work started. Baseline branch coverage: 93% overall; `llm/vision.py` 61%, `document/listing.py` 77%, `audio/encoding.py` 78%, `audio/progress.py` 82%, `tts/selection.py` 84%, `review_transaction.py` 86%, `llm/budget.py` 87%, `pdf_ocr.py` 87% | Coverage run at 7ca1b3907f965372fd5ebb80ee88755fb2278bf8: 2060 passed, 1 skipped | None |
