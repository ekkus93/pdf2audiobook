# PDF2Audiobook EPUB Chapter Detection TODO

**Status:** In progress
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

- [ ] 8.1 Run `/verify`, plus mypy on Python 3.12 and 3.13. Record the pass and skip counts.
- [ ] 8.2 Manual acceptance on the local *Spring Snow* EPUB, never committed. Use the failed run's settings in a fresh output directory, or the existing one, which has no approvals. Record counts only:
  - chapters, expecting front matter plus 55;
  - whether `damaged_source` is set, expecting not;
  - human warning lines, expecting one;
  - LLM cache hits and misses.
- [ ] 8.3 Review the final diff against every acceptance criterion in E1–E7, and record unresolved limitations.

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
