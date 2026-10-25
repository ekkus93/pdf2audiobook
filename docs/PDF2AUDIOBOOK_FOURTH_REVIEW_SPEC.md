# PDF2Audiobook — Fourth Review Fixes Specification

**Status:** Fourth review of `0c19845..6eedfa4` drafted; R80–R112 not implemented
**Date:** 2026-10-25
**Baseline:** master at 6eedfa4 (`docs: record fx9 completion and ci evidence`)
**Parent specification:** docs/PDF2AUDIOBOOK_SPEC.md
**Previous review specification:** docs/PDF2AUDIOBOOK_REVIEW_FIXES_SPEC.md (R1–R79)
**Companion:** docs/PDF2AUDIOBOOK_FOURTH_REVIEW_TODO.md (phase FX10)

## 1. Purpose and scope

On 2026-10-25 the whole project was reviewed again, and every task and subtask in docs/PDF2AUDIOBOOK_REVIEW_FIXES_TODO.md (FX0–FX9) was checked against the code at 6eedfa4.

At 6eedfa4 every local gate passes:
- `ruff check`, `ruff format --check` and `mypy` (22 files) are clean;
- pytest gives 1331 passed and 32 skipped locally, where FFmpeg, Tesseract and the Kitten extra are absent;
- CI run 40214615871 succeeded on Python 3.11–3.13.

The review found:

- three high-severity defects:
  - a review-UI save waives book-wide review reasons;
  - valid hand edits make reanalysis fail;
  - `batch` reports failed books as an internal error;
- twelve medium-severity defects, one of them a regression introduced by FX8 (numbered footnotes classified as lists);
- one checked item that is not met (FX8.12a);
- about forty checked items that are only partly met, mostly because their tests don't exercise what the item claims;
- documentation drift and status-record inconsistencies.

This document gives the required behaviour and acceptance tests for every finding. Each requirement has an ID; numbering continues from the previous specification, so R80 follows R79. The companion TODO orders the requirements by dependency as phase FX10.

This document adds to the parent spec and the previous review spec; it doesn't replace them. Where they disagree, the parent spec wins, except for the amendments in §11, which get merged into the parent spec as part of the work.

File and line references point to 6eedfa4 and are approximate, so check the current code before editing. A finding marked **(confirmed)** was reproduced by running code or a probe, or verified by reading the code. A finding marked **(suspected)** must first be shown by a failing test; if no failing test can be written, record that in the ledger and close the requirement without a code change.

Severity labels: **H** high, **M** medium, **L** low, **D** design or quality, **T** a TODO item marked done that is actually partial or wrong.

## 2. Ground rules

Everything in parent spec §12, the CLAUDE.md invariants, and the ground rules in §2, §8.2 and §9.2 of the previous review spec still applies. In particular:

- **One fix per commit, with its regression tests.** Docs-only status changes go in separate `docs:` commits.
- **Prove each regression test fails.** Before committing, run the new tests against the parent commit and record the failing test IDs in the ledger row. A test that passes at the parent doesn't count as a regression test. When one test function is parametrized, record the case IDs, not just a count.
- **Never change an existing test's inputs or expected results to make a change pass.** If an existing assertion is truly obsolete, delete it with a reason in the commit message and add a new, truthfully named test.
- **Test names describe what the test asserts.** A test named `…_blocks_…` asserts a block; a test named `…_near_body_text` has body text near the thing it tests.
- **The ledger is append-only.** A row's SHA is the full 40-character SHA of the commit whose state it documents, written after that commit exists. Corrections are new rows.
- **Status changes happen in git.** Each uncheck or re-check is a commit, and a parent is checked only when all of its subitems are.

Two rules are added for FX10:

- **Spec decisions are amendments, not footnotes.** If implementation leads to a behaviour that differs from a requirement's text, amend the requirement in this document in the same commit, citing the reason. Recording the decision only in the TODO or an audit file is not enough. The previous review's FX9.02c and FX9.16d decisions are brought into line by R110.
- **Gated tests must be shown to run.** A test that skips without FFmpeg, Tesseract or Node counts as evidence only when the CI log's skip summary shows it ran. CI must therefore print a skip summary (R111).

## 3. Review gate and manifest

**R80 — Book-wide review reasons are cleared only by an explicit acknowledgement (H) (confirmed).**
*Problem:*
- `save_chapter_updates` sets `manually_approved = True` on every chapter on any save (review_ui.py:157).
- `select_chapters` waives `damaged_source` and `ambiguous_page_numbers` for approved chapters (pipeline.py:787-794).
- The combined effect: a title-only save with the acknowledgement checkbox unticked keeps `damaged_source` in `review_required`, but convert proceeds anyway. R73's acknowledgement control has no effect on the gate, and the FX9.09a test only checks the list, never the gate.

*Required:*
- `damaged_source` and `ambiguous_page_numbers` are book-wide reasons. While either is in the current `review_required` and not in `review_acknowledged`, convert refuses every chapter, whether or not it is approved. Chapter approval never waives a book-wide reason.
- The only ways to acknowledge a book-wide reason are the review UI's explicit control and `convert --accept-review REASON`.
- The review UI offers the control for each book-wide reason that is currently present, not just `damaged_source`. The accepted set in `save_chapter_updates` (review_ui.py:123) becomes the book-wide reason codes.
- Per-chapter reasons (empty chapter, low boundary confidence) keep their current per-chapter approval semantics.

*Tests (new):*
- a title-only review-UI save, then `select_chapters` raises for `damaged_source` and for `ambiguous_page_numbers`;
- the explicit control (and `--accept-review`) then lets it pass;
- the page offers a control for `ambiguous_page_numbers` when that reason is present.

**R81 — Hand-edit protection survives valid edits (H) (confirmed; FX8.12a is not met).**
*Problem:*
- **A valid boundary edit breaks reanalysis.** Moving the boundary between chapters 1 and 2 needs edits to both `ch1.end_block` and `ch2.start_block`; without both, coverage is invalid. During reanalysis, chapter 1's edit moves the new chapter 2's start (pipeline.py:613-624). The identity matcher then looks for a new chapter starting at chapter 2's generated start block, finds none, and raises "Chapter 2 was edited but cannot be aligned after reanalysis" (pipeline.py:249-268, 550).
- **A title-only edit can also fail.** If reanalysis moves that chapter's own start by one block, the exact-start matcher fails the same way. R53 was written to remove exactly this failure.
- **The existing test can't catch either case.** It edits one side of a boundary, leaving a gap, and never asserts that the edited value survives (tests/test_chapter_edit_privacy.py:10).
- The conflict messages (pipeline.py:605-608, 619-622) don't tell the user to approve or revert, which R53 requires.

*Required:*
- Match every old chapter to a new chapter **before** applying any edit or neighbour adjustment.
  - Matching rule: the new chapter whose generated start block equals the old generated start block. If there is none, the unique new chapter whose generated range contains the old generated start block. If there is still none, a content-free conflict naming the old chapter number.
  - Never match by chapter number (R75).
- Then apply all edited fields together: titles, voices, and boundaries as a set. A boundary edit that was coverage-valid in the old manifest moves the matched neighbour's adjacent boundary to the same block. After applying, the chapters must cover the document contiguously; otherwise raise a content-free conflict naming the chapter numbers involved.
- Every conflict message ends with a fixed instruction to approve or revert the named chapters.
- Keep a single baseline per chapter. The `generated_*` fields and `generated_fingerprint` must agree after any merge or neighbour move (today pipeline.py:593-597 keeps the old fingerprint with new fields). A neighbour whose boundary was moved for it is not reported as user-edited on the next run.

*Tests (new):*
- a coverage-valid two-sided boundary edit survives reanalysis with its values asserted;
- a title-only edit survives when reanalysis shifts that chapter's start by one block;
- a title-only edit followed by a change to a neighbour's generated boundary (missing from FX8.12c);
- an edited chapter that becomes empty after reanalysis is reported, not silently converted (missing from FX8.12c);
- an unedited neighbour moved by an edit isn't reported as edited on the next reanalysis;
- conflict messages contain the approve-or-revert instruction and no book text.

**R82 — The analysis fingerprint excludes gate-only settings (M) (confirmed).**
*Problem:*
- `chapters.min_boundary_confidence` is fingerprinted (pipeline.py:155) but is only used by the convert gate (pipeline.py:796). Changing it on an approved workspace fails with "Changed analysis stage(s): chapter-boundaries", which goes against R13.
- When the LLM is disabled, LLM settings are still fingerprinted.
- An approved workspace run with `--no-resume` and unchanged settings fails with the fallback message "Changed analysis stage(s): analysis" (pipeline.py:186), which names no real change.

*Required:*
- Leave settings that affect only gating out of the analysis fingerprint.
- Include LLM settings only when the LLM is enabled.
- With `--no-resume` and unchanged stage fingerprints on an approved workspace, report a fixed message saying the approved analysis is kept, and carry on using it rather than failing.

*Tests (new):*
- after approval, changing `min_boundary_confidence` is accepted;
- with the LLM disabled, changing the LLM model is accepted;
- `convert --no-resume` on an approved workspace with unchanged settings succeeds in dry-run.

**R83 — `convert --dry-run` matches a real convert (M) (confirmed).**
*Problem:*
- Dry-run (cli.py:527-548) never calls `refresh_empty_chapter_reason`. A chapter emptied by hand after analysis makes dry-run exit 0 while a real convert exits 6.
- Dry-run lists approved empty chapters as MP3s that the real run skips.
- It logs no `review_acknowledged` event for `--accept-review` (R74).
- It duplicates the acknowledgement logic instead of sharing it.

*Required:* Dry-run and convert use one shared function to:
- apply acknowledgements;
- recompute review reasons from the current manifest;
- decide which chapters are converted, skipped or refused.

Dry-run reports exactly the chapters, skips and refusals the real run would produce, with the same exit code. It logs the same `review_acknowledged` event and writes nothing.

*Tests (new):*
- a hand-emptied chapter gives exit 6 in dry-run;
- an approved empty chapter is listed as skipped;
- dry-run logs `review_acknowledged` and changes no workspace file.

**R84 — `pack-m4b` packages exactly what convert produces (M) (confirmed).**
*Problem:*
- **Skipped chapters block packaging forever.** `pack-m4b` requires an MP3 for every manifest chapter (cli.py:727-751), but convert deliberately skips approved or acknowledged empty chapters (pipeline.py:949-960). Such a book exits 6 with "stale or missing … run convert", and running convert never fixes it.
- **A different footnote setting makes every chapter look stale.** `pack-m4b` renders narration with its own `settings.pdf.footnotes` (cli.py:732). If convert ran with a different footnote setting (another config, or `--no-config`), every chapter reports as stale.

*Required:*
- `pack-m4b` uses the same chapter-selection function as convert and dry-run (R83). Chapters that convert would skip are left out of the M4B, and `pack-m4b` reports them by chapter number in its output.
- Each MP3 sidecar records the narration-rendering inputs that affect the text hash (at least the footnote policy). `pack-m4b` renders with the recorded inputs. If a chapter's recorded inputs differ from the current settings, it still verifies the hash using the recorded inputs; a mismatch is reported as stale.
- This is a sidecar format bump (§10).
- **Decision (fourth review):** implement this in two steps, so users regenerate chapter audio only once.
  - **Skipped chapters:** fix first, with no format change.
  - **Recorded rendering inputs and the sidecar bump:** do these in the same task as the R105/R106 chapter-audio fingerprint bump, since that bump regenerates the audio anyway.

*Tests (new):*
- a book with an approved empty chapter packages with that chapter left out (FFmpeg-gated for the happy path; the selection logic is tested without FFmpeg);
- convert with `pdf.footnotes = "omit"`, then `pack-m4b --no-config`, still verifies freshness;
- a sidecar without the recorded inputs is treated as stale.

**R85 — The workspace lock covers analysis and review saves (M) (confirmed).**
*Problem:*
- `convert_book` runs `analyze_book` before taking `_workspace_conversion_lock` (pipeline.py:889-890). A second `convert --no-resume`, or a second convert with changed analysis settings, rewrites `manifest.json` and `chapters/*.txt`, and may make LLM calls, before it is refused. The first run then aborts with "Approved chapter text changed during conversion".
- (Suspected) A review-UI save can race a convert's manifest rewrite and lose an update.

*Required:*
- `convert`, `analyze` and `batch` (per book) take the exclusive workspace lock before any analysis or write, and hold it until they finish.
- The review UI's save takes the same lock without blocking. If the lock is held, it returns 409 with a fixed body and writes nothing.
- The lock file and its error messages stay content-free.

*Tests (new):*
- with the lock held, `convert --no-resume` exits with the lock error and leaves `manifest.json` and `chapters/*.txt` byte-identical;
- `analyze` with the lock held is refused;
- a review-UI POST with the lock held gets 409 and the manifest is unchanged.

**R86 — MP3 cleanup tolerates files it can't inspect (L) (confirmed).**
*Problem:* After publishing a chapter, cleanup calls `os.samefile` on every `audio/*.mp3`. A dangling symlink, or a file deleted mid-run, raises `OSError`, and the code turns that into `AudioError`, aborting convert after chapter 1 is published without writing `conversion_status.json` (pipeline.py:1221-1227).
*Required:* A candidate file that can't be inspected is skipped (it is not ours unless it has a valid sidecar) and logged with a content-free WARNING event. Cleanup never aborts a conversion.
*Tests (new):* a dangling `audio/x.mp3` symlink survives a convert that succeeds and writes `conversion_status.json`.

**R87 — Rejected deterministic cleanup edits are protected (L/D) (confirmed by reading).**
*Problem:*
- `approved_content` counts only accepted non-deterministic edits (pipeline.py:305-309).
- If a user sets a deterministic edit (for example a page-number removal) to `accepted = false` to keep the text, the next `--no-resume` or settings change rebuilds the edits with `accepted = true` and drops that text again, without warning.

*Required:* A deterministic edit whose `accepted` differs from its generated default counts as user-edited content. It is preserved across reanalysis like an approved edit, matched by its block ID and edit kind. If the edit can no longer be matched, raise a content-free conflict naming the block's chapter number.
*Tests (new):* reject a page-number removal, reanalyse with a changed OCR setting, and the text stays in the narration.

**R88 — Structured review reasons; empty chapters need per-chapter approval (L/D; amends R74).**
*Problem:*
- Review reason codes come from substring matching on warning text (pipeline.py:678-705), so rewording a warning silently changes the gate.
- `--accept-review empty_chapter` is book-wide and permanent: a different chapter that becomes empty later is skipped without a gate (pipeline.py:741, 945-958).

*Required:*
- The extractor and structure layers return reason codes as structured data (for example `ExtractedDocument.review_reasons`). The pipeline never parses warning strings to decide a gate.
- **Decision (fourth review):** an empty chapter is cleared only by approving that chapter.
  - Remove `empty_chapter` from the codes `--accept-review` accepts. `--accept-review empty_chapter` exits 2 before any work, with a fixed message saying to approve the chapter in the review UI.
  - `--accept-review` and the review UI's acknowledgement control accept only the book-wide codes (`damaged_source`, `ambiguous_page_numbers`; see R80).
  - Per-chapter approval already exists and covers only that chapter, so a chapter that becomes empty later is gated again.
  - An approved empty chapter is skipped with a report entry, as today.
- **No manifest schema change.** `review_required` and `review_acknowledged` stay as they are in v3. If an existing manifest has `empty_chapter` in `review_acknowledged`, convert ignores that entry and emits a content-free warning event saying the empty chapters need approval. The entry stays in the file and is never treated as an acknowledgement.

*Tests (new):*
- reword the damaged-source warning in a test double, and the gate still fires;
- `--accept-review empty_chapter` exits 2 with no workspace changes;
- a v3 manifest that has `empty_chapter` in `review_acknowledged` gates its unapproved empty chapter and emits the warning event;
- approve chapter 2 (empty), then empty chapter 3 by hand, and convert refuses chapter 3 while skipping chapter 2.

## 4. CLI, configuration and logging

**R89 — The catch-all never swallows `typer.Exit` (H) (confirmed; regression from FX8.03a).**
*Problem:*
- `batch` raises `typer.Exit(code=7)` inside `try: … except Exception` (cli.py:689-694).
- `typer.Exit` subclasses `RuntimeError` (typer 0.27.3), so the catch-all routes it to `fail()`.
- `batch books/` with one invalid PDF therefore exits 1, with `{"type": "Exit", "message": "Unexpected internal error"}` on stderr, instead of 7.

*Required:*
- Every command re-raises `typer.Exit` (and `click.exceptions.Exit`) before the generic handler.
- Audit every `raise typer.Exit` in cli.py.

*Tests (new):*
- `batch` with one bad book exits 7 with one JSON value on stderr in `--json` mode;
- a parametrized test over every command's non-zero `typer.Exit` path asserts the intended code.

**R90 — stderr holds one JSON value in `--json` mode, and starts with "Error:" in human mode (M) (confirmed; amends R72).**
*Problem:*
- `--quiet` turns off the default log policy, so `command_failed` is printed (logging.py:108-111, cli.py:113).
  - `--quiet … --json` puts two JSON values on stderr.
  - In human mode, `--quiet` stderr starts with `{"event":"command_failed"…}`.
- In `--json` mode, a configuration warning followed by a failure also produces two JSON values (probe: `cache.directory` set, then `analyze missing.pdf --json`).
- FX9.07b is checked although its human-readable rendering was never built.

*Required:*
- `--quiet` never adds output. It shows only the command's own error, exactly as the default policy does on failure.
- **In `--json` mode without `--verbose`,** stderr on failure is exactly one JSON value: the error object. Warnings raised during the command go into a `warnings` array of codes in that object, or of the success object on stdout. They are not printed as separate lines. This changes the `--json` output contract: document the `warnings` array in README.md and in parent spec §8 in the same commit.
- Events emitted before the output mode is known are buffered and then rendered for that mode.
- **In human mode without `--verbose`,** warnings are printed as human-readable `Warning: …` lines (fixed text, no content), and a failure's stderr ends with the `Error: …` line. No JSON appears in human-mode stderr unless `--verbose` or an explicit `general.log_level` is set.
- **With `--verbose` or an explicit `general.log_level`,** structured events appear as today.
- Remove the R72 decision text that says log level can be set by "file, environment or flag" unless an environment variable and flag are actually added.

*Tests (new):*
- `--quiet` and `--json` on a failing command gives one JSON value on stderr;
- `--quiet` in human mode gives stderr starting with "Error:";
- a configuration warning plus a failure in `--json` mode gives one JSON value containing the warning code;
- the same in human mode gives `Warning:` and `Error:` lines and no `{`.

**R91 — One failure, one exit code (M) (confirmed).**
*Problem:* An unusable `--output` (an existing file used as a parent directory) gives three different results:
- `analyze` exits 4;
- `convert` exits 6 with the unrelated message "Could not create or update chapter audio" (cli.py:561);
- `convert --dry-run` exits 1, because the dry-run's `analyze_book` call isn't wrapped (cli.py:529).

Separately, `batch` maps every `OSError` to 6 (cli.py:675).

*Required:*
- Workspace and output-directory failures raise one typed error with a fixed, context-specific message ("Cannot create the output workspace"), and use the exit code `analyze` uses today in every command (`analyze`, `convert`, `convert --dry-run`, `batch` per book, `review`, `pack-m4b`).
- `batch` records that code per book.

*Tests (new):* a parametrized CLI test over those commands with an unusable `--output`, asserting the code and message in text and JSON modes, and that no path or errno text appears.

**R92 — Configuration robustness (L) (confirmed).**
*Problem:*
- **URL redaction leaks part of a password.** `urlsplit` cuts the netloc at a raw `#`, `?` or `/`, so `http://user:pa#ss@host:1/v1` prints `pa#***` and `http://user:pa/ss@host:1/v1` prints unredacted (config.py:427-439).
- **A nested non-table section plus an environment override exits 1.** With TOML `[tts]\nkitten = 5` and `PDF2AUDIOBOOK_TTS_VOICE=x`, `_apply` raises `TypeError` (config.py:246-249), which surfaces as "Unexpected internal error" instead of a config error (exit 2).
- **The secret-path test is vacuous.** No config field is marked secret, so `_SECRET_CONFIG_PATHS` is empty, the FX9.15c "every listed path exists" test checks nothing, and the redaction branch at config.py:418 is never run.

*Required:*
- Before parsing, redact everything between `://` and the last `@` in the authority part of any URL-valued field. If the value can't be parsed as a URL, redact all of it.
- Report a non-table value at any section depth as a content-free `ConfigError` (exit 2), whether or not an environment override targets it.
- Either mark the real secret fields, or replace the vacuous test with one that registers a test-only secret field and shows it is redacted in `config show` and `config show --sources`.

*Tests (new):*
- URLs with `#`, `?`, `/` and `@` in the password are fully redacted;
- the nested non-table section with and without the env override exits 2;
- a non-vacuous secret-field redaction test.

**R93 — Every boolean switch has both forms on every command that uses it (L) (confirmed; completes R24).**
*Problem:* `analyze` and `batch` read `general.resume` (pipeline.py:310) but only `convert` has `--resume/--no-resume`, so TOML `resume = false` can't be overridden there.
*Required:* Add the paired option to `analyze` and `batch`, defaulting to unset, and audit every boolean setting the pipeline reads for a missing pair.
*Tests (new):* negative and positive flags override TOML values for `resume` on `analyze` and `batch`.

**R94 — Group help pages have examples (L) (confirmed; completes R33).**
*Problem:* `budget --help` and `config --help` (the command groups) contain no example. R33 names `budget`.
*Required:* Every command group's help includes an example line.
*Tests:* extend the FX7.01 help test to command groups.

**R95 — `budget` CLI edge cases (L) (confirmed).**
*Problem:*
- `budget show` exits 5 ("Unsupported … schema version") on a pre-v3 ledger, because the read-only path requires v3 (budget.py:36-38). That is exactly the ledger whose NULL-bound rows R70 says to fix with `budget resolve`.
- Resolving a missing ID, or a row that is already complete, gets the misleading message "Resolved values are invalid or exceed ledger limits" (cli.py:212).

*Required:*
- `budget show` reads every ledger version this release can write or has written, read-only.
- `budget resolve` refuses v2 and earlier ledgers with the fixed message "Legacy budget ledger cannot be resolved; re-create the ledger". This avoids modifying an old ledger before the user confirms a current-version workspace.
- A missing ID and an already-settled row each get their own fixed message and exit 2.

*Tests (new):* `show` on a v2 ledger; `resolve` of a missing ID; `resolve` of a complete row.

## 5. Extraction and structure

**R96 — One list classifier that respects footnotes and initials (M) (confirmed; regression from 5c8eff7).**
*Problem:*
- **Numbered footnotes become list items.** The per-page sequential-marker override in `_build_page_blocks` (pdf.py:1014-1015) turns two small-type notes, "1. First source note." and "2. Second source note.", at the foot of a page into `kind="list"`. They were `footnote` at 7eb4d25 and 2904f19. `--footnotes omit/end/inline` and the anchor-digit edits then silently ignore them.
- **Initials become list items.** The same override turns consecutive lines starting "A. Smith …" / "B. Jones …" into a list, splitting the paragraph (pdf.py:922-942). R46 forbids this.
- **Wrapped number lines split paragraphs.** The join check still uses the single-line `is_list_line` (structure.py:1519). "…held on May" followed by "12. Then he left the room." splits, and so does "…page" followed by "42) and later.".
- **A list swallows the next paragraph.** A body line at the list's left margin in the same font is joined onto the last item (structure.py:1526-1538), giving "2. Second item. The body paragraph begins here.".
- **There are two list classifiers.** `is_list_line` and the sequential logic in `_build_page_blocks`, which goes against R44.

*Required:*
- **One list classifier** in the structure layer, used both for block kinds and for the join check.
- **Footnotes first.** Footnote classification (small type in the page's foot band) runs before list detection. A footnote is never reclassified as a list.
- **A list item needs** a run of at least two sequential markers, each followed by text that isn't a capitalized name (for example "Smith" or "Jones"). Single capitals followed by a name are never markers.
- **A wrapped line joins** the previous line when the previous line doesn't end a sentence and the next line's marker isn't part of a sequential run.
- **A list ends** at a blank line, a font change, or a line whose left edge is at or left of the markers' left edge and doesn't start with the next marker.

*Tests (new):*
- numbered small-type footnotes stay `footnote`, and `--footnotes omit` removes them;
- "A. Smith …" / "B. Jones …" stays one paragraph;
- the "May / 12." and "page / 42)" wraps join;
- a list followed by a same-margin body line keeps the paragraph separate;
- every existing list and heading test passes unchanged.

**R97 — Page-number ambiguity counts only candidates (M) (confirmed).**
*Problem:*
- **A false warning blocks the whole book.** `numeric_counts` (structure.py:654-697) counts every numeral in a margin band, including ones in tables, lists, headings and large type. When a band has two numerals but neither is a candidate, the ranked list is empty and the band is marked ambiguous. One page with two table-cell numerals at its foot emits "Equally positioned margin numerals retained". That maps to `ambiguous_page_numbers` (pipeline.py:698-705) and blocks every unapproved chapter.
- **The label-mismatch warning fires when it shouldn't.** It is raised when a *rejected* sequence disagrees with the PDF page labels, even though the chosen sequence matches them exactly (structure.py:784-794; the sonnet fixture).
- **Ties need exact float equality.** Edge distances of 18pt and 18.4pt are not a tie, so one sequence is removed without a warning (structure.py:690, 777).

*Required:*
- Ambiguity is decided only among page-number candidates (blocks that pass the folio candidate test). Non-candidate numerals never make a band ambiguous.
- The label-mismatch warning compares only the chosen sequence with the labels.
- Treat edge distances within a named tolerance (start at 2pt) as tied; document the constant in MAINTAINER_GUIDE.md.

*Tests (new):*
- two table-cell numerals at the foot produce no warning and no review reason;
- the sonnet fixture gives no label-mismatch warning;
- 18pt vs 18.4pt is a tie and warns;
- the existing page-number tests pass unchanged.

**R98 — OCR selection keeps short valid text (M) (confirmed by the reviewer's probe).**
*Problem:*
- **An ornament forces OCR.** A born-digital page with "Part One" and a small ornament of 40 or more filled paths is sent to OCR by the dense-vector rule (pdf.py:618-628). Without Tesseract, the whole analysis fails with "OCR failed on PDF page 1". This contradicts R4 and parent spec §4.1 ("keep short valid selectable text").
- **The warnings are misleading.** With `--ocr never`, a dense vector page warns "attempting OCR" and then "no readable text (OCR disabled)". A page with a single rule is reported as "no text or drawings found".
- **The drawing checks are unbounded and repeated.** `_page_has_dense_vector_art` has no item cap, unlike its sibling checks, and `get_drawings()` is called about four times per page.

*Required:*
- The glyph-like-drawings rule applies only when the page has no usable embedded text. A page with usable text is never OCRed in auto mode because of its drawings.
- Warnings name the actual outcome:
  - "OCR disabled" when `--ocr never`;
  - "drawings present but not text-like" for a page with a rule or a figure;
  - "no text or drawings" only when both counts are zero.
- Compute each page's drawings and image information once, with the same item cap as the other checks.

*Tests (new):*
- a "Part One" page with a 48-path ornament analyzes with Tesseract unavailable and has `embedded` origin;
- `--ocr never` on an outlined page doesn't say "attempting OCR";
- the single-rule page's warning wording;
- a 10,000-path page is bounded (the check stops at the cap).

**R99 — Extraction code health (D).**
*Required:*
- Remove dead code: `nearer_edge_than_body` (structure.py:450), and `chapter_text` (structure.py:1224) if only tests use it.
- Stop importing the private `_valid_box` from special_material; make it public, or move it.
- Build the Roman-numeral sets and maps once, at module level (pdf.py:943-966).
- Move the OCR-fallback block out of `extract_pdf` (pdf.py:1035-1267) into a named step, as FX2.01b intended.
- Make `_classify_block_kind` the only place that decides a block's kind (today `_build_page_blocks` overrides it, pdf.py:1003-1019).

*Tests:* the full suite passes unchanged; no behaviour change.

## 6. LLM budget and providers

**R100 — The JSON-mode fallback settles `rejected` and is remembered (M) (confirmed by reading).**
*Problem:*
- When a server rejects `response_format`, the attempt is settled with `finish_attempt()` and no usage (llm/__init__.py:504-510). It becomes `unknown`, not `rejected` as R49 requires, and is charged at its full worst-case bound.
- The fallback flag is local to each call (llm/__init__.py:488), so every later request repeats the rejected attempt.
- Probe: three calls against such a server stored `[unknown, complete] × 3`, charging 711 tokens against 18 used. Under `max_reported_tokens` the budget burns about 10× faster than real use, and the unknown rows pile up until resolved by hand.

*Required:*
- A JSON-mode rejection (a 4xx other than 408 and 429, with no usage) is settled `rejected`.
- The fallback is remembered per provider identity, in the same capability store as rejected parameters, so later requests omit `response_format` from the start.

*Tests (new):* three requests against a stub that rejects `response_format` give one `rejected` row and three `complete` rows, and the capability is persisted across provider instances.

**R101 — The ledger rejects cumulative overflow at settlement (M) (confirmed by the reviewer's probe).**
*Problem:*
- `settle()` checks each usage counter against 2^63−1 but never the cumulative total (budget.py:291-310).
- The provider path passes raw `usage` rather than the overflow-filtered `last_usage` (llm/__init__.py:567).
- Two responses that each report `prompt_tokens = 2^62` make `totals()`, `rows()` and `reserve()` fail with "Cumulative token totals exceed supported range".
- `budget resolve` can't repair `complete` rows, so `budget show` and every LLM run fail, even with no budget configured, until someone edits SQLite by hand.
- Provider output is untrusted (CLAUDE.md). This is the same failure class R71 fixed for `resolve`.

*Required:*
- Inside the settlement transaction, check that every stored total, including the new values, stays within the 64-bit and `Decimal` limits.
- If not, settle the row `unknown` with its upper bound, so it fails closed and can be resolved, instead of `complete`.
- Settlement uses the same validated usage that the in-memory totals use.

*Tests (new):* two 2^62-token responses leave a ledger where `budget show` works, the second row is `unknown`, and `budget resolve` can settle it.

**R102 — `reserve` fails closed without a bound under any budget (L) (confirmed; amends the R70 decision).**
*Problem:* Under a token budget, `reserve()` skips the token check when `upper_bound_tokens is None` (budget.py:241-246), while a missing USD bound is refused (budget.py:248). Production always passes a bound, but the ledger API isn't fail-closed by itself. Several `…_blocks_…` tests block only because of this asymmetry, not because of the condition they are named for (test_llm_budget_settlement_types.py:21, test_llm_budget_integer_bounds.py:18).
*Required:*
- Under a token or USD budget, `reserve` without the matching bound raises a content-free `LLMError`. Without a budget, a missing bound is allowed.
- Amend the R70 decision text in the previous review spec to match.
- Fix or rename the tests whose names describe a condition they don't test, following the §2 rule (add new truthfully named tests rather than changing their inputs).

*Tests (new):* an unbounded `reserve` under a token budget is refused; the renamed or added tests assert their named conditions.

**R103 — Provider parameter detection doesn't misfire (L) (suspected).**
*Problem:*
- (Suspected) `_unsupported_parameter` (llm/__init__.py:275-296) treats any 400 whose message contains "invalid" or "unknown" plus a parameter name as an unsupported parameter, and that result is persisted per provider identity. A context-length 400 that mentions `max_tokens` could permanently switch a provider to `max_completion_tokens`. A server that silently ignores that field would then generate uncapped output while the ledger assumes the cap.
- (Confirmed) `_model()` (llm/__init__.py:237-243) silently picks `models[0]` when the provider is used directly with `model = "auto"`, for example by the smoke CLI.

*Required:*
- First add a test with a context-length 400 that mentions `max_tokens`. If it shows the misfire, require an explicit unsupported-parameter phrase for the matched parameter, and never persist a capability from a context-length error.
- `_model()` uses the same resolver as the pipeline and raises `LLMError` when the model is ambiguous.

*Tests (new):* the context-length case; `auto` with two served models raises through the real `resolve_model` (not a stub).

**R104 — LLM code health (D).**
*Required:*
- Split `_complete_json_request` (llm/__init__.py:428-626) so that each settle path (success, retryable, rejected parameter, JSON-mode fallback, non-retryable) is a named function returning a typed outcome.
- Replace the bare `str` outcome (llm/__init__.py:180, 500) with a `Literal` type.
- Write the usage-validation predicate once and use it in cache.py, budget.py and the provider (it is repeated four times today).
- Build the capability-file path in one place (cache.py:148-152, 169-173).
- Write the capability file only when it changes (today it is rewritten on every request, even with the cache disabled, cache.py:380).
- Delete the no-ledger budget path in cache.py if the pipeline never uses it. If it stays, give it the same per-attempt semantics as the ledger path.

*Tests:* the full suite passes unchanged.

## 7. Audio and TTS

**R105 — Every unspeakable paragraph becomes a pause (L) (confirmed; completes R37).**
*Problem:* Only `* * *` (`_SCENE_BREAK`, audio/__init__.py:128) becomes a `kind = "pause"` entry. Other paragraphs with no letters or digits (`# # #`, `~~~`, `• • •`, `———`, `⁂`) are silently skipped, with no pause entry and no count.
*Required:* A paragraph whose spoken form has no letters or digits becomes one pause entry, is counted in `pause_count`, and makes no TTS call.
*Tests (new):* each listed form makes one pause entry and no TTS call, and coverage still passes.

**R106 — Narration rules, remaining cases (L) (confirmed).**
*Problem:*
- **Em-dash-joined words skip pronunciations.** `_spoken_sequence` strips dashes only at word edges (audio/__init__.py:169), so `said—Hermione` is spoken "said, Hermione" even with a `hermione` key.
- **Typographic apostrophes never match.** The config keeps the key `o’brien` (config.py:162), but the lookup token is normalized to `O'Brien` (audio/__init__.py:244).
- **"Dr.?" is spoken "Doctor.?".** A pronunciation key ending in `.` gets doubled sentence punctuation at the end of a paragraph (audio/__init__.py:266-285).
- **Ordering:** the digit-range rule runs before invisible characters are stripped, so `1–<U+200B>2` is spoken "1, 2".
- **Bare dashes in quotes and brackets read oddly:** `"—"` becomes `", "` and `(—)` becomes `"(, )"`.
- **The key `...` is accepted at config load.**

*Required:*
- Split on internal em dashes and non-digit en dashes before pronunciation lookup.
- Normalize pronunciation keys with the same narration table as tokens.
- A key ending in `.` followed by `?` or `!` keeps only the `?` or `!`.
- Strip invisible characters before any rewrite rule runs.
- A dash with no word on either side becomes a pause (silence) and not a comma.
- Reject keys made only of punctuation at config load.

*Tests (new):* one test per bullet. Extend the alignment property test (test_audio_speech_alignment.py:45) to include pronunciations and chunk sizes from 20 to the default.

**R107 — Bounded progress bookkeeping (L/M) (confirmed by the reviewer's probe).**
*Problem:*
- `synthesize_chunks` rewrites the whole progress JSON after every chunk (audio/__init__.py:727), which is quadratic in chapter length.
- The pipeline reads that file back with a 1 MiB cap (pipeline.py:1186). A chapter of about 420k characters produced a 1.11 MB progress file, `load_bounded_json` returned `None`, and `pause_count` (0) and `chunk_mapping` (`[]`) were silently wrong.
- `inspect` caps `conversion_status.json` at 1 MiB (cli.py:286), so a very long book would silently hide its failed chapters.

*Required:*
- Progress writes are linear in the number of chunks: for example, an append-only JSON-lines log, or per-chunk records, each read with a per-record cap.
- When any bounded read hits its cap, emit a content-free WARNING and mark the affected report fields as unavailable rather than zero or empty.
- `inspect` reports that the status file is too large instead of showing nothing.

*Tests (new):* a synthetic 500k-character chapter with a no-op TTS keeps the correct `pause_count` and finishes within a time budget; an oversized status file makes `inspect` print the fixed "too large" message.

**R108 — Voice listing failures are errors (L) (confirmed; R60 spirit).**
*Problem:* Kitten's `list_voices` turns exceptions into `[]` (tts/__init__.py:79-87), and the pipeline treats `[]` as "skip validation" (pipeline.py:1000). A Kitten metadata failure therefore silently disables voice-marker validation.
*Required:* `list_voices` raises a content-free `TTSError` on failure. The pipeline skips validation only for providers that declare they have no voice list. An approved marker with a failed voice listing fails its chapter with reason `voice_list_unavailable`.
*Tests (new):* a Kitten stub whose voice listing raises fails the marker chapter, exit 7.

**R109 — Small audio fixes and code health (L/D).**
*Required:*
- **Cover image:** read it once per run, hash it once, and pass the bytes and hash to `chapter_audio_fingerprint` (today the file is read twice per chapter, pipeline.py:829). Changing the file mid-run can't make the embedded art differ from the fingerprinted hash.
- **WAV size guard:** stop using CPython's private `wave.Wave_write._datawritten` (audio/__init__.py:72, 81). Track the bytes written yourself.
- **Progress status after a size-limit error:** the failing chunk is not marked `completed`, and the progress status becomes `failed`.
- **Naming:** rename the two `narration-normalization` constants so their roles are clear: the WAV chunk table in audio/__init__.py:97 and the chapter-audio version in pipeline.py:809.
- **Dead code:** remove the `output_wav is None` check at audio/__init__.py:745.
- **Duplication:** extract the TTS provider construction (pipeline.py:987-992, 1115-1119) and the provider voice and speed selection (pipeline.py:826, 1130; cli.py:495-507, 653-660) into one function each.

*Tests (new):* the cover is read once per run (counted with a monkeypatched `read_bytes`); after a size-limit error the progress status is `failed`.

## 8. Test integrity and coverage

**R110 — Close the test gaps behind checked items (T).**
Each test below is new, must fail (or be shown not to apply) at 6eedfa4 where a code change accompanies it, and is listed against the item it backs.

| Item | Missing or non-discriminating test | Required test |
| --- | --- | --- |
| FX0.03c | Every chapter gets the same boundary warning (test_outline_led_chapters.py:69) | Only the low-confidence chapter carries the warning |
| FX1.02b / FX8.16b | The Node-run page body is never posted to the server | Post the body the page's own script builds (Node-gated) and assert voices are kept and edited |
| FX3.01b | No unedited chapter; the edited start isn't asserted | One edited and one unedited chapter, reanalysis recomputes the unedited one and keeps the edit |
| FX4.01d | "Resolve unblocks the run" never shows the run was blocked | Assert the block before `resolve`, then success after it |
| FX8.02c / FX9.16a | The R47 folio tests pass at 2904f19, and "near body text" has no nearby body | A folio within 12pt of body text that fails at 2904f19 |
| FX8.06d | "Unblocked by approval" isn't tested; the damaged acknowledgement test stubs `select_chapters` | Through the real gate: blocked, then unblocked by acknowledgement (R80) |
| FX8.08c | No retry flow at the exact worst-case limit | A retry at limit 460 is allowed and 459 is refused, in one request flow |
| FX8.09a | `pending` rows are resolved only at ledger level | `budget resolve` of a `pending` row via the CLI with `--confirm` |
| FX8.09b | `resolved_model` in the usage report is untested | Assert the field in `reports/llm_usage.json` |
| FX8.14a | No R56 batch validation test | A batch profile with an invalid value exits 2 before `convert_book` |
| FX8.14e | No `OSError` injection; no chapter-level size-limit test | Both, asserting no temporary WAV remains |
| FX8.15a | Port 80 tested only through `_expected_authorities` | A server-level request with `Host: 127.0.0.1` on port 80 |
| FX8.15b | `review_warning` and `degraded_output` emission untested | A pipeline run that emits each at WARNING |
| FX9.03 | "D. H. LAWRENCE" can never match `_ROMAN_TITLE`; there's no whitespace-path test | Replace with a case that matches the pattern; add a whitespace-isolated one-letter numeral case |
| FX9.07c | `stage_started` never asserted | Assert `stage_started` with `--verbose` |
| FX9.14 | The outdented-paragraph list test passes without the fix | Covered by R96's same-margin case |
| FX9.17 | Fingerprint tests pin literals only | Changing the version constant changes the computed fingerprint |
| FX5.09 | "Warns once" isn't asserted by count | Count the warning events across two loads |

Also: rename `test_overspent_token_budget_still_fails_closed` and the exact-exhaustion test in tests/test_llm_exact_budget_boundary.py to describe what they assert, and add truthfully named tests for the post-flight overspend and exact-exhaustion cases.

**R111 — CI shows what ran (T).**
*Problem:*
- CI runs `pytest -q` (ci.yml:63), so the FX9.05a and FX9.19c instruction to "confirm in CI's `-ra` summary" can't be followed.
- CI doesn't install Node explicitly, so it isn't known whether the Node-gated page-script tests run.

*Required:*
- CI runs `pytest -q -ra`.
- CI either installs Node explicitly (pinned major version) or documents that the runner image provides it. The ledger cites the CI log lines showing the Tesseract, FFmpeg and Node tests ran.
- Update `/verify` and `docs/MAINTAINER_GUIDE.md` to match.

*Tests:* tests/test_ci_uv_pin.py (or a sibling) asserts `-ra` and the Node step are present in ci.yml.

## 9. Documentation and status record

**R112 — Correct the documentation and status record (T/D) (confirmed).**
*Required:*

*README.md:* rewrite the budget section (about lines 199–212) to match the current behaviour:
- unresolved rows are charged at their upper bound and can be fixed with `budget resolve`;
- each HTTP attempt has its own ledger row;
- `rejected` rows exist;
- remove the advice to reset the ledger by hand.

Document the paired `--no-*` forms and the `budget resolve` syntax.

*docs/PDF2AUDIOBOOK_SPEC.md:*
- add R31's logging-level mapping to §7, as amended by R90;
- add R75's identity matching to §5, as amended by R81;
- fix §6.3 (line 191), which says unresolved calls "block token and cost budgets until reviewed", contradicting the next sentence.

*docs/MAINTAINER_GUIDE.md:*
- remove the stale "fingerprint v20" sentence next to the `analysis-v21` note (about lines 255–260);
- document R75/R81 matching;
- keep earlier upgrade notes rather than overwriting them: restore the analysis v19 and mp3-v5 notes as history.

*docs/PDF2AUDIOBOOK_REVIEW_FIXES_SPEC.md:* amend R79 to record the FX9.16d decision to keep the R47 page-number inversions, and the FX9.02c decision on the two budget tests (R102 supersedes the latter).

*docs/PDF2AUDIOBOOK_REVIEW_FIXES_TODO.md*, in one `docs:` commit before any FX10 fix:
- uncheck the items this review found wrong or partial (TODO FX10.00) and their parents;
- reword FX8.18 as "superseded by FX9.18" and uncheck it;
- append correction rows (never edit existing rows) saying that:
  - the FX9.00 row labelled `1530a35` was written in 1e73dbe;
  - the FX9.19a row labelled 597ed1c was written in 6eedfa4;
  - CI run 40214615871 for 6eedfa4 succeeded and wasn't recorded;
  - the "N failed at the parent" counts in the FX9 rows include parametrized cases;
- update the status line.

*docs/PDF2AUDIOBOOK_TODO.md*, in the same commit:
- uncheck P0.03c and P4.01b (they cite FX5.06, whose FX5.06a is open);
- uncheck F.06's voice-marker subitem (it cites FX6.06, whose FX6.06a is open);
- name P5.05 and F.01 in the status line alongside F.06;
- update the `Date` line;
- append a ledger row.

Leave the mis-placed rows at lines 163–164 and the edited "worktree after 1664fdd" row as they are, and append a correction row saying that row's mypy count should be 19.

## 10. Coordinated breaking changes

Make each bump **once**, in the phase that introduces it, and record it as an upgrade note in docs/MAINTAINER_GUIDE.md:

| Bump | Covers | Effect on existing workspaces |
| --- | --- | --- |
| Manifest schema | None. R88 uses per-chapter approval instead of a scoped acknowledgement, and R81 keeps the existing `generated_*` fields consistent. | v3 manifests stay valid; a stale `empty_chapter` acknowledgement is ignored with a warning (R88) |
| Extraction/analysis fingerprint (`analysis-v22`) | R82 (fingerprint composition), R96, R97, R98 | Analysis is recomputed; approved workspaces are protected as usual |
| Chapter audio fingerprint and MP3 sidecar version 3, made together in one task | R84 (recorded rendering inputs), R105, R106 | Chapter audio is regenerated once on the next convert; `pack-m4b` treats v2 sidecars as stale |
| LLM capability store | R100 (JSON-mode fallback remembered) | No cache-identity bump: existing capability files gain a key; old files still load |
| Budget ledger | R101, R102 | No schema change; R95 decides how `budget resolve` handles legacy ledgers |

## 11. Amendments to the parent specification

Merge these into docs/PDF2AUDIOBOOK_SPEC.md in the same commit as the fix each one describes:

| Parent section | Amendment | From |
| --- | --- | --- |
| §5 (review and approval) | Book-wide review reasons are cleared only by explicit acknowledgement; chapter approval never waives them. Hand edits are matched by generated identity before edits are applied; conflict messages say approve or revert. Rejected deterministic edits are preserved. Empty chapters are cleared only by approving the chapter; `--accept-review` accepts only book-wide codes. | R80, R81, R87, R88 |
| §5 (resume) | Gate-only settings and disabled-LLM settings are outside the analysis fingerprint; `--no-resume` on an approved workspace keeps approved analysis. | R82 |
| §7 (logging) | Logging-level mapping, `--quiet` semantics, and warnings inside the `--json` object. | R90 |
| §8 (CLI) | Exit-code consistency for workspace failures; `--resume/--no-resume` on `analyze` and `batch`; dry-run equals convert; workspace lock covers analysis and review saves; `pack-m4b` omits skipped chapters; the `--json` output objects carry a `warnings` array. | R83, R84, R85, R90, R91, R93 |
| §4.1–§4.2 (extraction) | Footnotes before lists; one list classifier; page-number ambiguity among candidates only; edge-distance tie tolerance; drawings never force OCR on a page with usable text. | R96, R97, R98 |
| §6.3 (budget) | JSON-mode rejection is `rejected`; settlement rejects cumulative overflow; `reserve` without a bound under a budget is refused. | R100, R101, R102 |
| §9 (audio) | Any unspeakable paragraph is a pause; sidecars record rendering inputs. | R84, R105 |

## 12. Out of scope

- **Piper speaker-count validation** stays deferred at the user's request (previous FX5.06a, FX6.06a, FX8.14c, FX9.12c). FX10 doesn't reopen it.
- **Live OpenAI and llama-server checks** (original P5.05) stay deferred.
- **Migrating manifests or ledgers** between versions is out of scope; old versions are rejected (R95 may choose an in-place ledger upgrade only for `budget resolve`).

## 13. Traceability

| Fourth-review finding | Requirement | Previous items to reopen |
| --- | --- | --- |
| Review-UI save waives `damaged_source` / `ambiguous_page_numbers` | R80 | FX8.06b, FX9.09a, FX9.09b |
| Valid boundary edit / title-only edit fails reanalysis | R81 | FX3.01a, FX3.01b, FX8.12a, FX8.12c, FX9.11b |
| `min_boundary_confidence` fingerprinted; misleading `--no-resume` error | R82 | FX3.02a |
| Dry-run differs from convert | R83 | FX9.10a, FX9.10b |
| `pack-m4b` can't package skipped chapters; footnote policy mismatch | R84 | FX8.12b |
| Lock taken after analysis | R85 | FX9.12a, FX9.12b |
| Dangling symlink aborts convert | R86 | FX3.04b |
| Rejected deterministic edits re-accepted | R87 | — (new) |
| Reasons from warning substrings; permanent `empty_chapter` acknowledgement | R88 | FX8.06b, FX9.10a, FX9.10b |
| `batch` exits 1 instead of 7 | R89 | FX8.03a |
| `--quiet` and warnings break one-JSON stderr; no human rendering | R90 | FX5.08a, FX9.07b, FX9.07c |
| Three exit codes for one output-path failure | R91 | FX1.04b |
| URL redaction with `#?/`; nested non-table crash; vacuous secret test | R92 | FX1.05a, FX5.01, FX9.15c |
| No `--resume` pair on `analyze`/`batch` | R93 | FX5.05a |
| No examples on group help | R94 | FX7.01 |
| `budget show` on legacy ledger; resolve messages | R95 | FX4.01c |
| Numbered footnotes as lists; initials; wraps; list absorbs paragraph | R96 | FX8.04a, FX8.04b, FX9.14a, FX9.14b |
| False page-number ambiguity; label warning; exact ties | R97 | — (new; FX8.05 stays checked) |
| Ornament forces OCR; misleading warnings | R98 | FX2.04a, FX8.06c, FX9.05b |
| Two list classifiers; dead code; long `extract_pdf` | R99 | FX2.01b |
| JSON-mode fallback `unknown` rows | R100 | — (new) |
| Cumulative overflow at settlement | R101 | — (new) |
| Unbounded `reserve` allowed; mis-named tests | R102 | FX9.02c |
| Parameter detection misfire (suspected); `_model()` picks first | R103 | — (new) |
| Only `* * *` is a pause | R105 | FX6.03, FX8.15c |
| Remaining narration cases | R106 | — (new; FX9.13 stays checked) |
| Progress file and status caps | R107 | FX8.15c |
| Kitten `list_voices` swallows errors | R108 | — (new) |
| Test gaps behind checked items | R110 | FX0.03c, FX1.02b, FX4.01d, FX8.02c, FX8.06d, FX8.08c, FX8.09a, FX8.09b, FX8.14a, FX8.14e, FX8.15a, FX8.15b, FX8.16b, FX9.16a |
| CI lacks `-ra`; Node not explicit | R111 | FX9.05a, FX9.19c |
| README, spec, guide drift; status and ledger | R112 | FX5.10, FX7.02a, FX7.02c, FX7.03, FX8.18, FX9.19a, FX9.19b |
