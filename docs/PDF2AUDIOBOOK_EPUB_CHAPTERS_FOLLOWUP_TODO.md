# PDF2Audiobook EPUB Chapter Detection Follow-up TODO

**Status:** Complete; unresolved limitations are listed below
**Date:** 2026-10-27
**Baseline:** master at 792b822
**Specification:** `docs/PDF2AUDIOBOOK_EPUB_CHAPTERS_FOLLOWUP_SPEC.md` (F1–F5)
**Previous TODO:** `docs/PDF2AUDIOBOOK_EPUB_CHAPTERS_TODO.md`

## Working rules

- Work in the order below. Use `[x]` only when the implementation exists and its named tests pass; check a parent only when all of its subitems are checked.
- Every fix task has three parts:
  - (a) add the regression tests, run them against the parent commit, and record the failing test IDs in the ledger;
  - (b) make the fix;
  - (c) run `/verify`.
- A task marked **refactor** instead proves there is no behavior change: the full suite passes unchanged.
- One fix per commit, with its tests. Conventional Commits with a scope, lowercase imperative subject. Docs-only status changes go in their own `docs:` commits.
- Never change an existing test's inputs or expected results to make a change pass, except where the spec names the change (F4, and the fingerprint pin in section 6); state the reason in the commit message.
- Every new warning path stays content-free. Fixtures are synthetic; never commit the real EPUB. CI stays offline.

## 1. Inferred offset for numeral anchors (F1)

- [x] 1.1 Tests: a synthetic book with two exact-title headings, a constant outline page offset and numeral chapter openings. Every chapter anchors at its numeral on the shifted page, with the alignment warning and confidence 0.85. With no inferred offset, behavior is unchanged.
- [x] 1.2 Try the numeral rule on `page_index + inferred_offset` after the raw page, never on a listing page. Record the existing alignment warning when the shifted page is used.

## 2. No per-entry rescans (F2) — refactor

- [x] 2.1 Test: count block iterations with a counting list subclass. With 200 numbered outline entries, `propose_chapters` stays within a small constant number of passes over the blocks.
- [x] 2.2 Build the `title_key → indices` map and move `first_on_page` before the outline loop. Use both inside the loop.
- [x] 2.3 Confirm the full suite passes unchanged, so anchors and order are identical.

## 3. Font-size gate with corroborated numerals (F3)

- [x] 3.1 Tests: no outline, a printed contents list, numeral chapters and one large-type prose line in the body. That line is not a chapter, and the "Ignored … font-size-only" warning is recorded. Without numerals, behavior is unchanged.
- [x] 3.2 Add `or len(numeral_titles) >= 3` to the weak-candidate gate.

## 4. Warning summary wording (F4)

- [x] 4.1 Tests:
  - a counted `review_warning` prints "Analysis recorded N warnings; see warnings in manifest.json", or "1 warning" for a single one;
  - the uncounted empty-chapter path keeps "Book review is required before conversion";
  - `--json` still lists `review_warning` once, with stderr empty.
- [x] 4.2 Change the counted description in `logging._dispatch`. Update the wording assertion in `tests/test_warning_noise.py`, with the reason in the commit message.

## 5. EPUB3 nav outlines (F5)

- [x] 5.1 Add `outline="ncx" | "nav" | None` to `tests/epub_book.py`, keeping the boolean values working. Confirm with PyMuPDF that the nav outline's titles and pages match.
- [x] 5.2 Parametrize the E1 anchoring and E2 contents-label tests over `ncx` and `nav`. If PyMuPDF cannot read a nav-only outline, record the limitation in the ledger and in the README's EPUB note instead.

## 6. Identity and docs

- [x] 6.1 Bump `chapter-detection-v3` to `chapter-detection-v4` (F1 and F3 change plans). Update the pin in `tests/test_fingerprint_bumps_fx9.py` and the upgrade note in `docs/MAINTAINER_GUIDE.md`.
- [x] 6.2 Document F1 and F3 in §5 of `docs/PDF2AUDIOBOOK_SPEC.md`, and the F4 wording in the README's "Watching a long run" section if it quotes the line.

## 7. Finish

- [x] 7.1 Run `/verify`, plus mypy on Python 3.12 and 3.13. Record the pass and skip counts.
- [x] 7.2 Re-check the local *Spring Snow* EPUB, never committed, and record counts only. Expect:
  - 57 chapters, with all 55 numbered chapters at their numeral;
  - `review_required` empty;
  - LLM cache hits only;
  - the new one-line summary.
- [x] 7.3 Review the final diff against F1–F5 and record any unresolved limitations.

## Unresolved limitations

- The alignment warning that numeral anchoring on a shifted page reuses says "matched unique title on page N", although it matched a numeral line. It is accurate about the page, not about the kind of match; the chapter's `evidence` names the numeral rule.
- The offset is inferred only from at least two uniquely matched named headings and only when it exceeds two pages (the existing rule), so an outline offset of one or two pages is not corrected for numeral anchors.
- The F2 test counts full passes over the block list; it does not time a large real outline, and indexed access to `blocks[i]` is not counted. The per-entry scans that existed in the outline loop are gone.
- The corroboration thresholds and the page-number guard remain heuristics checked on synthetic fixtures and one real book.
- The real book's first chapter, "Front Matter", still has confidence 0.7, so conversion still needs one human approval of that chapter.
- Local mypy reports the two known `kittenml` errors while the Kitten extra is installed; CI is the reference.

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
| 2026-10-27 | 80e5ace2c5782aa14058b22ba4d32d13b7f565f8 | Spec and TODO committed. | Docs only. Run [673](https://github.com/ekkus93/pdf2audiobook/actions/runs/40624513759) passed. | None |
| 2026-10-27 | eabe5df52e55dfeed24c003e4c529ac58d882e3a | 1.1-1.2 (F1): the numeral rule is also tried on the page shifted by the inferred offset, never on a listing page. | Failing at parent: `test_numerals_are_anchored_through_the_inferred_offset` and `test_a_shifted_anchor_carries_the_alignment_warning_and_lower_confidence` (the second first passed vacuously, then was strengthened to assert the chapters exist). The no-evidence and wrong-first-line guards pass on both. Run [674](https://github.com/ekkus93/pdf2audiobook/actions/runs/40624709093) passed. | None |
| 2026-10-27 | ff68b9197ac75968a7329389772a5da7871c68cf | 2.1-2.3 (F2, refactor): outline titles and each page's first line are indexed once; offset inference indexes heading titles once. | `test_passes_over_the_blocks_do_not_grow_with_the_number_of_outline_entries` failed at parent (88 passes for 40 entries, 408 for 200); it now passes. The anchors test passed before and after, and the full suite passed unchanged (1768 at that commit). Run [675](https://github.com/ekkus93/pdf2audiobook/actions/runs/40624893730) passed. | None |
| 2026-10-27 | 5f00c5326adaefb96399a2a79cdc4103e3e559fa | 3.1-3.2 (F3): `len(numeral_titles) >= 3` joins the strong-evidence gate that drops font-size-only and LLM-only headings. | Failing at parent: `test_a_large_type_line_inside_a_numeral_book_is_not_a_chapter` (the stray line became a chapter). The three control tests pass on both. Run [676](https://github.com/ekkus93/pdf2audiobook/actions/runs/40625074605) passed. | None |
| 2026-10-27 | 2096cb1490f43cc54062de5d3830f1d2de87e990 | 4.1-4.2 (F4): a counted `review_warning` prints "Analysis recorded N warning(s); see warnings in manifest.json"; the uncounted empty-chapter path keeps the review wording. | Failing at parent: the three counted-wording cases in `test_review_warning_wording`. Changed the E4 wording assertions in `tests/test_warning_noise.py`, as the spec requires, reason in the commit message. Run [677](https://github.com/ekkus93/pdf2audiobook/actions/runs/40625257575) passed. | None |
| 2026-10-27 | f2db808d72c0e7ecc6e0d236760c19e0e7125866 | 5.1-5.2 (F5): fixture `outline="ncx"|"nav"|None` (booleans still work); E1 and E2 outline tests run for both. | Coverage only: PyMuPDF already read the nav outline with the same titles and pages as the NCX one, so the new tests passed on first run and no limitation needs recording. Run [678](https://github.com/ekkus93/pdf2audiobook/actions/runs/40625541859) passed. | None |
| 2026-10-27 | daae4327eda6ed2c24111364aadb27ebe582a7a9 | 6.1-6.2: `chapter-detection-v4`; F1 and F3 documented in spec section 5; F4 wording in the README and maintainer guide. | Replaced the `chapter-detection-v3` pin, reason in the commit message. Run [679](https://github.com/ekkus93/pdf2audiobook/actions/runs/40625868521) passed on 3.11, 3.12 and 3.13. | None |
| 2026-10-27 | daae4327eda6ed2c24111364aadb27ebe582a7a9 | 7.1 final gate: `uv lock --check`, Ruff, format, mypy on 3.11, 3.12 and 3.13, `pytest -q -ra`, CLI smoke. | 1787 passed, 1 skipped (optional Kitten smoke). mypy reports only the two known `kittenml` errors locally, because the Kitten extra is installed in this venv; CI does not install it and passed. ffmpeg, tesseract and node were available. | None |
| 2026-10-27 | daae4327eda6ed2c24111364aadb27ebe582a7a9 | 7.2 re-check of the local *Spring Snow* EPUB under v4 (never committed; counts only). | 57 chapters; 55 numbered chapters at their own numeral; `review_required` empty; blocks per chapter min 18, median 222, max 456; summary line "Analysis recorded 398 warnings; see warnings in manifest.json"; LLM cache 1397 hits, 0 misses, 0 requests. Unchanged from the previous detector version, as expected for a book that was already correct. | None |
