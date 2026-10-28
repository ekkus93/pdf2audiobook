# PDF2Audiobook Citation and Equation Reading TODO

**Status:** In progress; 6.2 and 6.3 are finished by `docs/PDF2AUDIOBOOK_CITATIONS_EQUATIONS_REVIEW_TODO.md` (sections 9 and 10)
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
  - *Amendment (2026-10-28):* "defaults are false" was true when written. Both settings now default to true (commit 686bd06); the equation setting is quietly inactive without an LLM unless requested explicitly.
- [x] 1.2 Add a `Reading` config model and `Settings.reading`, the two environment variables, and the validation that equation processing needs the LLM.
- [x] 1.3 Add `--process-citations/--no-process-citations` and `--process-equations/--no-process-equations` to `analyze` and `convert`, as unset-by-default boolean pairs. Show both in `config show` and `doctor --json`.

## 2. Citation skipping (C2)

- [x] 2.1 Tests for the citation detector: the accepted forms (single, list, range with hyphen and en dash, semicolon list) and the rejected ones (`a[1]`, `x[i]`, bracketed text with letters, numbers over three digits, descending ranges, author–year forms).
- [x] 2.2 Implement the detector as a pure function that returns source character ranges.
- [x] 2.3 Tests for the spoken layer: a citation mid-sentence, at a sentence end, at the start of a paragraph, alone in a paragraph (nothing is spoken) or with punctuation (a pause), and split across a line break; trailing punctuation is kept; `chunk_source_ranges` alignment still succeeds; with the setting off, chunks are unchanged (golden comparison).
- [x] 2.4 Drop detected citation ranges from the spoken sequence while keeping the source mapping, voice markers and pause handling correct.
- [x] 2.5 Tests for identity: with the setting on, `"citations": true` is in the chapter audio fingerprint and the sidecar's `rendering_inputs`; with it off both are byte-identical to today's; a cached chapter is reused only when the recorded value matches; toggling regenerates audio only; `pack-m4b` does not call differing audio stale.
- [x] 2.6 Implement the fingerprint and sidecar change (conditional key), and the reuse check in `conversion.py` and `audio/freshness.py`. Confirm a fake-provider conversion never sends a citation when on, and does when off.
  - *Amendment (2026-10-28):* `audio/freshness.py` needed no change; it does not read the sidecar's rendering inputs. The reuse check lives in `conversion.py`. The fingerprint part is now `citations-skipped-v2` (review spec Q5).

## 3. Accepting and rejecting pending edits (C4)

- [x] 3.1 Tests: `edits list` filters by status and its `--json` output is content-free; `accept` sets `accepted` and changes exactly that block's narrated text; a hand-edited chapter file is a conflict naming the chapter, with every file unchanged; an interrupted accept recovers with `recover`; lock contention returns the lock error; accepting twice is harmless; an unknown block ID is exit 2; `reject` removes the proposal; `--all` works for both; the same commands handle a pending cleanup edit.
  - *Amendment (2026-10-28):* true for pending LLM cleanup edits only. An unaccepted built-in edit is a human rejection with status `rejected`, which the commands leave alone (review spec Q2).
- [x] 3.2 Add the `edits` command group (`list`, `accept`, `reject`) and the core functions behind it, using the workspace lock, the artifact planner and `commit_artifacts`/`commit_review` so the manifest and chapter files publish together.
- [x] 3.3 Record accepted and rejected proposals in `reports/edit_decisions.json`. Confirm the changed chapter's audio goes stale and nothing else does.
- [x] 3.4 Privacy tests for every new error path.

## 4. Equation proposals (C3)

- [x] 4.1 Tests for candidate selection: the listed symbols, Greek letters and function-call forms are candidates; ordinary prose, numbered list items and years are not; the cap and its warning.
- [x] 4.2 Implement the deterministic candidate test as a pure function.
- [x] 4.3 Tests for verification with a fake provider: a passing proposal becomes a pending edit (`provider="llm"`, `accepted=false`) and changes nothing else; each rule has a rejecting case (a dropped number, an invented digit, a dropped prose word, an empty or oversized proposal, markdown); the setting off makes no model calls; an LLM failure follows the existing fallback setting.
- [x] 4.4 Implement the equation reading task in a new `llm` module (add it to the mypy files), the verification, and the analysis hook that runs only when `process_equations` is on and the LLM is enabled. Respect the budget limits, remote-content consent and the existing windowing.
- [x] 4.5 Tests and implementation for the `llm-analysis` fingerprint: it includes the setting only when true, so off-state fingerprints do not change; enabling it re-analyzes an unapproved workspace from cached answers and still refuses an approved one with the existing message.
  - *Amendment (2026-10-28):* ticked as delivered, then **superseded by 686bd06**. With the setting on by default, a fingerprint part would have stale every existing workspace and refused approved ones, so the equation setting is in no stage fingerprint. Enabling it later does not re-analyze a workspace on its own. See spec C5 (amended).

## 5. Documentation

- [x] 5.1 Update `docs/PDF2AUDIOBOOK_SPEC.md` (§4.3, §6, §7) and `docs/MAINTAINER_GUIDE.md` (the settings, the spoken-layer citation hook, the edit workflow, the fingerprint rules).
- [x] 5.2 Update the README: the two settings and flags, the `edits` commands, what counts as a citation and as an equation candidate, and the known limitations.

## 6. Finish

- [x] 6.1 Run `/verify`, plus mypy on Python 3.12 and 3.13. Record the pass and skip counts, and run the Kitten smoke test with `PDF2AUDIOBOOK_KITTEN_SMOKE=1`.
- [ ] 6.2 Local acceptance on the *Attention Is All You Need* paper, never committed, counts only: citations skipped, equation candidates, proposals that pass verification, edits accepted, and a listening check of a sample.
- [ ] 6.3 Review the final diff against C1–C5 and record unresolved limitations.

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
| 2026-10-27 | 69a2eff6617aca745a9725c1f8105a5b60eef4b8 | Spec and TODO committed. | Docs only. Run [681](https://github.com/ekkus93/pdf2audiobook/actions/runs/40637939375) passed. | None |
| 2026-10-27 | 854bac9ccdfacb164434d1fd5ee588c8d18befd3 | 1.1-1.3 (C1): `[reading]` settings, env variables, flags, the LLM-required check, `config show`/`doctor` reporting. | All 20 `test_reading_settings` cases failed at parent. Extended the environment-variable coverage test for the two variables, reason in the commit message. Run [682](https://github.com/ekkus93/pdf2audiobook/actions/runs/40638432346) passed. | None |
| 2026-10-27 | 22bdafd5532dd1000b464b2b81f524cf5eac9120 | 2.1-2.2 (C2): `audio/citations.py` detector and masker. | `test_citation_detector` failed at parent with `ImportError` (module absent). After implementing, my own expected strings had miscounted spaces and one case carried a hack; both were test mistakes and were corrected. Run [683](https://github.com/ekkus93/pdf2audiobook/actions/runs/40639096154) passed. | None |
| 2026-10-27 | 8e3c20434e89a81e384c33d49f6f52b9a3ed4b4b | 2.3-2.4 (C2): `skip_citations` in the spoken layer. | Failing at parent: `test_a_paragraph_of_only_a_citation_becomes_a_pause`, `test_the_voice_never_receives_a_citation_when_skipping`, `test_voice_markers_and_citations_work_together`. A lone `[13]` paragraph contributes nothing rather than a pause; spec amended. Run [684](https://github.com/ekkus93/pdf2audiobook/actions/runs/40639603969) FAILED on Python 3.11 only, in "Verify committed dependency lockfile": a network error ("Request failed after 3 retries") while downloading packages; 3.12 and 3.13 passed. Not a code failure. | None |
| 2026-10-27 | 175f8c9b175901baafc2ef0160f6240070a2f3fa | 2.5-2.6 (C2): `"citations": true` in sidecars and a conditional fingerprint part; reuse only when the recorded setting matches. | Failing at parent: `test_turning_it_on_changes_the_fingerprint_and_is_stable`, the sidecar test and the toggling test. Run [685](https://github.com/ekkus93/pdf2audiobook/actions/runs/40639963249) FAILED on 3.11, 3.12 and 3.13: `test_with_the_setting_off_the_fingerprint_is_byte_identical_to_before` compared against a golden computed on this machine, where `kittenml` is installed, while the TTS model identity embeds the installed kittenml version, so the golden could not match CI. I did not check CI per commit during this loop and so pushed four more commits on top of it. Fixed below. | Fixed in `ebd84a5` |
| 2026-10-27 | 5b4ac1ebeb6d246c76ae32d372d768faf73ceb4b | 3.1-3.4 (C4): `edits list|accept|reject`, `edit_review.py`, `reports/edit_decisions.json`. | 14 of 15 `test_edit_review` cases failed at parent (the commands did not exist). Spec amended: `--status` option; a rejected proposal can return on re-analysis. Run [686](https://github.com/ekkus93/pdf2audiobook/actions/runs/40640429011) FAILED, same single cause as 685. | Fixed in `ebd84a5` |
| 2026-10-27 | 475c0570aecab4519628f4d1e9d6f17b520de77f | 4.1-4.2 (C3): `looks_mathematical` and `equation_candidates`. | `test_equation_candidates` failed at parent with `ImportError`. Spec amended: a function-call form counts only when being defined (`f(x) =`). Run [687](https://github.com/ekkus93/pdf2audiobook/actions/runs/40640681760) FAILED, same single cause as 685. | Fixed in `ebd84a5` |
| 2026-10-27 | 7c49c8c94656e330a95d1c43c872c0eeb6df6c4d | 4.3-4.4 (C3): `verify_reading`, `propose_llm_equation_readings`, the analysis hook. | `test_equation_readings` failed at parent with `ImportError`; the analysis tests failed before the hook (3 of 4). The digit-stream rule replaces the spec's two number rules because extraction merges superscripts (`100002i`); spec amended. Two of my own parametrized cases were wrong and were corrected. Run [688](https://github.com/ekkus93/pdf2audiobook/actions/runs/40641190646) FAILED, same single cause as 685. | Fixed in `ebd84a5` |
| 2026-10-27 | f4f73773dfbeab6d24d3fc10da685ee514b0fffb | 4.5: `equation-readings-v1` in the `llm-analysis` fingerprint only when on. | Failing at parent: the turning-on, re-plan-from-cache and approved-workspace tests; the two golden checks passed (analysis goldens do not embed kittenml). Run [689](https://github.com/ekkus93/pdf2audiobook/actions/runs/40641412802) FAILED, same single cause as 685. | Fixed in `ebd84a5` |
| 2026-10-27 | 0b5b15ed60925efad429d0cda168457c5442ddd7 | 5.1-5.2: spec, maintainer guide and README. | Docs only. Run [690](https://github.com/ekkus93/pdf2audiobook/actions/runs/40641484144) FAILED, same single cause as 685. | Fixed in `ebd84a5` |
| 2026-10-27 | ebd84a5b5514b9cb1014a840d6c0bb12c10cb8b5 | Fix for the CI failure: `tests/test_citation_identity.py` pins `_tts_model_identity` and its golden is recomputed from the real pre-change code (commit 8e3c204, in a throwaway worktree). | Verified locally with `kittenml` made unimportable, which is the CI condition. 1960 passed, 1 skipped. Run [691](https://github.com/ekkus93/pdf2audiobook/actions/runs/40642044070) passed on 3.11, 3.12 and 3.13. | None |
| 2026-10-27 | ebd84a5b5514b9cb1014a840d6c0bb12c10cb8b5 | 6.1 final gate: `uv lock --check`, Ruff, format, mypy on 3.11, 3.12 and 3.13, `pytest -q -ra` with `PDF2AUDIOBOOK_KITTEN_SMOKE=1`, CLI smoke. | 1961 passed, nothing skipped (the Kitten smoke test ran). mypy reports only the two known `kittenml` errors locally. ffmpeg, tesseract and node were available. | None |
| 2026-10-27 | ebd84a5b5514b9cb1014a840d6c0bb12c10cb8b5 | 6.2 attempted: re-analysis of the local *Attention* paper with both settings on, in a fresh output folder seeded with the earlier LLM cache. | Failed at the first uncached request with `Could not read the context length Ollama serves for the model`: Ollama was not running (service inactive, connections reset). No result to report. | Needs Ollama running |
