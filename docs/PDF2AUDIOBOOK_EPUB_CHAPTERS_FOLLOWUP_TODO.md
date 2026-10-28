# PDF2Audiobook EPUB Chapter Detection Follow-up TODO

**Status:** In progress
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

- [ ] 6.1 Bump `chapter-detection-v3` to `chapter-detection-v4` (F1 and F3 change plans). Update the pin in `tests/test_fingerprint_bumps_fx9.py` and the upgrade note in `docs/MAINTAINER_GUIDE.md`.
- [ ] 6.2 Document F1 and F3 in §5 of `docs/PDF2AUDIOBOOK_SPEC.md`, and the F4 wording in the README's "Watching a long run" section if it quotes the line.

## 7. Finish

- [ ] 7.1 Run `/verify`, plus mypy on Python 3.12 and 3.13. Record the pass and skip counts.
- [ ] 7.2 Re-check the local *Spring Snow* EPUB, never committed, and record counts only. Expect:
  - 57 chapters, with all 55 numbered chapters at their numeral;
  - `review_required` empty;
  - LLM cache hits only;
  - the new one-line summary.
- [ ] 7.3 Review the final diff against F1–F5 and record any unresolved limitations.

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
