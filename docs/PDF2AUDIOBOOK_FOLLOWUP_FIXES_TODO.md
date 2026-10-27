# PDF2Audiobook Follow-up Fixes and Progress TODO

**Status:** Complete; unresolved limitations are listed below
**Date:** 2026-10-27
**Baseline:** master at 5a4f96e plus the uncommitted module split in the working tree
**Specification:** `docs/PDF2AUDIOBOOK_FOLLOWUP_FIXES_SPEC.md` (R1–R11)
**Previous TODO:** `docs/PDF2AUDIOBOOK_REVIEW_FOLLOWUP_TODO.md`

## Working rules

- Work in the order below, because later tasks depend on earlier ones.
- Use `[x]` only when the implementation exists and its named tests pass; otherwise leave `[ ]`. Check a parent only when all of its subitems are checked.
- Every fix task has three parts unless it says otherwise:
  - (a) add the regression tests, run them against the parent commit, and record the failing test IDs in the ledger;
  - (b) make the fix;
  - (c) run `/verify`.
- A task marked **refactor** instead proves there is no behaviour change: the full suite passes with only monkeypatch targets moved.
- A task marked **feature** has new tests only; record that they pass.
- One fix per commit, with its tests. Conventional Commits with a scope, lowercase imperative subject, no body. Docs-only status changes go in their own `docs:` commits.
- Never change an existing test's inputs or expected results to make a change pass.
- If the implementation must differ from the spec, amend the spec in the same commit.
- Every new error path gets a `tests/test_*_privacy.py` test. Add every new `src/` module to `[tool.mypy].files`. CI stays offline.
- After CI for a pushed fix, record evidence in this file's Progress ledger in a separate `docs:` commit, using the full SHA and real run IDs.

## 0. Baseline

- [x] 0.1 **refactor** Commit the working-tree module split (R9). Split it into one commit per cohesive extraction where practical.
  - [x] 0.1a Confirm `[tool.mypy].files` lists every new module, and add `src/pdf2audiobook/narration.py`.
  - [x] 0.1b Full suite passes; the only test changes are monkeypatch targets (`tests/test_audio_error_privacy.py`, `tests/test_review_gate_current_state.py`).
  - [x] 0.1c Update `docs/MAINTAINER_GUIDE.md` with the module responsibilities and re-export facades.
- [x] 0.2 **docs** Fix `docs/PDF2AUDIOBOOK_REVIEW_FOLLOWUP_TODO.md` (R9): remove the stale §2 "Progress" paragraph, correct §5's mypy evidence, and point to this TODO.

## 1. Lock-free reads (R1)

- [x] 1.1 Add `PendingRecoveryError` to `errors.py`, with a content-free message and the workspace exit code.
- [x] 1.2 Add `create: bool` to `workspace_lock`. Only writer entry points pass `create=True`.
- [x] 1.3 Make `read_manifest` lock-free, with the journal check before and after the read. Move every locked caller's read under its existing lock (conversion, dry-run, `pack-m4b`, review save).
- [x] 1.4 Tests:
  - `read_manifest` and `GET /api/manifest` succeed while another process holds the lock;
  - a nonexistent path creates nothing;
  - a pending journal raises `PendingRecoveryError` with no file changes;
  - conversion and `pack-m4b` still recover first;
  - a privacy test.

## 2. Truthful save outcomes (R2, R3)

- [x] 2.1 Raise `PendingRecoveryError` for recovery failures during lock acquisition. Keep `ReviewRecoveryRequired` for this operation's own post-commit failures.
- [x] 2.2 Add `ChapterConflictError(chapter_number)` and raise it from `chapter_artifacts._conflict`. Update its message to name `regenerate-chapter`.
- [x] 2.3 Map the HTTP outcomes with stable `outcome` fields:
  - 503 `not_saved_pending_recovery`
  - 503 `committed_needs_recovery`
  - 422 `not_saved_conflict` plus `chapter`
  - 409 for lock contention
  - generic 400 for everything else

  Forward only allowlisted messages.
- [x] 2.4 Update the browser script so it shows the message and the next action for each outcome, and never "Saved" on failure. Map CLI exit codes.
- [x] 2.5 Tests:
  - a leftover unrecoverable journal gives 503 `not_saved_pending_recovery` with the manifest byte-identical;
  - the existing committed-recovery test returns `committed_needs_recovery`;
  - a boundary change on an edited chapter returns 422 naming the chapter with files unchanged;
  - browser script tests for each message;
  - privacy tests.

## 3. Regeneration and recovery commands (R4, R5)

- [x] 3.1 Add a shared backup helper: exclusive create in `chapter-backups/` and `workspace-backups/`, a UTC timestamp name, fsync of the file and directory, and never overwriting. Make the planner ignore both directories.
- [x] 3.2 Make recovery errors name blocking targets by safe label (`chapter N`, `manifest`, `coverage report`, `chapter metadata`).
- [x] 3.3 Add the `recover MANIFEST [--back-up-changed] [--json]` command.
- [x] 3.4 Add the `regenerate-chapter MANIFEST --chapter N ... | --all-conflicts [--json]` command. It plans from the committed manifest and recorded policy, backs up differing files, and publishes `edited=false` through one transaction.
- [x] 3.5 Update the conflict, recovery and README text to name these commands. Document that deleting `chapter-artifacts.json` is unsupported.
- [x] 3.6 Tests:
  - an observed edited file that was then deleted is regenerated and conversion then proceeds;
  - an edited file is backed up byte for byte;
  - a repeat run makes no new backup;
  - existing backups are never overwritten;
  - `--all-conflicts` selection;
  - an external edit after commit is named as `chapter N`;
  - `recover --back-up-changed` completes the transaction and a repeat reports "nothing pending";
  - an invalid journal is refused with no writes;
  - `--json` is parseable and content-free;
  - lock contention;
  - interrupted publication recovers;
  - privacy tests.

## 4. Legacy policy resolution (R6)

- [x] 4.1 Implement policy resolution when no artifact state exists, per spec R6 (omit edits, anchor edits, recognizable files); otherwise raise `FootnotePolicyUnknownError`. Add `regenerate-chapter --footnotes` for the refused case.
- [x] 4.2 Use the resolver in review save, selection and `pack-m4b`. Analysis keeps recording its configured policy.
- [x] 4.3 Tests:
  - legacy `inline`, `end` and `omit` workspaces save a review and record the policy;
  - ambiguous candidates are refused with files unchanged;
  - a footnote-free workspace adopts `warn`;
  - a privacy test.

## 5. No-op publication (R7)

- [x] 5.1 Return early from `commit_artifacts` when every planned digest matches the current one and there are no deletes. Guards still run first.
- [x] 5.2 Tests: an up-to-date analysis resume makes zero `atomic_write` calls, leaves modification times unchanged and creates no journal; a concurrent change is still detected.

## 6. Missing acceptance coverage (R8)

- [x] 6.1 Dry-run test: after a voice marker and a correction in an approved chapter, `convert --dry-run --json` reflects the edited text, writes no audio and leaves the bytes unchanged.
- [x] 6.2 Legacy end-to-end test: with `chapter-artifacts.json` removed, run analyze resume, review save and a fake-TTS convert. A matching file is adopted; a differing file is preserved, reported, and resolved by `regenerate-chapter`.
- [x] 6.3 No-mixed-consumption test: with a committed but unpublished journal, conversion recovers before selection and synthesizes the new text.

## 7. LLM request timeout (R10) — feature

- [x] 7.1 Add `RemoteLLM.timeout_seconds` (`> 0`, `<= 3600`). Defaults: Ollama 300, OpenAI and llama-server 60. Add the env override `PDF2AUDIOBOOK_LLM_TIMEOUT_SECONDS` mapped to `@selected`.
- [x] 7.2 Have the provider factory pass the selected provider's timeout, using an `httpx.Timeout` whose connect timeout is `min(10, t)`. Give the `/api/ps` lookup a fixed 10 s timeout.
- [x] 7.3 Treat a timeout as a retryable transport failure. The final message is content-free and names `llm.<provider>.timeout_seconds`; budget accounting is unchanged.
- [x] 7.4 Report the value in `config show` (text and `--json`) and `doctor --json`. Update the README, including the worst-case time per request, and the default config docs.
- [x] 7.5 Tests:
  - the default is 300;
  - config-file and env values reach the client timeout;
  - out-of-range values are rejected;
  - `httpx.ReadTimeout` is retried, then gives the message;
  - `/api/ps` uses 10 s;
  - the analysis fingerprint and LLM cache key are unchanged by the timeout;
  - `config show --json` includes the field;
  - a privacy test.

## 8. Progress and ETA (R11) — feature

- [x] 8.1 Add `tqdm>=4.66,<5` to the runtime dependencies and `types-tqdm` to dev. Run `uv lock`. Confirm the clean-venv wheel/sdist install works locally.
- [x] 8.2 Add `src/pdf2audiobook/progress_display.py` (`ProgressReporter` protocol, `NullReporter`, `TqdmReporter`) and add it to mypy files. Exclude `initial` from the rate, show "estimating…" until real work completes, and route log lines through `tqdm.write`.
- [x] 8.3 Add the root `--progress/--no-progress`, `general.progress` (`auto|always|never`) and `PDF2AUDIOBOOK_PROGRESS` settings. Always disable progress under `--json` and `--quiet`. `auto` requires stderr to be a TTY.
- [x] 8.4 Wire up the stages, with reporters injected rather than importing `tqdm`:
  - extraction pages;
  - analysis requests per stage, with cache hits advancing immediately and an indeterminate counter when the total isn't known;
  - synthesis characters, with cached and resumed work as `initial` and detail `chapter i/n`;
  - encoding and `pack-m4b` chapters, with the indeterminate M4B encode.
- [x] 8.5 Add the content-free completion summary line.
- [x] 8.6 Tests:
  - a recording reporter gets the right totals, initial values and advances for a fake-provider convert, a resumed convert with one cached chapter, and analysis with cache hits;
  - `TqdmReporter` on a fake TTY shows the stage, count and ETA field, with no book text or temp path;
  - `--json` and `--quiet` give no progress and parseable stdout;
  - non-TTY `auto` gives none;
  - `--progress --json` gives none;
  - the CLI smoke passes;
  - `tests/test_third_party_stdout_privacy.py` still passes.
- [x] 8.7 Update the README (progress option and how to read the ETA) and the MAINTAINER_GUIDE (reporter injection and the dependency). If ci.yml's install steps change, keep `tests/test_ci_uv_pin.py` consistent.

## 9. Finish

- [x] 9.1 Merge the superseding text into `docs/PDF2AUDIOBOOK_REVIEW_FOLLOWUP_SPEC.md` and `docs/PDF2AUDIOBOOK_SPEC.md`: the read-only access rule, outcome codes, regeneration and recovery commands, policy resolution, timeout and progress.
- [x] 9.2 Run `/verify`, plus `mypy --python-version 3.12` and `3.13`. Record pass and skip counts and any skipped external-tool checks.
- [x] 9.3 Review the final diff against every acceptance criterion in R1–R11. Record unresolved limitations without checking incomplete items.

## Unresolved limitations

- Progress: vision requests advance the analysis counter but are not pre-announced, so that total grows when they run. Speech synthesis and MP3 encoding share one per-chapter bar (only `pack-m4b` has a separate encoding stage). The estimate is tqdm's smoothed rate; its accuracy on a real long book was not measured, only the display on a pseudo-terminal with a fake TTS engine. Cached advances adjust tqdm's public counters (`n`, `initial`, `last_print_n`), so the `tqdm<5` pin matters.
- Legacy footnote policy inference is deliberately conservative: when the unedited chapter files do not pin one policy, the user must run `analyze` with the original setting or pass `regenerate-chapter --footnotes`.
- No live Ollama, OpenAI or llama-server run exercised the new timeout; it is covered with mock transports only. The opt-in Kitten smoke was not run in this environment.
- Windows was not tested: POSIX locking and directory fsync remain unavailable there, as documented.
- Section 3, 4 and 8 tests were written together with their implementation, because the symbols did not exist at the parent commit; the ledger lists which tests failed at the parent for the other sections.

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
| 2026-10-27 | 9a968ba61fd33d66c1050899c9b8b48759bfea2c | 0.1 (refactor): committed the module split with `narration.py` added to the mypy list; docs/CLAUDE.md commits `d3f2250` and `d96ced2` were pushed with it. | Full suite unchanged apart from monkeypatch targets. Run [645](https://github.com/ekkus93/pdf2audiobook/actions/runs/40533275832) passed on 3.11, 3.12, 3.13. | None |
| 2026-10-27 | 4da2215a68c8ac2e49908a6cb2ff622919d98dee | 0.2: reconciled the review follow-up TODO. | Docs only. Run [646](https://github.com/ekkus93/pdf2audiobook/actions/runs/40533325335) passed. | None |
| 2026-10-27 | 66c9cf065336ae0482e424ca3d23c50d767601f3 | 1.1–1.4 (R1): lock-free `read_manifest`, `workspace_lock(create=, recover=)`, `PendingRecoveryError`. | Failing at parent: `test_manifest_read_is_lock_free` (read_manifest succeeds while locked; review endpoint succeeds while locked; missing workspace creates nothing; no lock file; pending journal blocks read; endpoint reports pending) and `test_pending_recovery_privacy`. Changed existing tests: 8 reads in `test_review_followup_regressions.py` (including the fresh-process one-liner) now go through `workspace_lock`, because recovery moved to lock holders by R1; 11 tests depended on it and their expected results are unchanged. Run [647](https://github.com/ekkus93/pdf2audiobook/actions/runs/40533988368) passed. | None |
| 2026-10-27 | df0cbacd27fa69aa5d9a31d394570bc2c2d495f0 | 2.1–2.5 (R2, R3): `not_saved_pending_recovery`, `committed_needs_recovery`, 422 `not_saved_conflict`, browser messages. | Failing at parent: `test_review_save_outcomes` (blocked earlier transaction direct and HTTP; own post-commit failure; chapter conflict HTTP; conflict error carries the number). Browser-script tests were written after the implementation. Changed existing test: `test_recovery_refuses_to_overwrite_an_edit_after_commit` expects `PendingRecoveryError` for lock-time recovery failure. Run [648](https://github.com/ekkus93/pdf2audiobook/actions/runs/40534789530) passed. | None |
| 2026-10-27 | 4094be714fcf1d5fb8ede3599c4d358cc216dbe3 | 3.1–3.6 (R4, R5): `backup_file`, labelled recovery errors, `recover`, `regenerate-chapter`. | New commands, so no parent run was possible; 19 new tests (18 passed first run; the selector-validation test exposed `BadParameter` being swallowed, fixed). Run [649](https://github.com/ekkus93/pdf2audiobook/actions/runs/40535944201) passed. | None |
| 2026-10-27 | 5745660c0e9e8f2c5f9b80aa22b3b6400f0fc5e2 | 4.1–4.3 (R6): `resolve_footnote_policy`, `FootnotePolicyUnknownError`, `regenerate-chapter --footnotes`; spec R6 amended (omit edits, anchor edits, recognizable files). | New symbols, so no parent run was possible; warn and omit legacy cases failed on first run and drove the amended rules. Run [650](https://github.com/ekkus93/pdf2audiobook/actions/runs/40536784884) passed. | None |
| 2026-10-27 | 79c6cdc694de2864e20133cd755f32a98161a7f4 | 5.1–5.2 (R7): no-op publication writes no journal. | Failing at parent: `test_rendering_an_up_to_date_workspace_writes_nothing`. Run [651](https://github.com/ekkus93/pdf2audiobook/actions/runs/40536999764) passed. | None |
| 2026-10-27 | 3c086f516b4b69ef854d3512210ea21f02b7dcf9 | 6.1–6.3 (R8): dry-run, legacy end-to-end, no-mixed-consumption acceptance tests. | Coverage only: the behavior already existed, all 5 passed on first run. Run [652](https://github.com/ekkus93/pdf2audiobook/actions/runs/40537395775) passed. | None |
| 2026-10-27 | 05c126dd0042c66e41415b0585fcc647cda152fd | 7.1–7.5 (R10): `timeout_seconds` per provider (Ollama 300), env override, `/api/ps` 10 s, timeout message, `config show`/`doctor`. | Failing at parent: defaults; config file; env override; factory timeout; context lookup timeout; read-timeout message; fingerprint and cache identity; config show and doctor. Extended `test_environment_mapping_covers_every_declared_variable` with the new variable. Timeout failures keep the "transport failure" wording that `test_llm_provider_matrix` and `test_llm_retry_budget_attempts` match. Run [653](https://github.com/ekkus93/pdf2audiobook/actions/runs/40538097122) passed. | None |
| 2026-10-27 | f451b74211c87a2135ca6fd4a16ff9469fe70371 | 8.1–8.7 (R11): `tqdm` dependency, `progress_display.py`, `--progress/--no-progress`, `general.progress`, stage wiring, summaries. | Feature tests written with the implementation (34 new tests). Extended the env coverage test for `PDF2AUDIOBOOK_PROGRESS`. Pty run with a fake TTS showed bars; a zero-size pty drew nothing until explicit dimensions were passed. Clean-venv wheel install smoke passed locally. Run [654](https://github.com/ekkus93/pdf2audiobook/actions/runs/40540922857) passed. | None |
| 2026-10-27 | 8fca90eba4a8df1a0b9b93beaaa17a50623e9915 | 9.1: merged the follow-up amendments into the review follow-up spec and the main spec; marked the follow-up fixes spec Implemented. | Docs only. Run [655](https://github.com/ekkus93/pdf2audiobook/actions/runs/40541112320) passed on 3.11, 3.12, 3.13. | None |
| 2026-10-27 | 8fca90eba4a8df1a0b9b93beaaa17a50623e9915 | 9.2 final gate: `uv lock --check`, Ruff, format, mypy (43 files) on 3.11, 3.12 and 3.13, `pytest -q -ra`, CLI smoke (`--help`, `config show --json`, `doctor --json`). | 1652 passed, 1 skipped (optional Kitten smoke: the extra is not installed locally). ffmpeg, tesseract and node were available, so their tests ran. | None |
