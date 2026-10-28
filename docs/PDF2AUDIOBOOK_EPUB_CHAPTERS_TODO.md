# PDF2Audiobook EPUB Chapter Detection TODO

**Status:** Complete; unresolved limitations are listed below
**Date:** 2026-10-27
**Baseline:** master at 04e4e8c
**Specification:** `docs/PDF2AUDIOBOOK_EPUB_CHAPTERS_SPEC.md` (E1–E7)
**Previous TODO:** `docs/PDF2AUDIOBOOK_FOLLOWUP_FIXES_TODO.md`

## Working rules

- Work in the order below, because later tasks depend on earlier ones. Use `[x]` only when the implementation exists and its named tests pass; check a parent only when all of its subitems are checked.
- Every fix task has three parts:
  - (a) add the regression tests, run them against the parent commit, and record the failing test IDs in the ledger;
  - (b) make the fix;
  - (c) run `/verify`.
- One fix per commit, with its tests. Conventional Commits with a scope, lowercase imperative subject, no body. Docs-only status changes go in their own `docs:` commits.
- Never change an existing test's inputs or expected results to make a change pass. If the implementation must differ from the spec, amend the spec in the same commit.
- Every new warning or error path gets a privacy assertion: no book text, titles from the body, or paths. Add every new `src/` module to `[tool.mypy].files`. CI stays offline.
- Never commit the real EPUB or any text from it. Fixtures are synthetic.

## 0. Shared fixture

- [x] 0.1 Add a synthetic EPUB builder under `tests/`, extending the `_write_epub` pattern in `tests/test_epub_input.py`. It needs options for:
  - a cover page: an image plus a full-page white background rectangle;
  - a contents list spanning two generated pages with `Chapter 1` … `Chapter N`;
  - body chapters that open with a bare numeral line;
  - an optional outline (nav or NCX) with `Chapter N` entries pointing at each opening page.

  Confirm with PyMuPDF that the fixture reproduces the observed structure: the outline titles, the numeral first lines, the drawing count on the cover, and `is_reflowable`.

## 1. Outline anchoring (E1)

- [x] 1.1 Tests: with the outline, every outline entry is anchored to its numeral block, titled from the outline, with confidence 0.95 and no alignment warning; plus tests for the number parsers. (No-chapter-on-a-contents-page belongs to E2, section 2.) Record the failures at the parent commit.
- [x] 1.2 Compute `listing_pages` before the outline loop in `document/structure.py`.
- [x] 1.3 Add numbered-label parsing for arabic, roman and optional number-word forms, and `Chapter`/`Part`, with matching bare chapter numbers. Anchor on the target page in the order: exact title, then numbered label against the first block, then the nearby fallback, which must never land on a listing page.
- [x] 1.4 Record the matched rule in the chapter's evidence (numeral anchoring is not a page mismatch, so it adds no warning).
- [x] 1.5 Confirm the existing PDF bookmark tests pass unchanged.

## 2. Contents-listing labels (E2)

- [x] 2.1 Tests: with the outline, no chapter starts on a contents page and the plan is the numbered chapters plus front matter. Without the outline, numerals corroborated by the printed contents become headings. Prose-titled bodies behave as today.
- [x] 2.2 Drop listing-page labels whose chapter number is anchored elsewhere, by the outline or by a corroborated numeral heading. Compare by number.
- [x] 2.3 Detect numeral headings corroborated by the printed contents (first line on its page, number named by a listing-page label, strictly increasing, at least three and at least half of the listed chapters).

## 3. LLM heading verification (E3)

- [x] 3.1 Tests with a fake provider:
  - `Chapter 2` for the source line `2` is accepted, with the block text unchanged;
  - `Chapter 3` for `2` is rejected;
  - prose for a numeral line is rejected;
  - warnings stay content-free.
- [x] 3.2 Accept numeral-equivalent proposals in `llm/structure.py` verification. The label is not propagated to the chapter title.

## 4. Warning noise (E4)

- [x] 4.1 Tests:
  - K > 1 warnings print exactly one human warning line, with the count;
  - `--json` lists `review_warning` once;
  - the EPUB fixture has one page-label summary warning and no per-page ones;
  - PDF page-label warnings are unchanged.
- [x] 4.2 Emit a single `review_warning` with `count`, and update its description.
- [x] 4.3 Collapse page-label warnings for reflowable documents into one summary warning.

## 5. EPUB cover and background pages (E5)

- [x] 5.1 Tests:
  - the fixture cover page sets no `damaged_source` and records the embedded-image warning;
  - an EPUB page with a non-background drawing and no text still sets `damaged_source`;
  - PDF damaged-source tests are unchanged.
- [x] 5.2 Implement the background-rectangle and image-block rule for reflowable documents only.

## 6. Identity and upgrade (E6)

- [x] 6.1 Tests:
  - a workspace analyzed before the bump is re-planned after it;
  - with a manually approved chapter, it refuses with the existing message;
  - a re-run reuses the LLM cache, asserting cache hits.
- [x] 6.2 Add `chapter-detection-v2` to the `chapter-boundaries` fingerprint and bump `analysis-v22` to `analysis-v23`. Add the upgrade note to `docs/MAINTAINER_GUIDE.md`.

## 7. Documentation (E7)

- [x] 7.1 Fix FR-017 in `docs/PDF2AUDIOBOOK_SPEC.md` and document E1–E5 in §5.
- [x] 7.2 Update the README's EPUB note: outline anchoring, numeral headings, cover pages and the single warning line.

## 8. Finish

- [x] 8.1 Run `/verify`, plus mypy on Python 3.12 and 3.13. Record the pass and skip counts.
- [x] 8.2 Manual acceptance on the local *Spring Snow* EPUB, never committed. Use the failed run's settings in a fresh output directory, or the existing one, which has no approvals. Record counts only:
  - chapters, expecting front matter plus 55;
  - whether `damaged_source` is set, expecting not;
  - human warning lines, expecting one;
  - LLM cache hits and misses.
- [x] 8.3 Review the final diff against every acceptance criterion in E1–E7, and record unresolved limitations.

## Unresolved limitations

- The first chapter, "Front Matter" (the copyright page text), still has boundary confidence 0.7, below the 0.75 threshold, so conversion of the real book still stops on one human review step: approve that chapter, after reading it, before synthesis. This is the existing gate working as designed; the detector change does not lower it.
- A contents list with fewer than six lines per page is not recognised as a listing (the existing detector threshold), so very short books do not get numeral corroboration; they behave as before.
- Numeral anchoring and corroboration require the numeral to be the first non-omitted line on its page. A book that puts a running head or ornament first falls back to the previous behavior for that chapter.
- The corroboration thresholds (at least three numerals, at least half of the listed chapters, not one per page) are heuristics checked on synthetic EPUBs and one real book; they have not been run against a wider set of books.
- Local mypy reports the two known `kittenml` errors while the Kitten extra is installed; CI is the reference.

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
| 2026-10-27 | c002aa5beec4e691ec522e200bea572fdf2a7dd8 | Spec and TODO committed. | Docs only. Run [661](https://github.com/ekkus93/pdf2audiobook/actions/runs/40617996797) passed. | None |
| 2026-10-27 | 48e503de5e69925324aa667b338620e10328b96d | 0.1: synthetic novel EPUB fixture (`tests/epub_book.py`) and its sanity tests. | 6 new tests; the fixture was probed with PyMuPDF to reproduce the real book's outline, bare-numeral openings, split contents and white-background cover. Run [662](https://github.com/ekkus93/pdf2audiobook/actions/runs/40618194618) passed. | None |
| 2026-10-27 | 17f43b2c8f24645933cdcc54c7049f33c5832cf3 | 1.1-1.5 (E1): outline entries anchor to the lone numeral on their page; `label_number`/`bare_number`; contents pages excluded from the nearby fallback. | Failing at parent: the helper tests (`ImportError`) and, in the first run before the tests were narrowed, the anchoring cases (the fixture produced `Chapter 16` at index 1, 16 of 30 chapters, a 211-block chapter, `Chapter 1` starting on the contents page). Spec and TODO amended: E1 no longer asserts the contents-page outcome, which is E2. Run [663](https://github.com/ekkus93/pdf2audiobook/actions/runs/40618646017) passed. | None |
| 2026-10-27 | a4c1ae73265fd0d35dd2c56927af34368577e5e3 | 2.1-2.3 (E2): contents labels whose chapter opens elsewhere are dropped; numeral headings corroborated by the printed contents. | Failing at parent: `test_with_an_outline_no_contents_label_becomes_a_chapter`, `test_without_an_outline_numerals_named_by_the_contents_are_headings`, `test_the_plan_is_stable_across_book_sizes[12]` and `[16]`. A page-number guard (constant page-minus-number offset) was added after reasoning about running page numbers and is tested; the fixture's chapters were made variable in length for it. Run [664](https://github.com/ekkus93/pdf2audiobook/actions/runs/40619355159) passed. | None |
| 2026-10-27 | a467c8b4fe93b8c8eb75541d91815314d5cc5eb2 | 3.1-3.2 (E3): an LLM label for a lone numeral line is accepted. | Failing at parent: the six `test_a_label_for_the_numeral_on_the_line_is_accepted` cases; the rejection cases already passed. The label is not propagated to the title (spec amended). Run [665](https://github.com/ekkus93/pdf2audiobook/actions/runs/40619541250) passed. | None |
| 2026-10-27 | 383f3dd988b312b012ca0d7b0fbbb8cc107ab08e | 4.1-4.3 (E4): one `review_warning` with a count; one EPUB page-label summary. | Failing at parent: `test_an_epub_has_one_label_summary_not_one_warning_per_page` and `test_human_output_prints_one_review_line_with_the_warning_count`. Run [666](https://github.com/ekkus93/pdf2audiobook/actions/runs/40619876243) passed. | None |
| 2026-10-27 | 80b6412f7cec71497fdd01afc144bdadff58f616 | 5.1-5.2 (E5): an EPUB image on a page-sized background fill is not `damaged_source`. | Failing at parent: `test_a_cover_image_on_a_page_background_does_not_flag_damage` and the `_background_only` helper tests. The vector-art and PDF cases assert existing behavior. Corrected my own tests, which had set `ocr = never` and so never reached the branch. Run [667](https://github.com/ekkus93/pdf2audiobook/actions/runs/40620200011) passed. | None |
| 2026-10-27 | e8fa9574caa671b4feb52a5b4396edd8c79f9179 | 6.1-6.2 (E6): `analysis-v23` and `chapter-detection-v2`; upgrade note in the maintainer guide. | Failing at parent: all four of `test_epub_analysis_upgrade`. Replaced `test_extraction_fingerprint_is_the_fx9_generation` (pinned `analysis-v22`) with `test_extraction_fingerprint_is_the_epub_chapters_generation`, reason in the commit message. Run [668](https://github.com/ekkus93/pdf2audiobook/actions/runs/40620609434) passed. | None |
| 2026-10-27 | 2a16c2d707095573e4b64d0df4a5848d7fcbc5e0 | 7.1-7.2 (E7): FR-017 corrected; E1-E5 documented in spec section 5 and the README. | Docs only. Run [669](https://github.com/ekkus93/pdf2audiobook/actions/runs/40620669093) passed on 3.11, 3.12 and 3.13. | None |
| 2026-10-27 | 2a16c2d707095573e4b64d0df4a5848d7fcbc5e0 | 8.1 final gate: `uv lock --check`, Ruff, format, mypy on 3.11, 3.12 and 3.13, `pytest -q -ra`, CLI smoke (`--help`, `config show --json`, `doctor --json`). | 1751 passed, 1 skipped (optional Kitten smoke). mypy reports only the two known `kittenml` errors locally, because the Kitten extra is installed in this venv; CI does not install it and passed. ffmpeg, tesseract and node were available. | None |
| 2026-10-27 | 2a16c2d707095573e4b64d0df4a5848d7fcbc5e0 | 8.2 manual acceptance on the local *Spring Snow* EPUB (never committed; counts only), re-analysed with the failed run's settings in its existing workspace. | Chapters 35 -> 57 (front matter, contents, chapters 1-55); all 55 chapters open at their own numeral with confidence 0.95; blocks per chapter min 18, median 222, max 456 (before: one chapter held 13,080); `review_required` empty (was `damaged_source`); 1 human warning line with count 398 (was about 775 lines) and 1 page-label summary (was 375); LLM cache 1397 hits, 0 misses, 0 requests (no Ollama needed). | None |
