# PDF2Audiobook Citation and Equation Review Fixes Specification

**Status:** Proposed
**Date:** 2026-10-28
**Companion:** `docs/PDF2AUDIOBOOK_CITATIONS_EQUATIONS_REVIEW_TODO.md`
**Baseline:** master at 686bd06 (`feat(config): default citation and equation processing to on`)
**Supplements:** `docs/PDF2AUDIOBOOK_CITATIONS_EQUATIONS_SPEC.md` (C1–C5)

## 1. Purpose and scope

A code review of the citation and equation work (C1–C5), done after both settings became on by default, found:
- three bugs in the `edits` commands;
- several smaller code and documentation problems;
- stale text in the C1–C5 spec and TODO;
- missing ledger evidence;
- an unfinished acceptance step.

This spec covers every one of them, so they can be fixed in one pass.

All existing invariants still hold:
- PDF text and LLM output are untrusted, and LLM edits stay pending until a person accepts them.
- Errors, logs and `--json` output are content-free.
- A human rejection is never silently undone.
- Resume is content-addressed.
- CI stays offline, and fixtures are synthetic.

## 2. Requirements

### Q1: `edits list` prints book text literally

**Problem.** The human output of `edits list` (`cli.py`) prints `original` and `replacement` through `console.print(..., markup=True)`. Rich therefore parses book text as markup:
- `x[i] + y[/i] z` prints as `x + y z`, so the brackets vanish and the text is styled;
- `a [/b] c` raises `MarkupError`, so the command fails.

Bracketed math notation is exactly what equation readings contain.

**Requirement.**
- Escape every book-derived field (`original`, `replacement`, and `reason` when it is model-written) with `rich.markup.escape`, keeping markup only for the fixed parts of the line. Printing those fields with `markup=False` is also acceptable.
- No markup error can occur for any text. The fixed `Unexpected internal error` path must not be reachable from listing.

**Acceptance:**
- An edit whose original and replacement contain `x[i]`, `[/b]`, `[bold]` and `[13]` lists with exit 0, and every bracket appears verbatim in stdout.
- `--json` output is unchanged and still content-free.

### Q2: Rejected built-in edits are not "pending"

**Problem.** Built-in edits (`provider="deterministic"`) are created with `accepted=True`. An unaccepted one is a cleanup a person rejected during review: `analysis_state._preserve_rejected_deterministic_edits` carries it across reanalysis, and `pipeline.py` treats it as approved content. `edit_review._select` and `list_edits` call every unaccepted edit pending, so:
- `edits list` shows a rejection as pending;
- `edits accept --all` silently re-accepts it;
- `edits reject` deletes it, so the rejection is forgotten and the edit returns on the next analysis.

**Requirement.**
- An edit's status is:
  - `accepted` when `accepted=True`;
  - `rejected` when `accepted=False` and `provider == "deterministic"`;
  - `pending` otherwise.
- `edits list --status` accepts `pending|accepted|rejected|all`. The default stays `pending`.
- `accept` and `reject` act only on pending edits. `--all` never touches a rejected built-in edit.
- Naming the block of a rejected built-in edit, when that block has no pending edit, is exit 2 with a content-free message: "That edit was rejected during review; it cannot be accepted or rejected here".
- The manifest record of a rejection is never removed.

**Acceptance:**
- A manifest has one accepted built-in edit, one rejected built-in edit, one pending LLM cleanup edit and one pending equation edit:
  - `list` shows exactly the two LLM edits as pending;
  - `--status rejected` shows exactly the built-in rejection;
  - `accept --all` accepts exactly the two LLM edits;
  - `reject --all` removes only those two.
- In every case the rejected built-in edit is still in the manifest with `accepted=False`, and a following reanalysis still refuses or preserves it as before.
- Naming its block ID is exit 2.

### Q3: One accepted edit per block

**Problem.** Accepted edits are applied as a `{block_id: replacement}` map (`chapter_selection.py`, `document/narration.py`). An equation reading is written from the raw block text. Accepting it on a block that already has an accepted edit therefore discards that edit silently. The earlier edit could be a built-in fix or an accepted LLM cleanup. `_select` refuses only two pending edits that name one block, and only when IDs are given; `--all` skips even that check.

**Requirement.** Before any change, and for explicit IDs and `--all` alike, `accept` refuses with exit 2 and nothing changes when:
- the block already has an accepted edit: "That block already has an accepted edit; accepting another would discard it";
- or more than one pending edit for one block would be accepted: the existing "More than one pending edit targets that block; reject the unwanted one first".

The message carries no book text. It may name the block ID, since block IDs are not book text and `edits list` already prints them.

**Acceptance:**
- A block with an accepted built-in edit and a pending equation edit: accepting the equation edit by ID, or with `--all`, is exit 2, and the manifest, chapter files and audio are byte-identical.
- A block with two pending edits: `--all` is exit 2 with nothing changed.
- Other blocks are unaffected by the refusal: the operation is all-or-nothing, and the message says which block blocked it.

### Q4: A failed edit audit is reported, not swallowed

**Problem.** `edit_review._audit` catches every exception and returns, so `reports/edit_decisions.json` can fail to update with no sign. The function also imports `load_bounded_json` inside its body.

**Requirement.**
- The decision still succeeds when the audit cannot be written, because the manifest change is already published.
- The failure is reported content-free:
  - human mode prints a warning line, "Could not update reports/edit_decisions.json; the decision itself was saved";
  - `--json` adds `"warnings": ["edit_audit_not_written"]`.
- Catch only `OSError` and the bounded-JSON errors; let programming errors propagate.
- Move the import to module level.

**Acceptance:**
- With the reports directory made unwritable (or with `write_json` patched to raise `OSError`), accept and reject exit 0 and their decisions are saved.
- The warning appears as specified and contains no path or exception text.
- A corrupt existing audit file is replaced rather than failing, as today.

### Q5: Math intervals are not citations

**Problem.** `[1, 5]` used as an interval, as in `x ∈ [1, 5]` or `p = [2, 3]`, matches the citation pattern and is skipped from the audio.

**Requirement.**
- A bracketed group is not a citation when the nearest preceding non-space character is one of `∈ = ≤ ≥ < > ≈ ×`.
- `in [1, 5]` stays ambiguous and remains a citation, because "as shown in [1, 5]" is the common citation form. Document this.
- This changes what is spoken with the setting on, so bump the audio fingerprint part from `citations-skipped` to `citations-skipped-v2`. The off-state identity stays byte-identical.

**Acceptance:**
- `x ∈ [1, 5]`, `p = [2, 3]` and `a ≤ [4]` are kept.
- `shown in [1, 5].` and `results [13]` are still skipped.
- The off-state golden fingerprints are unchanged.
- The on-state fingerprint differs from the value at the baseline (a golden computed from the baseline code with the model identity pinned).

### Q6: Bibliography numbering and citation-only chapters

**Problem.**
- Bibliography entries (`[1] Jimmy Lei Ba, …`) lose their numbers in the audio. This is acceptable, but undocumented.
- A chapter whose only text is citations would have nothing speakable after masking. The behavior of that case is untested.

**Requirement.**
- Keep skipping bracketed entry numbers in bibliographies, and document it in the README and the maintainer guide.
- A chapter with nothing speakable after citation masking fails only that chapter, with the existing content-free "Chapter has no speakable text" error. Other chapters still convert.

**Acceptance:**
- A test shows `[1] Jimmy Ba. Layer normalization.` spoken as `Jimmy Ba. Layer normalization.`, with no leading gap that alters chunking.
- A fake-provider conversion of a two-chapter book whose second chapter is only `[1] [2]` completes chapter 1 and reports chapter 2 with the existing error, content-free.

### Q7: Equation prompt wording

**Problem.** The equation prompt says "Each line contains mathematical notation", but candidates are whole blocks, often paragraphs. The *Attention* run proposed rewrites of entire paragraphs.

**Requirement.** Reword the prompt to say that each record is a line or paragraph that contains mathematical notation, and that only the notation may change. The prompt text is part of the LLM cache key, so equation requests are re-sent once. No fingerprint changes, because the setting is not in any stage fingerprint.

**Acceptance:**
- A test asserts that the prompt names records as lines or paragraphs and still carries the untrusted-content framing.
- The cache key changes.

### Q8: Code and documentation accuracy

**Problem and requirement:**
- The `Reading` docstring in `config.py` still says "Opt-in processing". Change it to describe settings that are on by default and can be switched off.
- Accepting any equation reading makes the workspace approved content (`pipeline.py`), so it refuses reanalysis. Document this in the README and the maintainer guide.
- `docs/PDF2AUDIOBOOK_CITATIONS_EQUATIONS_SPEC.md`:
  - the header says "Proposed", the opening says "two independent, opt-in settings", and C1's acceptance list says "Defaults are false";
  - amend these, keeping the original text visible as superseded where the amendment notes already do.
- `docs/PDF2AUDIOBOOK_CITATIONS_EQUATIONS_TODO.md`:
  - task 1.1 says "defaults are false";
  - task 2.6 names `audio/freshness.py`, which needed no change;
  - task 3.1's cleanup-edit claim is true only for LLM cleanup;
  - task 4.5 is ticked although its design was reversed;
  - the status line says it waits on Ollama.
- Amend each with a dated *Amendment* note. Do not rewrite history: 4.5 stays ticked, with a note that the 686bd06 change superseded it.

**Acceptance:** A reviewer reading either document sees the current behavior, and why it changed.

### Q9: Missing evidence and the unfinished acceptance

**Problem.**
- The default change (686bd06, CI run 693) has no ledger row. It also skipped the TODO's test-first rule and changed existing tests beyond the one exception.
- Task 6.2's real-paper run happened, but it is not recorded or ticked, and the listening check was never done.
- Task 6.3 (diff review) is not done.

**Requirement.**
- Add ledger rows to the C1–C5 TODO:
  - one for 686bd06, with CI run 693, saying plainly that it was not written test-first and naming the existing tests it changed;
  - one for the 6.2 counts (27 chapters, 103 citation groups in chapter text, 22 equation proposals, 13 verified, 9 discarded, 13 accepted in a scratch workspace).
- Repeat 6.2 after Q1–Q7 land, using the cached analysis, and render one chapter that contains both citations and accepted readings for a listening check by the user. The audio stays in `tmp/` and is never committed.
- Tick 6.2 only after the user confirms the listening check.
- Record this review as 6.3, with the findings that Q1–Q8 fix and the limitations that remain.

**Acceptance:** Ledger rows use full SHAs and real run numbers. 6.2 is ticked only with the user's confirmation, and 6.3 lists the remaining limitations.

## 3. Identity

- Q5 bumps the on-state audio fingerprint part to `citations-skipped-v2`. With the default on, every chapter's audio regenerates once; record this in the maintainer guide's upgrade notes.
- Q7 changes the equation prompt, so its LLM cache entries miss once.
- Q1–Q4 change the `edits` commands only, and Q6 and Q8 change documentation and tests, so none of them needs a bump.

## 4. Known limitations (documented, not solved here)

- `in [1, 5]` is read as a citation even when it is an interval.
- A rejected built-in edit can be re-enabled only through the review workflow, not through `edits`.
- An equation reading replaces its whole block. A block with another accepted edit cannot also take a reading (Q3 refuses it). Combining the two would need the reading to be proposed from the edited text.
- Author–year citations and math without the listed symbols remain unhandled (C1–C5 limitations).

## 5. Validation

- Add focused tests per requirement, then run `/verify`, plus mypy on Python 3.12 and 3.13. Run the Kitten smoke test with `PDF2AUDIOBOOK_KITTEN_SMOKE=1`.
- Check CI after **every** push, and fix a failing run before the next task.
