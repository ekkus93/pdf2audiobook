# PDF2Audiobook Citation and Equation Review Fixes TODO

**Status:** Not started
**Date:** 2026-10-28
**Baseline:** master at 686bd06
**Specification:** `docs/PDF2AUDIOBOOK_CITATIONS_EQUATIONS_REVIEW_SPEC.md` (Q1–Q9)
**Previous TODO:** `docs/PDF2AUDIOBOOK_CITATIONS_EQUATIONS_TODO.md`

## Working rules

- Work in the order below. Use `[x]` only when the implementation exists and its named tests pass; check a parent only when all of its subitems are checked.
- Every fix task has three parts:
  - (a) add the regression tests, run them against the parent commit, and record the failing test IDs in the ledger;
  - (b) make the fix;
  - (c) run `/verify`.
- One fix per commit, with its tests. Conventional Commits with a scope, lowercase imperative subject, no body. Docs-only status changes go in their own `docs:` commits.
- Never change an existing test's inputs or expected results to make a change pass, except where the spec names the change (the Q5 fingerprint token); state the reason in the commit message.
- After every push, check the CI run for that SHA, and fix a failure before starting the next task.
- Errors, warnings and `--json` stay content-free; add a privacy test for each new message. Fixtures are synthetic, and the real paper and its audio are never committed. CI stays offline.

## 1. Literal text in `edits list` (Q1)

- [x] 1.1 Tests: an edit containing `x[i]`, `[/b]`, `[bold]` and `[13]` lists with exit 0 and every bracket verbatim; `--json` is unchanged.
- [x] 1.2 Escape book-derived fields (or print them without markup) in the human `edits list` output.

## 2. Rejected built-in edits (Q2)

- [x] 2.1 Tests with one accepted built-in edit, one rejected built-in edit, one pending LLM cleanup edit and one pending equation edit:
  - `list` and `--status rejected` show the right rows;
  - `accept --all` and `reject --all` act only on the two LLM edits;
  - the rejection stays in the manifest, and reanalysis still preserves it;
  - naming its block is exit 2, content-free.
- [x] 2.2 Add the `rejected` status and keep `accept` and `reject` to pending edits, in `edit_review.py` and the `--status` option.

## 3. One accepted edit per block (Q3)

- [x] 3.1 Tests:
  - a block with an accepted edit refuses another accept, by ID and with `--all`, with manifest, chapters and audio byte-identical;
  - two pending edits on one block refuse `--all`;
  - the message names only the block ID.
- [x] 3.2 Check both conditions in `_select` for explicit IDs and `--all`, before any change.

## 4. Reported audit failures (Q4)

- [x] 4.1 Tests:
  - with the audit write failing, accept and reject still exit 0 and save their decision;
  - the human warning and the JSON warning code appear, with no path or exception text;
  - a corrupt audit file is replaced.
- [x] 4.2 Catch only `OSError` and the bounded-JSON errors, return the failure to the CLI, emit the warning, and move the import to module level.

## 5. Math intervals (Q5)

- [x] 5.1 Tests:
  - `x ∈ [1, 5]`, `p = [2, 3]` and `a ≤ [4]` are kept;
  - `shown in [1, 5].` and `results [13]` are skipped;
  - the off-state goldens are unchanged;
  - the on-state fingerprint differs from a baseline golden, with the model identity pinned.
- [x] 5.2 Add the preceding-symbol rule to `audio/citations.py`, and bump `citations-skipped` to `citations-skipped-v2`. Add the upgrade note to `docs/MAINTAINER_GUIDE.md`.

## 6. Bibliography numbers and citation-only chapters (Q6)

- [x] 6.1 Tests:
  - a bibliography entry's leading `[1]` is skipped without altering chunking;
  - a two-chapter conversion whose second chapter is only citations completes chapter 1 and fails chapter 2 with the existing content-free error.
- [x] 6.2 Fix any failure the tests expose, keeping the per-chapter failure. Document both behaviors in the README and the maintainer guide.

## 7. Equation prompt (Q7)

- [x] 7.1 Test: the prompt describes records as lines or paragraphs, keeps the untrusted-content framing, and changes the cache key.
- [x] 7.2 Reword the prompt in `llm/equations.py`.

## 8. Accuracy of code comments and documents (Q8)

- [x] 8.1 Update the `Reading` docstring. Document in the README and the maintainer guide that accepting an equation reading makes the workspace approved content.
- [x] 8.2 Amend the C1–C5 spec: the status, the "opt-in" opening, and C1's "Defaults are false".
- [x] 8.3 Amend the C1–C5 TODO with dated notes on tasks 1.1, 2.6, 3.1 and 4.5 (4.5 stays ticked, superseded by 686bd06), and correct its status line.

## 9. Evidence and acceptance (Q9)

- [x] 9.1 Add the ledger rows to the C1–C5 TODO:
  - 686bd06 and CI run 693, stating that it was not test-first and naming the existing tests it changed;
  - the first 6.2 counts.
- [ ] 9.2 After sections 1–7, repeat the *Attention* acceptance from the cached analysis. Render one chapter with citations and accepted readings into `tmp/`, and ask the user to listen. Tick the C1–C5 TODO's 6.2 only with the user's confirmation.
- [ ] 9.3 Record the review as the C1–C5 TODO's 6.3: the findings fixed here and the remaining limitations.

## 10. Finish

- [ ] 10.1 Run `/verify`, plus mypy on Python 3.12 and 3.13, and the Kitten smoke test with `PDF2AUDIOBOOK_KITTEN_SMOKE=1`. Record the pass and skip counts.
- [ ] 10.2 Review the final diff against Q1–Q9, and record any unresolved limitations below.

## Unresolved limitations

(Filled in by 10.2.)

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
| 2026-10-28 | 357138593246cba8b8b27a72967ee5edd8bd1e66 | Spec and TODO committed. | Docs only. Run [694](https://github.com/ekkus93/pdf2audiobook/actions/runs/40653789817) passed. | None |
| 2026-10-28 | 0ca6295c1fb6e5ae88657a21f5944c5a071e33e9 | 1.1-1.2 (Q1): `edits list` escapes book text instead of parsing it as Rich markup. | Failing at parent: `test_book_text_with_brackets_lists_verbatim` (exit 1, "Unexpected internal error"). The JSON-listing test passed before and after, as intended. Run [695](https://github.com/ekkus93/pdf2audiobook/actions/runs/40654205466) passed. | None |
| 2026-10-28 | ffee0afcadeda1282d2e03a0e487ddc54cf13bba | 2.1-2.2 (Q2): a `rejected` status for unaccepted built-in edits; `accept` and `reject` act only on pending edits; naming a rejected edit is exit 2. | Failing at parent: the pending-listing case (it showed `a2`) and the `accept --all` case (it re-accepted `a2`); the other new Q2 cases were not individually recorded because the output was truncated. Replaced `test_a_pending_deterministic_edit_is_handled_the_same_way`, which asserted the bug, reason in the commit message. **Process slip:** the suite had one failure, `test_half_million_character_chapter_keeps_pause_count_with_linear_progress`, a wall-clock test (full run 122 s against the usual 66 s under load), and my command committed and pushed without being gated on the result. It passed alone and in a full rerun (1967 passed), and CI was green. Later commits were gated. Run [696](https://github.com/ekkus93/pdf2audiobook/actions/runs/40654926037) passed. | None |
| 2026-10-28 | d1d4e23d3069a36cd2c3a3bd5ef28424ac084f2a | 3.1-3.2 (Q3): `accept` refuses a block that already has an accepted edit, and `--all` also refuses two pending edits on one block; all-or-nothing. | Failing at parent: `test_accepting_a_second_edit_on_a_block_is_refused_by_id_and_by_all` and `test_two_pending_edits_on_one_block_refuse_accept_all`; the single-edit control passed. Reject by ID on a doubled block was left as it was. Run [697](https://github.com/ekkus93/pdf2audiobook/actions/runs/40655449442) passed. | None |
| 2026-10-28 | 730fc088af94cba412416a0c17b06c90e36793f4 | 4.1-4.2 (Q4): a failed `edit_decisions.json` write warns (`edit_audit_not_written`) in human and JSON modes; only `OSError` is caught; the import moved to module level. | Failing at parent: the four failed-audit cases (accept and reject, human and JSON). The corrupt-file and success controls passed before and after, because the bounded loader already treats a corrupt file as a miss. Run [698](https://github.com/ekkus93/pdf2audiobook/actions/runs/40655939290) passed. | None |
| 2026-10-28 | 51ae888c20a3e72dd95cc46336db0366ad4730f4 | 5.1-5.2 (Q5): a bracketed list after `∈ = ≤ ≥ < > ≈ ×` is an interval; the on-state fingerprint part is `citations-skipped-v2`; upgrade note and README added. | Failing at parent: nine interval cases in `test_citation_detector.py` and `test_the_on_state_identity_changed_when_the_interval_rule_did`; the prose-context controls passed. The old on-state values are pinned as goldens, computed from the code before the change with the model identity pinned. No existing test changed. Run [699](https://github.com/ekkus93/pdf2audiobook/actions/runs/40656487348) passed. | None |
| 2026-10-28 | 9497c59b92b46a0897d84cb7c6c96aa2cb6f1ea7 | 6.1-6.2 (Q6): tests for bibliography entry numbers and a chapter of only citations; both behaviors documented. | Coverage only: the behavior was already correct, so the tests passed on first run once a mistake of mine was fixed (chunks pack sentences per paragraph, so my first expected list was wrong). A chapter cannot be citation-only through normal analysis, because its title stays speakable; the test hand-edits the chapter file, and `convert` reports `PartialConversionError` for that chapter only, content-free. Run [700](https://github.com/ekkus93/pdf2audiobook/actions/runs/40657177908) passed. | None |
| 2026-10-28 | 67a764986a0f0787abcc32bdecd423d303c62e28 | 7.1-7.2 (Q7): the equation prompt describes records as lines or paragraphs and asks for the whole record; its JSON example says "record". | Failing at parent: `test_the_prompt_describes_records_as_lines_or_paragraphs`. The prompt is part of the LLM cache key, so equation requests are sent once more. Run [701](https://github.com/ekkus93/pdf2audiobook/actions/runs/40657649005) passed. | None |
| 2026-10-28 | 91616ff672f36e7e6361e90cf728ddddfd7d5877 | 8.1: corrected the `Reading` docstring; documented that accepting an LLM edit makes the workspace approved content, the one-accepted-edit-per-block rule, the `rejected` status and the audit warning. | Docs and a docstring only; 1994 passed locally. Run [702](https://github.com/ekkus93/pdf2audiobook/actions/runs/40658170803) passed. | None |
| 2026-10-28 | 9fb5bde8ca2655b498cd42f71568ad371305b67d | 8.2: amended the C1-C5 spec (status, opt-in wording, C1 acceptance, C2 intervals, C4 statuses). | Docs only. Run [703](https://github.com/ekkus93/pdf2audiobook/actions/runs/40658211507) passed. | None |
| 2026-10-28 | f37d9ac68e887b038254019236c21b416e34c079 | 8.3: dated amendment notes on tasks 1.1, 2.6, 3.1 and 4.5 of the C1-C5 TODO (4.5 stays ticked, superseded by 686bd06) and a corrected status line. | Docs only. Run [704](https://github.com/ekkus93/pdf2audiobook/actions/runs/40658245628) passed. | None |
