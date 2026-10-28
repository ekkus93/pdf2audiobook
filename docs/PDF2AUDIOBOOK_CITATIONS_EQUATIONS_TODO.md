# PDF2Audiobook Citation and Equation Reading TODO

**Status:** In progress
**Date:** 2026-10-27
**Baseline:** master at b0b4d7c
**Specification:** `docs/PDF2AUDIOBOOK_CITATIONS_EQUATIONS_SPEC.md` (C1–C5)
**Previous TODO:** `docs/PDF2AUDIOBOOK_EPUB_CHAPTERS_FOLLOWUP_TODO.md`

## Working rules

- Work in the order below, because later tasks depend on earlier ones. Use `[x]` only when the implementation exists and its named tests pass; check a parent only when all of its subitems are checked.
- Every fix task has three parts:
  - (a) add the regression tests, run them against the parent commit, and record the failing test IDs in the ledger;
  - (b) make the fix;
  - (c) run `/verify`.
- One feature per commit, with its tests. Conventional Commits with a scope, lowercase imperative subject, no body. Docs-only status changes go in their own `docs:` commits.
- Never change an existing test's inputs or expected results to make a change pass, except the environment-variable coverage test, which must list every declared variable; say so in the commit message.
- With both settings off, behavior, fingerprints and sidecars must be byte-identical to today's. Prove this with a test, not by inspection.
- LLM output is untrusted and pending until accepted. Errors and logs stay content-free (add a privacy test for each new error path). Add every new `src/` module to `[tool.mypy].files`. Use synthetic fixtures and fake providers only; CI stays offline.

## 1. The two settings (C1)

- [x] 1.1 Tests: defaults are false; the TOML key, environment variable and each CLI flag form reach `Settings`; precedence is CLI over environment over TOML; the two settings are independent; `process_equations` with the LLM disabled is a content-free exit 2; `config show --json` and `doctor --json` report both. Extend the environment-variable coverage test for both variables.
- [x] 1.2 Add a `Reading` config model and `Settings.reading`, the two environment variables, and the validation that equation processing needs the LLM.
- [x] 1.3 Add `--process-citations/--no-process-citations` and `--process-equations/--no-process-equations` to `analyze` and `convert`, as unset-by-default boolean pairs. Show both in `config show` and `doctor --json`.

## 2. Citation skipping (C2)

- [x] 2.1 Tests for the citation detector: the accepted forms (single, list, range with hyphen and en dash, semicolon list) and the rejected ones (`a[1]`, `x[i]`, bracketed text with letters, numbers over three digits, descending ranges, author–year forms).
- [x] 2.2 Implement the detector as a pure function that returns source character ranges.
- [x] 2.3 Tests for the spoken layer: a citation mid-sentence, at a sentence end, at the start of a paragraph, alone in a paragraph (nothing is spoken) or with punctuation (a pause), and split across a line break; trailing punctuation is kept; `chunk_source_ranges` alignment still succeeds; with the setting off, chunks are unchanged (golden comparison).
- [x] 2.4 Drop detected citation ranges from the spoken sequence while keeping the source mapping, voice markers and pause handling correct.
- [x] 2.5 Tests for identity: with the setting on, `"citations": true` is in the chapter audio fingerprint and the sidecar's `rendering_inputs`; with it off both are byte-identical to today's; a cached chapter is reused only when the recorded value matches; toggling regenerates audio only; `pack-m4b` does not call differing audio stale.
- [x] 2.6 Implement the fingerprint and sidecar change (conditional key), and the reuse check in `conversion.py` and `audio/freshness.py`. Confirm a fake-provider conversion never sends a citation when on, and does when off.

## 3. Accepting and rejecting pending edits (C4)

- [x] 3.1 Tests: `edits list` filters by status and its `--json` output is content-free; `accept` sets `accepted` and changes exactly that block's narrated text; a hand-edited chapter file is a conflict naming the chapter, with every file unchanged; an interrupted accept recovers with `recover`; lock contention returns the lock error; accepting twice is harmless; an unknown block ID is exit 2; `reject` removes the proposal; `--all` works for both; the same commands handle a pending cleanup edit.
- [x] 3.2 Add the `edits` command group (`list`, `accept`, `reject`) and the core functions behind it, using the workspace lock, the artifact planner and `commit_artifacts`/`commit_review` so the manifest and chapter files publish together.
- [x] 3.3 Record accepted and rejected proposals in `reports/edit_decisions.json`. Confirm the changed chapter's audio goes stale and nothing else does.
- [x] 3.4 Privacy tests for every new error path.

## 4. Equation proposals (C3)

- [x] 4.1 Tests for candidate selection: the listed symbols, Greek letters and function-call forms are candidates; ordinary prose, numbered list items and years are not; the cap and its warning.
- [x] 4.2 Implement the deterministic candidate test as a pure function.
- [x] 4.3 Tests for verification with a fake provider: a passing proposal becomes a pending edit (`provider="llm"`, `accepted=false`) and changes nothing else; each rule has a rejecting case (a dropped number, an invented digit, a dropped prose word, an empty or oversized proposal, markdown); the setting off makes no model calls; an LLM failure follows the existing fallback setting.
- [x] 4.4 Implement the equation reading task in a new `llm` module (add it to the mypy files), the verification, and the analysis hook that runs only when `process_equations` is on and the LLM is enabled. Respect the budget limits, remote-content consent and the existing windowing.
- [x] 4.5 Tests and implementation for the `llm-analysis` fingerprint: it includes the setting only when true, so off-state fingerprints do not change; enabling it re-analyzes an unapproved workspace from cached answers and still refuses an approved one with the existing message.

## 5. Documentation

- [ ] 5.1 Update `docs/PDF2AUDIOBOOK_SPEC.md` (§4.3, §6, §7) and `docs/MAINTAINER_GUIDE.md` (the settings, the spoken-layer citation hook, the edit workflow, the fingerprint rules).
- [ ] 5.2 Update the README: the two settings and flags, the `edits` commands, what counts as a citation and as an equation candidate, and the known limitations.

## 6. Finish

- [ ] 6.1 Run `/verify`, plus mypy on Python 3.12 and 3.13. Record the pass and skip counts, and run the Kitten smoke test with `PDF2AUDIOBOOK_KITTEN_SMOKE=1`.
- [ ] 6.2 Local acceptance on the *Attention Is All You Need* paper, never committed, counts only: citations skipped, equation candidates, proposals that pass verification, edits accepted, and a listening check of a sample.
- [ ] 6.3 Review the final diff against C1–C5 and record unresolved limitations.

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
