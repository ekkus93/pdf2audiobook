# PDF2Audiobook Voice Cloning Review Follow-up TODO

**Status:** R2–R6 complete; R1.2 remains open only for a historical green-CI acceptance exception
**Date:** 2026-11-19
**Last reviewed:** 2026-11-20
**Baseline:** `master` at `451551c` plus the uncommitted voice-cloning working tree
**Specification:** [Voice Cloning Review Follow-up Specification](PDF2AUDIOBOOK_VOICE_CLONING_REVIEW_SPEC.md) (R1–R6)
**Previous TODO:** [Voice Cloning TODO](PDF2AUDIOBOOK_VOICE_CLONING_TODO.md)

## Working rules

- Work in the order below. Commit R1 first: the later fixes need a committed baseline so their regression tests can run against a parent commit.
- Use `[x]` only when the implementation exists and its named tests pass. Check a parent only when all of its subitems are checked.
- Every fix task has three parts:
  - (a) add the regression test and run it against the parent commit, recording the failing test IDs in the ledger;
  - (b) make the fix;
  - (c) run `/verify`, plus mypy on Python 3.12 and 3.13, and the desktop checks if the commit touches `desktop/`.
- One task per commit. Conventional Commits with a scope, lowercase imperative subject, no body.
- Check CI after every push. A failed run blocks the next task until it is fixed or explained.
- Never commit recordings, transcripts, model weights, conditioning caches, private paths or generated workspaces. Scan with `git status` and a secrets check before each commit.
- Errors, logs and `--json` stay content-free. Fixtures are synthetic and CI stays offline. Real-model runs stay opt-in and outside Git.

## 1. Commit the feature (R1)

- [x] 1.1 Plan the commit series from the VC0–VC8 sections of the existing TODO, in dependency order, with the files for each commit listed in the ledger before committing.
- [ ] 1.2 For each commit, run lint, format, mypy on 3.11–3.13 and the tests that cover its files; push; check CI; record the run in the ledger.
- [x] 1.3 Confirm that `git status` shows only `.serena/` and `audiobooks/` and that no private media, weights, caches or workspaces are tracked.

## 2. Warm resume with an unchanged reference (R2)

- [x] 2.1 Decide between option (a), transcribe locally when synthesis needs a transcript, and option (b), keep the refusal and name the fix. Record the decision and reason in the ledger before implementing.
- [x] 2.2 Regression test, run against the parent commit: unchanged reference, no transcript, a chapter that needs synthesis. Record the failing test ID.
- [x] 2.3 Regression test: a missing local ASR backend never downloads or loads a model.
- [x] 2.4 Regression test: the recorded identity is unchanged unless new transcription produces a different digest.
- [x] 2.5 Implement the chosen option in `conversion.py` (`_voice_run` / `_synthesize_selected`) and keep the refusal content-free.

## 3. Containment before directory creation (R3)

- [x] 3.1 Regression test, run against the parent commit: a manifest path that escapes the cache root creates nothing outside it and raises `ConfigError`. Record the failing test ID.
- [x] 3.2 Regression test: a symlinked component pointing outside the root creates nothing outside it.
- [x] 3.3 Move the containment check in `tts/catalog.py` `fetch_model` before `mkdir`. Resolve the deepest existing ancestor for paths that do not exist yet, and refuse symlinks that leave the root.
- [x] 3.4 Confirm the existing fetch and offline reuse tests pass unchanged.

## 4. Single validation table (R4)

- [x] 4.1 Add a "Current validation state" table to `docs/PDF2AUDIOBOOK_VOICE_CLONING_TODO.md` with one row per gate, each giving commit, date and counts.
- [x] 4.2 Mark superseded counts in the prose as superseded by the table. Keep the history.
- [x] 4.3 Check each table count against a run on the named commit, recorded after the last code change.

## 5. Per-task verification (R5)

- [x] 5.1 For each `[x]` task in the voice cloning TODO, record the implementing file and line(s), the exercising test(s), and a verdict: verified, partially verified (with what is missing) or not verified.
- [x] 5.2 Record each unchecked task as open, with its reason.
- [x] 5.3 For each task that is not verified or only partially verified, add a test that verifies it, or untick it with a note.
- [x] 5.4 Cover the privacy and identity requirements of the specification in the verification, not only the presence of code.

## 6. Honest provenance (R6)

- [x] 6.1 Label each finding in the ledger as reproduced by a failing test, or as read from code and not reproduced, with the reason.
- [x] 6.2 Label carried-forward timing and real-model results as recorded evidence from 2026-11-19, not re-measured.

## 7. Finish

- [x] 7.1 Run the full offline Python suite, the CLI smoke, the wheel and sdist smokes, and the desktop checks on the final commit. Record counts in the table from 4.1.
- [x] 7.2 Confirm that VC0.03 and VC8.04 remain open and that the ledger says why.
- [x] 7.3 Record unresolved limitations below.

## Unresolved limitations

- **R1.2 historical acceptance:** all commit checks and exact-head CI evidence are
  recorded, but `ed160e6b7ce509ab3c914281207add10bee7739b` has failed Python
  CI #913 (44636305313) because an existing SDK test update was staged later.
  Corrective `0cd79d6084da8491047135eb4b7408968ee731cf` is green. History was
  not rewritten. The spec's literal “Every feature commit has a green CI run”
  needs an accepted historical exception; a green successor cannot satisfy it.
- **Original VC5.05 (resolved in `282f6f0`; see the VC5.05 TODO):** dependency-free completed conversion can attempt synthesis
  when optional backend metadata is removed while the recording and transcript
  remain. The strict expected-failure test and partial audit verdict retain this
  gap; the original task is unticked. Fixing this extra boundary is outside R2/R3.
- **Original VC0.03 / VC8.04:** supported-accelerator measurements remain deferred
  to another machine. The current host's AMD device is not an accessible tested
  cloning accelerator, and the prepared environment is CPU-only. No GPU run is
  claimed. CPU, listening, continuity, repair and cancellation results are recorded
  evidence from 2026-11-19, not re-measured; pacing was slower but speaker identity
  and consistency were confirmed by the user.
- Native software playback/seek was exercised under Xvfb; physical speaker output
  was not measured in this review. The worker remains POSIX-only as documented.

## Progress ledger

| Date | Commit/tree | Completed tasks | Validation | Outstanding gates |
|---|---|---|---|---|
| 2026-11-19 | `451551c` + uncommitted working tree | Spec and TODO drafted from the review; no tasks checked | Review spot checks: 173 cloning and related tests passed; Ruff lint and format clean | R1–R6 |
| 2026-11-19 | `eed3f7d0dfbad873086d0f7889212002eb2372b7` | R1 prerequisite P0 committed/pushed; 1.1 commit plan recorded; 1.2 partial | Isolated index tree `d0439beb56085317e4760714aca6f9d9a10902b7`: 38 tests passed; lock/Ruff/format/CLI smokes passed; mypy 101 modules on 3.11–3.13; detect-secrets 1.5.0 found 0 findings. Python CI #911 (44632710294) passed all three versions: 2,685 passed/4 skipped each; Desktop CI #66 (44632710112) passed, including executable and AppImage walkthroughs | Remaining R1 units and R2–R6; accelerator gates unchanged |
| 2026-11-20 | `6fd242d817d2bbe135ea3c0a849b3ce60ab0f5a8` | R1 VC0 design, commit plan and P0 CI evidence committed/pushed | Isolated 23 passed; lock/Ruff/format/CLI and mypy 101 modules on 3.11–3.13 passed; secret scan 0. Exact-head Python CI #912 (44634772551) and Desktop CI #67 (44634772470) passed | Remaining R1 units and R2–R6; accelerator gates unchanged |
| 2026-11-20 | `ed160e6b7ce509ab3c914281207add10bee7739b` | R1 VC1 pinned model catalog/cache primitives committed; CI failure reproduced | Isolated 22 passed; lock/Ruff/format/CLI and mypy 103 modules on 3.11–3.13 passed. Secret scan: 33 public manifest revisions/checksums reviewed, no real secrets. Python CI #913 (44636305313) failed on the old optional-SDK expectation (2,686 passed/4 skipped/1 failed per version); Desktop CI #68 (44636305380) passed | Historical Python CI remains failed; corrected by the next commit, not rewritten |
| 2026-11-20 | `0cd79d6084da8491047135eb4b7408968ee731cf` | R1 VC1 corrective test assertion committed/pushed | Isolated 25 passed; lock/Ruff/format/CLI and mypy 103 modules on 3.11–3.13 passed; secret scan 0. Python CI #914 (44637479642) passed all three versions with 2,687 passed/4 skipped each and CLI/wheel/sdist smokes; Desktop CI #69 (44637479706) passed | Remaining R1 units; original ed160e6 CI history still red; R2–R6 and accelerator gates remain |
| 2026-11-20 | `cdd056079d0d87e65f4f45f40ebac2aa06f59062` | R1 CI failure/recovery evidence commit (partial R1) | Python #915 (44706154248) passed; Desktop #70 (44706154237) attempt 1 failed at the AppImage review-window-close timeout; attempt 2 passed both executable and AppImage flows. No code changed for the rerun. | Remaining R1 units and R2–R6; historical ed160e6 Python failure and VC0.03/VC8.04 accelerator gates remain open. |
| 2026-11-20 | `0e22c82b46e1f0330d5da5e13b048fe7287ad087` | R1 VC2 private reference/configuration selection (partial R1) | Python #916 (44707452180) passed all three versions: 2,728 passed/4 skipped each, mypy 107 modules, CLI and wheel/sdist smokes. Desktop #71 (44707452181) passed both native walkthroughs. Isolated local subset 160 passed; all three mypy versions, lock/Ruff/format/CLI passed; three non-secret scanner flags reviewed. | Remaining R1 units and R2–R6; historical ed160e6 Python failure and VC0.03/VC8.04 accelerator gates remain open. |
| 2026-11-20 | `731c8a99d9f6d31336818d7bc8b81ce212ba6cc2` | R1 VC3 isolated offline speech/ASR workers (partial R1) | Python #917 (44707705390) passed all three versions: 2,735 passed/4 skipped each, mypy 109 modules, CLI and wheel/sdist smokes. Desktop #72 (44707705359) passed both native walkthroughs. Isolated local subset 58 passed; lock/Ruff/format/CLI and all three mypy versions passed; one public golden hash scanner flag reviewed. | Remaining R1 units and R2–R6; historical ed160e6 Python failure and VC0.03/VC8.04 accelerator gates remain open. |
| 2026-11-20 | `3044e742fd397fec6bfc58f661c16a0bc3afbea3` | R1 partial: VC4 CLI conversion, repair and protocol contracts | Python #918 (44708223720): 2,740 passed/4 skipped on each of 3.11–3.13, mypy 110 modules, CLI/wheel/sdist passed; Desktop #73 (44708223845) passed executable and AppImage walkthroughs. Local 94 Python, 356 Vitest, 110 Rust unit + seven permission tests passed; 66 public fixture checksum/revision scanner flags reviewed. | Final R1 CI/evidence, R2–R6; historical ed160e6 Python failure and accelerator gates remain open. |
| 2026-11-20 | `7e873e525e767175282c081d317ec3b594e4efd8` | R1 partial: VC5 cache, conversion and repair acceptance tests | Python #919 (44708513801): 2,774 passed/6 skipped on each of 3.11–3.13, all static/CLI/wheel/sdist checks passed; Desktop #74 (44708513495) passed both walkthroughs. Local 85 passed/two real-model tests intentionally skipped; secret scan 0. | Final R1 CI/evidence, R2–R6; historical ed160e6 Python failure and accelerator gates remain open. |
| 2026-11-20 | `8a88b7d04f1fa1e83ab7ba3593e8934f2097501d` | R1 partial: VC6 typed Tauri bridge, private drafts and shared config setup | Python #920 (44708954277): 2,774 passed/6 skipped on each version, all static/CLI/wheel/sdist checks passed; Desktop #75 (44708954310) passed both walkthroughs, 119 Rust unit + seven permission tests (four opt-in ignored). Local 59 Python and 356 Vitest passed; one existing synthetic fixture scanner flag reviewed. | Final R1 CI/evidence, R2–R6; historical ed160e6 Python failure and accelerator gates remain open. |
| 2026-11-20 | `066be91cd7d8f0c279e2d6541f41d2d3b848213a` | R1 VC7 clone controls and native workflow | Python #922 (44709697687) passed all versions with 2,774 passed/6 skipped each. Desktop #77 (44709697645) passed the clone-enabled executable and AppImage walkthroughs: picker, transient draft, synthesis, resume, repair, cancel and cleanup. Local 64 Python, 383 Vitest, 119 Rust unit + seven permission tests and all static/build checks passed; secret scan 0. | Review audit/final gates; historical ed160e6 CI exception and accelerator acceptance remain open. |
| 2026-11-20 | `f981812c51613f6ca02a859a2b1bd6faebd4ff01` | R1 VC8 setup, configuration and voice-cloning guides | Exact-head Python #923 (44710034100) and Desktop #78 (44710034119) passed, including clean wheel/sdist and both native clone walkthroughs. Local 39 Python, 383 Vitest, 119 Rust unit + seven permission tests, all three mypy targets and remaining static/build/CLI checks passed; six documentation placeholders/environment-name scanner flags reviewed. | Review audit/final gates; historical ed160e6 CI exception and accelerator acceptance remain open. |
| 2026-11-20 | `c1523415034f2563178e2dfe90fe5cb2c9ad4ac8` | R2 warm-resume identity and regeneration reason | Parent a01cfdc reproduced three failures/one pass before the fix; isolated corrected subset 89 passed with all Python static/CLI gates and mypy 110 modules on 3.11–3.13, secret scan 0. Python #925 (44710917499) passed all versions with 2,778 passed/6 skipped each, CLI and wheel/sdist smokes. Desktop #80 (44710917478) passed both clone-enabled native walkthroughs. | Review audit/final gates; historical ed160e6 CI exception and accelerator acceptance remain open. |
| 2026-11-20 | `8888b4e716e8ca307b887db6aed5928fded1f1de` | R3 containment before directory creation | Immediate-parent traversal/symlink tests both failed before the fix; isolated 83 passed and all Python static/CLI gates plus 110-module mypy on 3.11–3.13 passed; secret scan 0. Python #926 (44711393593) passed all versions with 2,780 passed/6 skipped each and CLI/wheel/sdist smokes. Desktop #81 (44711393418) passed both clone-enabled native flows. | VC5.05 known resume limitation; VC0.03/VC8.04 hardware gates; historical R1 ed160e6 CI exception. |
| 2026-11-20 | `99416560b9081dd61f8fecd1c52d870fdc0a4c0f` | R5 additional acceptance coverage and reopened VC5.05; R4 final-code counters | Local full suite 2,807 passed/6 skipped/1 strict expected failure; lock/Ruff/format, three 110-module mypy targets, CLI, clean wheel/sdist installs, 384 Vitest, 120 Rust unit + seven permission tests, three explicit real-CLI integrations and 70.39-s native synthetic walkthrough passed. Python #928 (44713371948) confirms the same full-suite counts on all three versions. Desktop #83 (44713371693) passed, including both clone-enabled native flows. Two old documentation placeholder scanner findings reviewed. | VC5.05 known resume limitation; VC0.03/VC8.04 hardware gates; historical R1 ed160e6 CI exception. |

## R1 commit plan (recorded before staging)

Each candidate is exported from the Git index into an isolated checkout. Local checks use
that checkout's environment, so future worktree files cannot satisfy missing imports. Shared
files are staged progressively; their final working-tree contents are preserved. The existing
host-memory test repair is a prerequisite, followed by VC0–VC8 in dependency order.

| Order | Commit unit | Exact paths (shared-file portions noted) |
|---|---|---|
| P0 | `test(verification): isolate host memory in offline cli checks` | `tests/test_verify_audio_cli.py` |
| VC0 | `docs(voice): record cloning baseline and review plan` | `docs/PDF2AUDIOBOOK_VOICE_CLONING_SPEC.md`, `docs/PDF2AUDIOBOOK_VOICE_CLONING_TODO.md`, `docs/PDF2AUDIOBOOK_VOICE_CLONING_REVIEW_SPEC.md`, `docs/PDF2AUDIOBOOK_VOICE_CLONING_REVIEW_TODO.md`; baseline CI evidence in `docs/PDF2AUDIOBOOK_TODO.md` |
| VC1 | `feat(tts): pin full model artifacts and offline catalog` | `src/pdf2audiobook/tts/catalog.py`, `src/pdf2audiobook/tts/kitten2_manifest.json`, `src/pdf2audiobook/tts/private.py`, `src/pdf2audiobook/tts/__init__.py`, `uv.lock`; catalog/package-data/SDK portions of `pyproject.toml`; catalog-only portion of `tests/test_voice_cloning.py` |
| VC2 | `feat(tts): resolve private reference voice selections` | `src/pdf2audiobook/config.py`, `src/pdf2audiobook/config_file.py`, `src/pdf2audiobook/tts/selection.py`, `src/pdf2audiobook/tts/cloning.py`, `src/pdf2audiobook/tts/private.py`, `src/pdf2audiobook/tts/worker_client.py`, `src/pdf2audiobook/cli/configuration.py`, `src/pdf2audiobook/cli/options.py`, `tests/test_config.py`, `tests/test_config_init.py`; configuration portions of `src/pdf2audiobook/cli/__init__.py` and `src/pdf2audiobook/cli/_core.py`; corresponding mypy entries and selection/reference tests in shared files |
| VC3 | `feat(tts): isolate local reference speech workers` | `src/pdf2audiobook/tts/clone_worker.py`, `src/pdf2audiobook/tts/clone_provider.py`; corresponding mypy entries in `pyproject.toml`; remaining worker/provider tests in `tests/test_voice_cloning.py` |
| VC4 | `feat(cli): integrate cloned conversion and safe repair` | `src/pdf2audiobook/cli/__init__.py`, `src/pdf2audiobook/cli/_core.py`, `src/pdf2audiobook/cli/tts_models.py`, `src/pdf2audiobook/cli/info.py`, `src/pdf2audiobook/cli/convert.py`, `src/pdf2audiobook/cli/batch.py`, `src/pdf2audiobook/cli/verify.py`, `src/pdf2audiobook/conversion.py`, `src/pdf2audiobook/pipeline.py`, `src/pdf2audiobook/verification/reference.py`, `tests/test_function_length.py`, `tests/test_cli_help_examples.py`, `tests/test_cli_voices.py`, `tests/test_doctor_optional_kitten.py`, `tests/test_verification_optional.py`, `tests/test_desktop_contracts.py`; final CLI mypy entry in `pyproject.toml`; typed protocol files listed next |
| VC4 protocol | Included atomically with CLI behavior | `desktop/contracts/convert-dry-run.schema.json`, `desktop/contracts/doctor.schema.json`, `desktop/contracts/error.schema.json`, `desktop/contracts/voices.schema.json`, `desktop/contracts/tts-fetch.schema.json`, `desktop/contracts/tts-models.schema.json`, `desktop/contracts/voice-clone.schema.json`, `desktop/src/screens/reasons.tsx`, `desktop/src/screens/reasons.test.tsx`, `desktop/src-tauri/src/engine/contracts.rs`, `desktop/src-tauri/src/engine/result.rs`, `desktop/src-tauri/tests/fixtures/error.voice-clone.stderr`, `desktop/src-tauri/tests/fixtures/tts-fetch.json`, `desktop/src-tauri/tests/fixtures/tts-models.json`, `desktop/src-tauri/tests/fixtures/voice-clone.json`; fixture/result guards are staged atomically with the schemas |
| VC5 | `test(voice): verify cloning cache and repair invariants` | `tests/test_voice_cloning_conversion.py`, `tests/test_voice_cloning_real.py` (cache-safe conversion/repair implementation is inseparable from the preceding CLI integration) |
| VC6 | `feat(desktop): bridge private voice selection and setup` | `desktop/src-tauri/src/commands.rs`, `desktop/src-tauri/src/config.rs`, `desktop/src-tauri/src/voice.rs`, `desktop/src-tauri/src/lib.rs`, `desktop/src-tauri/src/privacy.rs`, `desktop/src-tauri/src/settings.rs`, `desktop/src-tauri/src/engine/request.rs`, `desktop/src-tauri/src/engine/result.rs`, `desktop/src-tauri/tests/fixtures/tts-fetch.json`, `desktop/src-tauri/tests/fixtures/tts-models.json`, `desktop/src-tauri/tests/fixtures/voice-clone.json`, `desktop/src/engine/api.ts`, `desktop/src/engine/types.ts` |
| VC7 | `feat(desktop): edit clone options and exercise native flows` | `desktop/src/App.tsx`, `desktop/src/screens/AudioCheck.tsx`, `desktop/src/screens/BookPage.tsx`, `desktop/src/screens/BookPage.test.tsx`, `desktop/src/screens/Run.tsx`, `desktop/src/screens/Settings.tsx`, `desktop/src/screens/Settings.test.tsx`, `desktop/src/screens/CliConfigEditor.tsx`, `desktop/src/screens/CliConfigEditor.test.tsx`, `desktop/src/screens/CloneControls.tsx`, `desktop/src/screens/CloneControls.test.tsx`, `desktop/src/screens/book.css`, `desktop/src/screens/settings.css`, `desktop/src/screens/bookOptions.ts`, `desktop/src/screens/bookOptions.test.ts`, `desktop/e2e/walkthrough.mjs`, `desktop/e2e/fake_clone.py`, `desktop/e2e/isolated.sh`, `.github/workflows/desktop.yml`, `tests/test_desktop_ci.py` |
| VC8 | `docs(voice): document local setup privacy and acceptance` | `README.md`, `desktop/README.md`, `docs/MAINTAINER_GUIDE.md`, `docs/PDF2AUDIOBOOK_SPEC.md`, `docs/PDF2AUDIOBOOK_TAURI_SPEC.md`, `docs/guides/README.md`, `docs/guides/cli.md`, `docs/guides/configuration.md`, `docs/guides/development.md`, `docs/guides/voices.md`, `docs/guides/voice-cloning.md` |

Separate documentation commits record each completed exact-head CI result in the main and
review ledgers, as required by `CLAUDE.md`. No `.serena/`, `audiobooks/`, media, model artifacts,
private transcripts, generated outputs or validation environments enter the index. Shared-file
staging details and any dependency adjustments are recorded before the affected commit.

### Provenance at start

- R1 uncommitted-state finding: reproduced by `git status --short` and `git log` on `master`.
- R2 warm-resume and R3 containment findings: read from code, not yet reproduced; regression
  tests must run against their committed parent before fixes.
- R4 ledger inconsistency: reproduced by reading the conflicting historical totals in the
  existing TODO. R5 coverage gap: the earlier review recorded spot checks; a complete table
  is still required.
- Earlier real-model, timing and listening results are recorded evidence from 2026-11-19,
  not re-measured by this follow-up. Hardware acceptance remains deferred to another machine.

- Dependency note before VC4 staging: the shared Rust contract guard enumerates all schemas.
  Its three new success fixtures and reason-code parser tests therefore belong to VC4's
  atomic protocol update, ahead of the remaining VC6 request/transport implementation.
- Remote baseline was fetched and matches local `451551c88b0642b42bc63270a1aed4a604afef60`.
  Existing Python CI #910 (run 44315565883) and Desktop CI #65 (run 44315565794) succeeded
  for that exact baseline. This is fetched CI evidence, not a new local or real-model run.

- Dependency note before VC1 staging: catalog readiness imports the POSIX capability guard
  from `tts/private.py`; stage that existing cache/lock utility and its mypy entry with VC1.
  The remaining selection and worker-client dependencies stay in VC2.

- P0 completed: exact-head Python CI #911 (run 44632710294) and Desktop CI #66
  (run 44632710112) both passed for `eed3f7d0dfbad873086d0f7889212002eb2372b7`.
  Python 3.11, 3.12 and 3.13 each report **2,685 passed, 4 skipped**, with 101-module mypy,
  CLI and installed wheel/sdist smokes passing. Desktop native executable/AppImage flows
  passed. This is fetched CI evidence; recorded real-model runs were not repeated.

- R2 source-trace qualification (before reproducer): `_voice_run` restores the saved identity,
  but `_synthesize_selected` already calls `complete_transcript` when pending speech lacks a
  transcript, then replans. The initially described refusal is therefore **not reproduced**;
  the review had not traced that later path. Parent-commit tests will distinguish existing
  rehydration behavior from any same-digest identity or changed-digest reason-reporting gap.

### VC1 CI staging correction (planned before corrective commit)

- Python CI #913 (run 44636305313) failed on all three versions at
  `tests/test_verification_optional.py::test_the_default_install_has_no_asr_package`:
  the SDK pin was committed while its existing updated test assertion was left for VC4.
  The full runs each had **2,686 passed, 4 skipped, 1 failed**. This is a reproduced staging
  omission, not an SDK or inference failure; the failed SHA/run will not be erased or relabelled.
- Corrective unit: `test(tts): align optional sdk pin contract`, exact path
  `tests/test_verification_optional.py`. Move this already-existing assertion change forward
  from VC4. Validate it against the pinned optional dependency before committing/pushing.
- The original `ed160e6b7ce509ab3c914281207add10bee7739b` remains a historically failing CI
  revision. A green corrective successor does not make that original run green. Preserve this
  qualification when assessing R1's strict per-commit green-CI acceptance criterion.

- CI observation after resumption (2026-11-20): the VC1 corrective head has green Python
  and Desktop runs. The missing test assertion has been moved forward; no production
  behavior was changed to resolve the CI failure. Record the failed and recovered heads
  in this separate documentation commit before advancing to VC2.

### VC2 checkpoint (2026-11-20)

- Committed/pushed `0e22c82b46e1f0330d5da5e13b048fe7287ad087` after isolated
  validation: 160 passed; lock, Ruff lint/format, CLI smokes and mypy 107 modules
  on 3.11–3.13 passed. Three scanner flags were configuration variable names or
  a public golden identity hash, not secrets. CI is pending.
- The preceding evidence commit `cdd056079d0d87e65f4f45f40ebac2aa06f59062`
  passed Python #915 (44706154248). Desktop #70 (44706154237), attempt 1,
  failed at the AppImage review-window-close timeout; its native executable flow,
  build and other checks passed. This is a reproduced walkthrough timeout on a
  documentation-only revision, not a demonstrated voice-cloning regression.
  A failed-job rerun was requested; do not label the original attempt green.
- VC2's first test invocation selected a nonexistent test file (exit 4, no tests
  collected); correcting the command, without changing code, yielded 160 passed.

- VC3 committed/pushed `731c8a99d9f6d31336818d7bc8b81ce212ba6cc2` after isolated 58 tests, lock, Ruff lint/format,
  mypy on 3.11–3.13 and CLI smokes passed. The scanner flag is the fixed legacy
  identity golden hash. Exact-head CI is pending; no pending result is counted
  as passed. VC2's CI was checked and still running before this R1 unit.

- Exact-head Python CI #916 (44707452180) passed VC2 on all three Python
  versions: **2,728 passed, 4 skipped** each, 107-module mypy and installed
  wheel/sdist smokes passed. Python #917 (44707705390) also passed VC3;
  detailed counters and the still-running Desktop jobs will be recorded in the
  separate CI-evidence commit. Pending jobs are not green evidence.
- R5 working-tree probe reproduced an additional cache limitation: after a
  simulated installed Torch version is removed, retaining a reference and its
  transcript changes `backend_versions` and synthesizes finished chapters again.
  The earlier probe without a simulated installed backend passed because both
  identities were empty. Reproduce against the completed committed feature
  before assigning the final audit verdict; do not silently broaden R2's fix.

- VC4 committed/pushed `3044e742fd397fec6bfc58f661c16a0bc3afbea3`: isolated
  94 Python tests passed; lock, Ruff, mypy 110 modules on 3.11–3.13, CLI smokes,
  desktop lint/typecheck/build, 356 Vitest tests, Rust fmt/clippy, 110 Rust unit
  and seven permission tests passed (one existing opt-in Rust test ignored).
  All 66 scanner findings were public model/ASR revisions and artifact checksums
  in the two new diagnostic fixtures. CI pending.

- VC5 committed/pushed after isolated **85 passed, 2 intentionally skipped**
  (the two opt-in real-model tests); lock, Ruff lint/format, mypy 110 modules
  on 3.11–3.13 and CLI smokes passed. No scanner findings. Real-model evidence
  from 2026-11-19 was not re-measured. Exact SHA and CI results follow in the
  separate evidence ledger after the jobs finish.

- VC6 committed/pushed `8a88b7d04f1fa1e83ab7ba3593e8934f2097501d`: isolated
  59 Python tests; all Python static/CLI gates; 356 Vitest, 119 Rust unit and
  seven permission tests passed (four Rust opt-in tests ignored). Private
  transcript lifecycle covers completion, failure, cancellation and shutdown.
  One secret-scan flag was an existing synthetic invalid password-env fixture.
  Exact-head Python #920 (44708954277) and Desktop #75 (44708954310) pending.

### Committed feature baseline and R2 decision (2026-11-20)

- VC7 `066be91cd7d8f0c279e2d6541f41d2d3b848213a`: isolated 64 Python tests,
  383 Vitest tests in 21 files, 119 Rust unit and seven permission tests passed
  (four opt-in Rust tests ignored). Lock/Ruff/format, mypy 110 modules on
  3.11–3.13, CLI and desktop lint/typecheck/build/fmt/clippy passed; secret scan 0.
- VC8 `f981812c51613f6ca02a859a2b1bd6faebd4ff01`: isolated 39 tests and the
  same Python/desktop gates passed; six scanner flags were documented example
  placeholders or environment-variable names, not credentials.
- R1.3 verified at `f981812c51613f6ca02a859a2b1bd6faebd4ff01`: `git status
  --short` showed only `.serena/` and `audiobooks/`. All 97 new/changed tracked
  paths since `451551c` were checked for private media, weights, conditioning
  caches and workspaces; none were present. The original feature is now committed
  in dependency order. R1.2 stays open until pending CI is recorded, with the
  historical `ed160e6` Python failure retained as an explicit acceptance exception.
- R2.1 decision: **option (a)**. Keep the existing lazy local transcription when
  pending synthesis needs text. User selection of clone mode without a supplied
  transcript enables that documented local path; unavailable ASR fails before a
  worker or network action. The original refusal allegation was not reproduced
  because `_synthesize_selected` already rehydrates after `_voice_run`.
- The R2 fix will preserve the recorded identity when normalized transcript SHA-256
  is unchanged, including its original ASR provenance. If text differs, replan
  affected synthesis and record the content-free `voice_reference_changed` reason.
  The actual integration function is `_voice_run`, not `_clone_preparation`.

### Parent-commit reproduction (2026-11-20)

Parent `a01cfdcdd6a4b7907abe53d06b8ce24ec0abfeee` (isolated Git tree
`724f2ced3910226eda477dd7957913fe06c67be2`), before any runtime review fix:

- R2: **3 failed, 1 passed**. Failing tests:
  `test_warm_resume_rehydrates_same_transcript_without_changing_identity[speed]`,
  the same test `[chapter]`, and
  `test_changed_auto_transcript_regenerates_and_records_reason`.
  The first two reached successful local transcription/synthesis but changed
  provenance despite identical text SHA-256; the third regenerated speech but
  lacked `reason_code`. `test_missing_asr_on_warm_resume_never_starts_a_worker_or_downloads`
  passed with worker/network traps. The originally alleged refusal remains
  read from code, **not reproduced**, because the later rehydration path works.
- R3: **2 failed** at
  `test_fetch_rejects_escaping_parent_before_creating_directories[traversal]`
  and `[symlink]`: the refusal happened after an outside `new/` directory existed.
  Both failures were reproduced with synthetic manifest entries and no network.
- R5 additional finding: `test_finished_audio_reuses_without_sdk_while_reference_exists`
  failed (eight synthesis calls instead of the original four) when simulated
  Torch metadata was removed while the reference and transcript remained.
  This reproduces the working-tree probe on committed code. It affects shared
  spec §6/§9 dependency-free completed-audio reuse; record VC5.05 as partial
  rather than include an unrelated behavioral change in R2.

Full logs and reproducer JSON remain outside Git in the review validation cache;
only synthetic regression test source and content-free findings enter the repository.

- R2 final repository test source was also run against the unchanged parent
  runtime before editing: `tests/test_voice_cloning_resume.py` reproduced the
  same **three failures / one pass**. Applied fix: preserve saved provenance on
  an equal normalized text digest; after a changed digest, replan and record
  `voice_reference_changed` in each regenerated chapter's conversion status.
  No model-download or readiness path changed. Validation is in progress.

- R2 focused validation after the fix: **81 passed** across warm resume, clone
  conversion/reference and function-length tests. The three reproduced failing
  cases now pass; missing-ASR refusal still starts no worker or network action.
  Equal digests retain the original identity; differing text records the reason
  and regenerates even the otherwise unchanged selected chapter. Full per-commit
  static/type/subset validation is running in an isolated index export.

- R2 committed/pushed `c1523415034f2563178e2dfe90fe5cb2c9ad4ac8` after
  isolated **89 passed**, lock/Ruff/format/CLI smokes and mypy 110 modules on
  3.11–3.13; secret scan 0. Exact-head Python #925 (44710917499) and
  Desktop #80 (44710917478) are pending; no pending result is counted as passed.
- R3 repository tests were rerun against their immediate parent
  `c1523415034f2563178e2dfe90fe5cb2c9ad4ac8` **before the containment fix**:
  both traversal and symlink variants of
  `tests/test_tts_cache_containment.py::test_fetch_rejects_escaping_parent_before_creating_directories`
  failed because an outside directory existed. Moved the unchanged content-free
  refusal before mkdir, using `resolve(strict=False)` to resolve existing
  ancestors/symlinks while retaining a nonexistent suffix. Validation in progress.

- R3 focused validation passed **79 tests**, including both new containment
  regressions and the unchanged normal fetch, offline reuse, interruption,
  cloning conversion and function-length tests. Per-commit isolated checks run
  before commit; R3 changes no identity or refusal message.

- R3 committed/pushed `8888b4e716e8ca307b887db6aed5928fded1f1de` after
  isolated **83 passed**, all Python static/CLI gates and mypy 110 modules
  on 3.11–3.13; secret scan 0. Python #926 (44711393593) and Desktop #81
  (44711393418) pending. R5 new focused Python coverage passes **27 tests**
  plus one strict expected failure documenting the unresolved retained-reference
  dependency-removal case. No production behavior change is planned for that case.

- R5 adds 27 passing Python acceptance cases and a strict expected failure for
  the reproduced VC5.05 limitation; the original task is reopened (37/40 checked).
  Added clone-specific Rust Details/Debug/event-log/generic-error marker coverage
  and frontend repair-request parity. Structured CLI error messages are a trusted
  protocol boundary; their content-free behavior is tested on the real Python
  CLI, while Rust tests ensure raw unstructured stderr cannot reach generic errors.
- R5 CI maintenance: the original feature changed Desktop CI's apt package list.
  `MAINTAINER_GUIDE.md` explicitly requires a cache-key bump for that change;
  refresh its documented key and `desktop.yml` from v2 to v3. This changes no
  application behavior. Full final-source Python and desktop checks follow.

- R4 authoritative table now names final code
  `99416560b9081dd61f8fecd1c52d870fdc0a4c0f` for every gate, with date and
  counters verified against local exported-tree logs. Python CI #928 (44713371948)
  confirms **2,807 passed, 6 skipped, 1 xfailed** on 3.11/3.12/3.13. Clean wheel
  and sdist imports/three smokes each, 384 Vitest, 120 Rust unit + seven permission
  tests, three explicit real-CLI integrations and native synthetic walkthrough
  (70.39 s) passed. Four Rust opt-ins are ignored by default; only the real-model
  bridge remains unrun in this review. Current Desktop #83 (44713371693) is pending.
  Older software counters/timings are explicitly historical and superseded;
  recorded 2026-11-19 real-model/listening evidence was not re-measured.

- R5 complete task audit: [40-row verification table](PDF2AUDIOBOOK_VOICE_CLONING_REVIEW_AUDIT.md)
  links implementing source and exercising tests at final code
  `99416560b9081dd61f8fecd1c52d870fdc0a4c0f`. Every original clause is recorded:
  **37 verified, one partially verified/open (VC5.05), two open hardware gates**.
  All remaining checked tasks have inspected code plus exercising evidence.
  Clone-specific privacy, legacy/active identity and per-layer invalidation are
  covered explicitly. Three default-ignored offline Rust CLI integrations were
  run and passed; only the real-model Rust bridge is unrun in this review.
  Native dark/light controls were captured and visually inspected; playback
  controls/seek ran under Xvfb, without assessing physical speaker output.

- R6 provenance reconciliation: the review spec now distinguishes the original
  non-reproduced refusal inference from the three reproduced R2 failures, corrects
  the integration function name, records parent-before-fix R3 evidence, and names
  the independently reproduced VC5.05 gap. Git/CI inspection establishes R1;
  historical counter inspection establishes R4; all 40 source/test rows establish
  R5 coverage. Carried CPU/model/timing/listening results are explicitly recorded
  2026-11-19 evidence, not re-measured. The main feature spec retains its reuse
  requirement while documenting that the new VC5.05 case remains unmet.

- Finding classifications: R1 is reproduced by read-only Git status/history
  inspection (not a runtime unit-test failure). R2's original refusal is read
  from code/not reproduced because later lazy transcription exists; its actual
  identity/reporting failures were reproduced before the fix. R3 is reproduced
  by two parent-commit failures before its fix. R4/R5 are observed documentation
  inconsistencies/coverage gaps, not claimed runtime failures. The extra VC5.05
  runtime boundary is reproduced by a failing parent test and remains open.

### Final review verification (2026-11-20)

- Final code `99416560b9081dd61f8fecd1c52d870fdc0a4c0f` has green exact-head
  Python #928 (44713371948) and Desktop #83 (44713371693). Python 3.11,
  3.12 and 3.13 each report **2,807 passed, 6 skipped, 1 xfailed** with mypy,
  CLI and installed wheel/sdist smokes. Desktop CI confirms **384 Vitest tests**,
  **120 Rust unit + seven permission tests**, production installers, and both
  executable/AppImage clone walkthroughs. Default-ignored offline Rust CLI tests
  were also run locally: clone conversion/resume/repair, shared config and
  read-only requests, **three passed**. Only the real-model bridge was not repeated.
- The authoritative table records every gate on that exact code revision after
  the last code change. Subsequent commits are documentation records, with their
  own scoped Python/static/CLI verification and CI checks. No code changed after
  final validation. The complete audit resolves all 40 original task clauses.
- VC0.03 and VC8.04 remain open with hardware prerequisites recorded; VC5.05 is
  additionally reopened. Remaining strict R1.2 qualification is isolated above.
  No private media/weights/caches/workspaces entered Git, and owned native
  processes/ports were cleaned after the successful local walkthrough.
