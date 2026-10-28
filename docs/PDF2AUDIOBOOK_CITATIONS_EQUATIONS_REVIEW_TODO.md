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

- [ ] 4.1 Tests:
  - with the audit write failing, accept and reject still exit 0 and save their decision;
  - the human warning and the JSON warning code appear, with no path or exception text;
  - a corrupt audit file is replaced.
- [ ] 4.2 Catch only `OSError` and the bounded-JSON errors, return the failure to the CLI, emit the warning, and move the import to module level.

## 5. Math intervals (Q5)

- [ ] 5.1 Tests:
  - `x ∈ [1, 5]`, `p = [2, 3]` and `a ≤ [4]` are kept;
  - `shown in [1, 5].` and `results [13]` are skipped;
  - the off-state goldens are unchanged;
  - the on-state fingerprint differs from a baseline golden, with the model identity pinned.
- [ ] 5.2 Add the preceding-symbol rule to `audio/citations.py`, and bump `citations-skipped` to `citations-skipped-v2`. Add the upgrade note to `docs/MAINTAINER_GUIDE.md`.

## 6. Bibliography numbers and citation-only chapters (Q6)

- [ ] 6.1 Tests:
  - a bibliography entry's leading `[1]` is skipped without altering chunking;
  - a two-chapter conversion whose second chapter is only citations completes chapter 1 and fails chapter 2 with the existing content-free error.
- [ ] 6.2 Fix any failure the tests expose, keeping the per-chapter failure. Document both behaviors in the README and the maintainer guide.

## 7. Equation prompt (Q7)

- [ ] 7.1 Test: the prompt describes records as lines or paragraphs, keeps the untrusted-content framing, and changes the cache key.
- [ ] 7.2 Reword the prompt in `llm/equations.py`.

## 8. Accuracy of code comments and documents (Q8)

- [ ] 8.1 Update the `Reading` docstring. Document in the README and the maintainer guide that accepting an equation reading makes the workspace approved content.
- [ ] 8.2 Amend the C1–C5 spec: the status, the "opt-in" opening, and C1's "Defaults are false".
- [ ] 8.3 Amend the C1–C5 TODO with dated notes on tasks 1.1, 2.6, 3.1 and 4.5 (4.5 stays ticked, superseded by 686bd06), and correct its status line.

## 9. Evidence and acceptance (Q9)

- [ ] 9.1 Add the ledger rows to the C1–C5 TODO:
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
