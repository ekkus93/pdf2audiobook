# PDF2Audiobook Voice Cloning Review Follow-up TODO

**Status:** In progress — R1 commit planning and isolated validation
**Date:** 2026-11-19
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
- [ ] 1.3 Confirm that `git status` shows only `.serena/` and `audiobooks/` and that no private media, weights, caches or workspaces are tracked.

## 2. Warm resume with an unchanged reference (R2)

- [ ] 2.1 Decide between option (a), transcribe locally when synthesis needs a transcript, and option (b), keep the refusal and name the fix. Record the decision and reason in the ledger before implementing.
- [ ] 2.2 Regression test, run against the parent commit: unchanged reference, no transcript, a chapter that needs synthesis. Record the failing test ID.
- [ ] 2.3 Regression test: a missing local ASR backend never downloads or loads a model.
- [ ] 2.4 Regression test: the recorded identity is unchanged unless new transcription produces a different digest.
- [ ] 2.5 Implement the chosen option in `conversion.py` (`_clone_preparation`) and keep the refusal content-free.

## 3. Containment before directory creation (R3)

- [ ] 3.1 Regression test, run against the parent commit: a manifest path that escapes the cache root creates nothing outside it and raises `ConfigError`. Record the failing test ID.
- [ ] 3.2 Regression test: a symlinked component pointing outside the root creates nothing outside it.
- [ ] 3.3 Move the containment check in `tts/catalog.py` `fetch_model` before `mkdir`. Resolve the deepest existing ancestor for paths that do not exist yet, and refuse symlinks that leave the root.
- [ ] 3.4 Confirm the existing fetch and offline reuse tests pass unchanged.

## 4. Single validation table (R4)

- [ ] 4.1 Add a "Current validation state" table to `docs/PDF2AUDIOBOOK_VOICE_CLONING_TODO.md` with one row per gate, each giving commit, date and counts.
- [ ] 4.2 Mark superseded counts in the prose as superseded by the table. Keep the history.
- [ ] 4.3 Check each table count against a run on the named commit, recorded after the last code change.

## 5. Per-task verification (R5)

- [ ] 5.1 For each `[x]` task in the voice cloning TODO, record the implementing file and line(s), the exercising test(s), and a verdict: verified, partially verified (with what is missing) or not verified.
- [ ] 5.2 Record each unchecked task as open, with its reason.
- [ ] 5.3 For each task that is not verified or only partially verified, add a test that verifies it, or untick it with a note.
- [ ] 5.4 Cover the privacy and identity requirements of the specification in the verification, not only the presence of code.

## 6. Honest provenance (R6)

- [ ] 6.1 Label each finding in the ledger as reproduced by a failing test, or as read from code and not reproduced, with the reason.
- [ ] 6.2 Label carried-forward timing and real-model results as recorded evidence from 2026-11-19, not re-measured.

## 7. Finish

- [ ] 7.1 Run the full offline Python suite, the CLI smoke, the wheel and sdist smokes, and the desktop checks on the final commit. Record counts in the table from 4.1.
- [ ] 7.2 Confirm that VC0.03 and VC8.04 remain open and that the ledger says why.
- [ ] 7.3 Record unresolved limitations below.

## Unresolved limitations

(Filled in by 7.3.)

## Progress ledger

| Date | Commit/tree | Completed tasks | Validation | Outstanding gates |
|---|---|---|---|---|
| 2026-11-19 | `451551c` + uncommitted working tree | Spec and TODO drafted from the review; no tasks checked | Review spot checks: 173 cloning and related tests passed; Ruff lint and format clean | R1–R6 |
| 2026-11-19 | `eed3f7d0dfbad873086d0f7889212002eb2372b7` | R1 prerequisite P0 committed/pushed; 1.1 commit plan recorded; 1.2 partial | Isolated index tree `d0439beb56085317e4760714aca6f9d9a10902b7`: 38 tests passed; lock/Ruff/format/CLI smokes passed; mypy 101 modules on 3.11–3.13; detect-secrets 1.5.0 found 0 findings. Python CI #911 (44632710294) passed all three versions: 2,685 passed/4 skipped each; Desktop CI #66 (44632710112) passed, including executable and AppImage walkthroughs | Remaining R1 units and R2–R6; accelerator gates unchanged |

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
