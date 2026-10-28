# PDF2Audiobook EPUB Chapter Detection Specification

**Status:** Proposed
**Date:** 2026-10-27
**Companion:** `docs/PDF2AUDIOBOOK_EPUB_CHAPTERS_TODO.md`
**Baseline:** master at 04e4e8c (`feat(cli): add --llm-output-tokens to analyze and convert`)
**Supplements:** `docs/PDF2AUDIOBOOK_SPEC.md` (§5 chapter discovery), `docs/PDF2AUDIOBOOK_FOLLOWUP_FIXES_SPEC.md`

## 1. Purpose and scope

Converting a commercial EPUB (the 1990 Vintage edition of *Spring Snow*, 375 generated pages, 55 chapters) produced a chapter plan that would have produced a single unusable audio track. The run also printed hundreds of identical warning lines and stopped on a false damage flag.

The evidence below was taken from that run's manifest and from PyMuPDF. The book itself is copyrighted and must never be committed. The tests use synthetic EPUBs that reproduce the same structure.

### Observed defects

1. **Chapters anchored to the printed table of contents.** The EPUB outline has 61 correct entries; for example, `Chapter 1` points to page 6 and `Chapter 2` to page 15. Each chapter opens in the body with a bare numeral line (`1`, then the first sentence).
   - The outline matcher in `document/structure.py` accepts a block only when its text equals the bookmark title. Page 6 has no line reading "Chapter 1", so it fell back to a unique match within two pages: the contents list on page 4. The manifest records *"TOC entry 'Chapter 1' points to PDF page 6; matched unique title on page 4"*.
   - The contents lines `Chapter 26` to `Chapter 55` on page 5 were also kept as headings. The filter that drops contents-page labels applies only when the same label reappears later, and the body never prints "Chapter 26".
   - Result: 35 chapters. Chapters 6 to 34 are each one contents line, and the last chapter, titled "Chapter 55", holds 13,080 of the 13,156 blocks.
2. **LLM heading proposals at the right place were rejected.** All 19 rejected proposals point to line 2 of chapter-opening pages (`p00015-l00002` and similar). Verification requires the proposed text to equal the source line, so a proposal of "Chapter 2" for the source line "2" is discarded.
3. **False `damaged_source`.** Page 2 is the cover. It holds an embedded JPEG plus one drawing: a fill-only white rectangle covering the whole page, which is the background painted behind the image. A page with drawings but no text sets `damaged_source`. That rule protects scanned PDFs, but here it blocks conversion of an undamaged EPUB.
4. **Warning flood.** `pipeline._analyze_book_locked` runs `for _warning in extracted.warnings + warnings: log_event("review_warning", ...)`, which prints the same fixed line once per manifest warning. This run had 775 warnings, and 375 of them were the same per-page "could not read PDF page label; using physical" message, which is meaningless for generated EPUB pages. JSON mode deduplicates warning codes, so the flood appears only in human output.
5. **Stale plans would survive a fix.** The `chapter-boundaries` stage fingerprint (`pipeline._analysis_stage_fingerprints`) hashes only `settings.chapters`. Without a version token, a resumed workspace keeps its old chapter plan after any detector change.

All existing invariants still hold: source blocks, spans and coverage are preserved; LLM output is untrusted and never invents text; manual approvals block destructive reanalysis; errors and logs are content-free; CI stays offline.

## 2. Requirements

### E1: Outline anchoring prefers the target page

For each valid outline entry, after the existing offset inference:

1. **Exact title.** If exactly one block on the target page matches the title (`_title_key` equality), anchor it. This is the current rule.
2. **Numbered label on the target page.** Otherwise, if the title is a numbered chapter label, take the first non-empty, non-omitted block on the target page. Anchor it when it is a bare chapter number with the same value.
   - Numbered labels: `Chapter 12`, `CHAPTER 12`, `Chapter XII`, `Chapter Twelve` (number words are optional), `Part 3`.
   - Bare chapter numbers: `12`, `XII`, or `12.`.
   - Keep the outline title as the chapter title. The narrated text keeps the source line unchanged.
3. **Nearby fallback.** Only if steps 1 and 2 fail, use the existing ±2-page unique-match fallback, now with one restriction: it must never select a block on a contents-listing page (`listing_pages` in the same function). Compute the listing pages before the outline loop.
4. Each anchor records which rule matched in the existing alignment warning. The warning stays content-free: it carries the outline title and page numbers, never block text.

**Acceptance:** A synthetic EPUB has a two-page contents list (`Chapter 1` … `Chapter 30`), chapters that open with a bare numeral, and an outline `Chapter N` pointing at each opening page. All 30 outline entries are anchored to their numeral block (title from the outline, confidence 0.95, evidence naming the numbered chapter heading), with no "matched unique title on page" alignment warning. Whether the contents labels still add extra chapters is E2's acceptance. Existing PDF bookmark tests (exact match, printed-page offset, duplicated titles, malformed records) pass unchanged.

*Amendment (implemented):* anchoring by numeral is not a page-mismatch, so it adds no alignment warning. The rule that matched is recorded in the chapter's `evidence` instead, which avoids one warning per chapter.

### E2: Contents-listing labels do not open chapters

A chapter label on a contents-listing page is not a chapter start when the chapter it names is anchored elsewhere, either by an outline entry (E1) or by a bare-numeral heading on a later non-listing page.
- Compare by chapter number, not by text, so a listed `Chapter 26` is dropped once chapter 26 opens elsewhere as `26`.
- Labels for chapters that are anchored nowhere keep today's behavior.
- The existing rule that drops a listed label when the same label opens a chapter later stays as it is.

**Acceptance:** In the E1 fixture no chapter starts on a contents page, and the plan has the 30 numbered chapters plus front matter only (no one-line chapters from the contents labels). With the outline removed, the same holds when the body numerals are corroborated by the printed contents (see below). With prose headings and no outline, behavior matches today's.

*Amendment (design):* without an outline nothing detects a bare numeral as a heading, so E2 also adds **numeral headings corroborated by the printed contents**: a bare numeral that is the first line on its page, whose number is named by a contents label ("Chapter N") on a listing page, in strictly increasing order, accepted only when at least three such numerals are found and they cover at least half of the listed chapters. The chapter title is the contents label. Running page numbers must not qualify: when every accepted numeral sits at the same page-minus-number offset (one number per page), the sequence is rejected. Contents lists with fewer than six lines per page are not treated as listings (the existing detector threshold), so very short books are unaffected.

### E3: LLM heading proposals tolerate the numeral form

In LLM heading verification (`llm/structure.py`), accept a proposal whose block is a bare chapter number N and whose proposed title is a numbered label with the same N.
- Record the proposal as matching. The block text is unchanged and nothing is invented or deleted. *Amendment (implemented):* the LLM label is not carried into the chapter; the chapter takes its title from the outline, the printed contents or the block text, as for every other LLM-nominated heading.
- Any other mismatch is rejected as today.
- The "LLM heading text mismatched source" warning remains for real mismatches.

**Acceptance:**
- A fake provider proposing `Chapter 2` for the source line `2` is accepted, and the block text is unchanged.
- A proposal of `Chapter 3` for the source line `2` is rejected.
- A proposal of prose text for a numeral line is rejected.
- The privacy tests for these warnings still pass.

### E4: One warning line, and no per-page label noise for EPUB

- Replace the per-warning loop with a single `review_warning` event carrying `count=len(...)`, emitted only when there are warnings. The human description becomes "Book review is required before conversion (N warnings in manifest.json)", content-free.
- For reflowable documents (`document.is_reflowable`), page labels do not exist. Emit one warning, "EPUB pages have no printed page labels; physical page numbers are used", instead of one per page.

**Acceptance:**
- An analysis with K > 1 warnings prints exactly one warning line in human mode.
- `--json` still lists the `review_warning` code once.
- The E1 fixture's manifest contains no per-page label warnings and exactly one summary warning.
- The PDF page-label warning behavior is unchanged.

### E5: EPUB cover and background drawings are not damage

For reflowable documents, a page with no text does not set `damaged_source` when:
- every drawing on it is a fill-only rectangle covering at least 95% of the page (a background), and
- the page has at least one image block (`page.get_text("dict")`, block type 1).

Such a page is reported with the existing embedded-image warning instead ("embedded image detected; OCR does not describe figures or diagrams; review manually"). Every other no-text case keeps today's behavior, including any page whose drawings are not purely background and every PDF page.

**Acceptance:**
- The E1 fixture with a cover page (an image plus a full-page white background rectangle) has no `damaged_source`, and its manifest warns about the image.
- An EPUB page with a non-background drawing and no text still sets `damaged_source`.
- Existing PDF damaged-source tests pass unchanged.

### E6: Identity and upgrade

- Add a version token to the `chapter-boundaries` fingerprint, for example `fingerprint("chapter-detection-v2", chapter_settings)`. Bump the extraction token from `analysis-v22` to `analysis-v23`, because E4 and E5 change the stored warnings and review reasons.
- Expected effect on existing workspaces:
  - A workspace with no manual approvals or accepted LLM edits is re-analyzed on the next run.
  - LLM cache entries remain valid, because their keys depend on the block windows and instructions, not on chapter boundaries. A re-run should therefore mostly hit the cache. Verify this and record the hit count in the ledger rather than assuming it.
  - A workspace with approvals keeps refusing reanalysis with the existing message, so the user must use a new `--output` directory.
- Record the bump in `docs/MAINTAINER_GUIDE.md`'s upgrade notes.

**Acceptance:**
- A fixture workspace analyzed before the bump is re-planned after it, without approvals.
- The same workspace with a manually approved chapter refuses with the existing message.
- A cached-LLM test shows hits on the re-run.

### E7: Documentation consistency

- `docs/PDF2AUDIOBOOK_SPEC.md` FR-017 still lists EPUB as a future feature, while §9 and the README say EPUB is accepted. Correct FR-017.
- Document E1–E5 in §5 (chapter discovery) and the README's EPUB note: outline anchoring, numeral headings, cover pages, and the single warning line.

## 3. Validation

- Add focused deterministic tests for each requirement, using synthetic EPUBs built with `zipfile`, as in `tests/test_epub_input.py`. Then run `/verify`, plus mypy on 3.12 and 3.13.
- **Manual acceptance, local only and never committed:** re-analyze `tmp/Spring Snow [Sea of Fertility 1]/…1990).epub` with the settings from the failed run. Expect:
  - front matter plus 55 chapters at the body numerals, with outline titles;
  - no `damaged_source`;
  - one warning line;
  - the LLM cache hit count recorded.

  The real file is copyrighted, so record only counts and outcomes in the ledger.
