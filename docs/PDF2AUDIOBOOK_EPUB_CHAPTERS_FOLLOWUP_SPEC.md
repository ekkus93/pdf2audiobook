# PDF2Audiobook EPUB Chapter Detection Follow-up Specification

**Status:** Implemented
**Date:** 2026-10-27
**Companion:** `docs/PDF2AUDIOBOOK_EPUB_CHAPTERS_FOLLOWUP_TODO.md`
**Baseline:** master at 792b822 (`docs: record epub chapter review fixes ci evidence`)
**Supplements:** `docs/PDF2AUDIOBOOK_EPUB_CHAPTERS_SPEC.md` (E1–E7)

## 1. Purpose and scope

The code review of the EPUB chapter detection work (E1–E7) found issues in `document/structure.py` and the logging layer. Three were fixed in `f294b23`: titles carrying contents leaders, the page-number guard, and the Part/Chapter conflation. This spec covers everything the review raised that is still open, so it can be fixed in one pass.

All existing invariants still hold: chapter plans are deterministic and content-addressed, the narrated text is never altered, errors and logs are content-free, and CI stays offline. Use synthetic fixtures only; never commit the real book.

## 2. Requirements

### F1: Numeral anchoring honours the inferred page offset

**Problem.** The outline loop in `propose_chapters` infers a printed-versus-physical page offset (`inferred_offset`) from uniquely matched titles. The exact-title fallback uses that offset, but the numeral rule added for E1 checks only the outline's raw page. A PDF whose outline points at printed page numbers, and whose chapters open with a bare numeral, is therefore not anchored, even when the offset is known.

**Requirement.** Try the numeral rule on the outline's page first. If it does not match there and `inferred_offset` is set, try it on `page_index + inferred_offset`.
- Anchor only when the first line on that page is the entry's numeral (`bare_number == label_number`).
- Never anchor on a contents-listing page.
- When the shifted page is used, add the existing content-free alignment warning ("TOC entry … points to PDF page N; matched … on page M"). The chapter's confidence is then 0.85, as for the other page-mismatch anchors.

**Acceptance:**
- A synthetic book whose outline is offset by a constant (for example +4) anchors every chapter at its numeral on the shifted page, with the alignment warning and confidence 0.85.
- Offset inference needs at least two uniquely matched titles, so the fixture provides two exact-title headings (for example "Preface" and "Prologue") alongside the numeral chapters.
- With no inferred offset, behavior is unchanged.

### F2: Outline matching does not rescan the book for every entry

**Problem.** For each outline entry, `propose_chapters` scans every block twice, so the work grows as outline entries × blocks:
- once to collect blocks whose `_title_key` equals the title (the `matching` list; this predates E1);
- once more, for numeral anchoring, to find the first line on the target page (added in E1).

That is acceptable for a novel (61 entries against 13,000 blocks), but slow for large technical PDFs with long outlines.

**Requirement.**
- Before the outline loop, build a `title_key → [block indices]` map and the `first_on_page` map. `first_on_page` already exists later in the function; move it earlier and reuse it.
- The loop must do no full scan per entry.
- Behavior must not change: the same anchors in the same order.

**Acceptance:**
- A deterministic iteration-count test passes the block list as a list subclass that counts its own iterations. With an outline of 200 numbered entries, block iterations inside `propose_chapters` stay below a small constant multiple of the block count (for example ≤ 10 passes), rather than growing with the number of entries.
- The full existing suite passes unchanged, which shows behavior is preserved.

### F3: Corroborated numerals also suppress font-size-only headings

**Problem.** When the outline, contents titles or numbered labels give strong evidence, `propose_chapters` drops candidates supported only by font size or LLM classification (the `weak` set). The gate is `len(bookmark_titles) >= 2 or contents_titles or numbered_labels >= 3`. A book whose chapters are found only through corroborated numerals (E2: no outline, numeral body headings) meets none of these conditions. Stray large-type lines, such as a title page, a copyright heading or an advert, can then still split the book.

**Requirement.** Add `or len(numeral_titles) >= 3` to that gate. The existing warnings ("Ignored N font-size-only heading candidate(s)…", "Ignored N LLM-proposed heading(s)…") then apply as they do for the other evidence types.

**Acceptance:**
- A synthetic book with no outline, a printed contents list, numeral chapter openings, and one large-type heading inside the body (a prose line set in a large font, not a chapter) does not gain an extra chapter for that line.
- The "Ignored … font-size-only" warning is recorded.
- Without corroborated numerals, behavior is unchanged.

### F4: The analysis warning summary says what it means

**Problem.** E4 prints one human line, "Book review is required before conversion (N warnings in the manifest)". Most manifest warnings are informational. Conversion is blocked only by `review_required` codes and per-chapter gates, never by the warning count, so the line overstates what the warnings mean. The same `review_warning` event, without a count, is also emitted by `chapter_selection.refresh_empty_chapter_reason` for a stale empty-chapter acknowledgement, where the original wording fits.

**Requirement.**
- When the `review_warning` event carries `count`, print "Analysis recorded N warnings; see warnings in manifest.json". For one warning, print "Analysis recorded 1 warning; see warnings in manifest.json".
- Without `count`, keep the current text.
- Keep the event name and the `--json` warning code (`review_warning`) unchanged, so machine consumers are unaffected.

**Acceptance:**
- In human mode, a book with K warnings prints exactly one line with the new wording and the count, singular or plural.
- The empty-chapter path still prints "Book review is required before conversion".
- `--json` still lists `review_warning` once and keeps stderr empty.
- Update the existing E4 test (`tests/test_warning_noise.py`), whose wording assertion this requirement intentionally changes, with the reason in the commit message.

### F5: EPUB3 navigation documents are covered by tests

**Problem.** The synthetic fixture (`tests/epub_book.py`) writes an EPUB 2 NCX outline only. Most current EPUBs carry an EPUB 3 navigation document (`nav.xhtml` with `epub:type="toc"`), and none of the E1 tests exercise that path.

**Requirement.**
- Add an `outline="ncx" | "nav" | None` option to the fixture. Keep backward compatibility with the boolean `outline=True` (meaning NCX) and `outline=False` (meaning none).
- Confirm with PyMuPDF that a nav outline is read with the same titles and pages.
- Run the E1 anchoring and E2 label tests for both outline kinds.
- If PyMuPDF does not expose a nav-only outline through `get_toc()`, record that in the ledger and in the README's EPUB note as a known limitation, rather than adding a separate parser.

**Acceptance:**
- The fixture sanity test confirms the nav outline's titles and pages.
- The parametrized E1 and E2 tests pass for `ncx` and `nav`, or the limitation is recorded as described.

## 3. Identity

F1 and F3 change chapter plans for some books. Bump the chapter-boundaries token from `chapter-detection-v3` to `chapter-detection-v4`, update the pin in `tests/test_fingerprint_bumps_fx9.py` with the reason in the commit message, and extend the upgrade note in `docs/MAINTAINER_GUIDE.md`.
- F2 must not change any plan, so it needs no bump of its own.
- F4 changes output wording only.
- F5 changes tests only.

## 4. Validation

- Add focused tests per requirement, then run `/verify`, plus mypy on 3.12 and 3.13.
- Re-check the local *Spring Snow* EPUB (never committed). Expect 57 chapters, all 55 numbered chapters at their numeral, no `review_required`, a full LLM cache hit, and the new F4 wording. Record counts only.
