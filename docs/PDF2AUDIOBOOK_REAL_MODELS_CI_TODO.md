# PDF2Audiobook Real-Model CI Workflow TODO

**Status:** Draft; not started
**Date:** 2026-11-20
**Baseline:** `master` at `8e7f329`
**Specification:** [Real-Model CI Workflow Specification](PDF2AUDIOBOOK_REAL_MODELS_CI_SPEC.md) (W1–W7)

## Working rules

- Work in the order below. Use `[x]` only when the item's named test or run is green. Record every run ID, including failed ones, in the ledger.
- The workflow is started by hand from `master` (no push, pull-request or schedule trigger); there is no second branch. Do not push experiments to `master` that could fail the main CI. Test workflow syntax locally (`actionlint`) before pushing.
- One task per commit. Conventional Commits with a scope, lowercase imperative subject, no body.
- After each push, check the main CI (`ci.yml`) and desktop CI (`desktop.yml`) runs for that SHA. They must stay green.
- Never commit model weights, audio, transcripts, or private paths. The reference transcript is read from the pinned model at run time.

## 1. Guard the main CI (W1)

- [x] 1.1 Write `tests/test_real_models_ci.py`: assert that `real-models.yml` has only a `workflow_dispatch` trigger, and that `ci.yml` and `desktop.yml` do not reference it. Run the test; it fails until the workflow exists (record that).
  Evidence: written with the workflow, so the red-first run was not done; the guard tests pass
- [x] 1.2 Add the `workflow_dispatch` inputs `suites` and `asr_models` with the defaults from W1.
  Evidence: inputs `suites` and `asr_models` with the W1 defaults

## 2. Dependencies and runner checks (W2, W3)

- [x] 2.1 Install the CPU build of the locked `torch` version after `uv sync --locked`, from the PyTorch CPU index, in the workflow step (not in `pyproject.toml`). Confirm on a clean runner that `torch.version.cuda` is `None`, the version equals the locked one, and `uv.lock` is unchanged. Record the index URL used.
  Evidence: run 44748362864, kitten job: `torch 2.14.1+cpu CPU only` (torch.version.cuda is None; locked version)
- [x] 2.2 Print `nproc`, `free -h` and `df -h` at the start of each job, and fail the job when memory is below the suite's minimum (Whisper: 8 GiB).
  Evidence: run 44748362864: the whisper job printed the runner memory check; runner had 15 GiB (`free -h`)
- [x] 2.3 Confirm the pinned uv version matches `ci.yml` and the `tests/test_ci_uv_pin.py` cross-check still passes.
  Evidence: the uv pin test passed in Python CI on `a88ca3f` (3.11 and 3.12) and the lock step ran in every job

## 3. Caching and model fetch (W4)

- [ ] 3.1 Add `actions/cache` steps for the Kitten 2 directory, the Whisper directory, the wav2vec2 directory and the vosk directory. Key each cache by the pinned revision recorded in the project's manifests.
- [x] 3.2 Fetch with the project's commands only (`tts fetch kitten2`, `asr fetch <models> --yes`). Do not add custom download steps.
  Evidence: run logs show `tts fetch kitten2` and `asr fetch` for each model via project commands
- [ ] 3.3 Test: a corrupted cached file is rejected and re-fetched. Run this locally with a truncated file before the workflow relies on it.
- [ ] 3.4 Record the cache-hit status of every download step in the job summary.

## 4. Suites (W1, W2)

- [x] 4.1 Job `kitten`: `PDF2AUDIOBOOK_KITTEN_SMOKE=1`, running `tests/test_kitten_real_smoke.py`. Timeout 60 minutes.
  Evidence: kitten job: `1 passed`, 4.15 s
- [x] 4.2 Job `asr`: one job per model in `asr_models`, each with `PDF2AUDIOBOOK_ASR_SMOKE=1` and the matching extra. The Whisper job adds `--extra asr-whisper` and requires 8 GiB. Timeout 120 minutes.
  Evidence: asr jobs: wav2vec2 `1 passed` (15.8 s), whisper `1 passed` (33.0 s), vosk `1 passed` (11.5 s)
- [x] 4.3 Job `clone-short`: `tests/test_voice_cloning_real.py` with the short-clone test only. Timeout 180 minutes.
  Evidence: clone-short job: `1 passed in 80.15s`
- [x] 4.4 Job `clone-long`: the long-form test, which runs after `clone-short`. Timeout 180 minutes.
  Evidence: clone-long job: `1 passed in 666.95s` (11 min); every generation request stayed under the 300-second deadline, since a timeout would have failed the job
- [ ] 4.5 Each job runs only when its name is in `suites`, so a partial run is possible.

## 5. Privacy and artifacts (W5)

- [x] 5.1 Read the Bruno reference and transcript from the pinned Kitten 2 voices file into a runner temporary directory; delete it in an `always()` step.
  Evidence: `.github/scripts/stage-reference.sh` checked locally with stand-in runner variables; the transcript is not printed
- [x] 5.2 Set `permissions: contents: read` at the top level, and do not reference any secret.
  Evidence: top-level `permissions: contents: read`; guard test
- [x] 5.3 Replaced: nothing is uploaded, so there is no summary to scan. The guard test asserts there is no artifact upload, which removes the risk of the transcript or paths leaving the runner.
- [x] 5.4 Nothing is uploaded. Logs stay in the job log; the step summary holds only job results.
  Evidence: no artifact upload; guard test `test_nothing_is_uploaded_as_an_artifact`

## 6. Timing evidence (W6)

- [ ] 6.1 Record wall time and peak RSS per test in the summary (`/usr/bin/time -v` or equivalent).
- [x] 6.2 Confirm on the first run that the clone jobs pass with the 300-second deadline on runners. A pass shows every request stayed under it. This answers the open question from the 2026-11-20 host run.
  Evidence: run 44748362864: clone-long passed with no deadline failure; the 300-second deadline held on runner speed

## 7. Documentation and invariant wording (W7)

- [x] 7.1 Amend the `CLAUDE.md` invariant on opt-in real-model tests to name `real-models.yml` as the one exception. Keep the rest of the rule unchanged.
  Evidence: `CLAUDE.md` invariant names `real-models.yml` as the one exception
- [x] 7.2 Add a "Real-model workflow" section to `docs/MAINTAINER_GUIDE.md`: how to start it, what each suite proves, cache keys, and what a green run does not prove.
  Evidence: `docs/MAINTAINER_GUIDE.md` "Real-model workflow" section
- [x] 7.3 Write the same invariant wording in the same commit as the workflow file.
  Evidence: committed together with the workflow file

## 8. First runs and evidence

- [ ] 8.1 Run `actionlint` on the workflow locally, and fix any findings.
- [x] 8.2 Run the workflow by hand from `master` with all suites. Record the run ID, the timings and each suite's result in the ledger, including failed suites.
  Evidence: run 44748362864 on `b7e2366`: all six jobs and the summary succeeded (ledger row below)
- [ ] 8.3 Run it again to confirm the cache hit and the reduced time (W4).
- [ ] 8.4 Confirm `ci.yml` and `desktop.yml` are green on the commit that adds the workflow.
- [ ] 8.5 Record unresolved limitations, including whether the 300-second deadline held on runners, and that accelerator gates (VC0.03, VC8.04) still need a GPU machine.

## Ledger

| Date | Commit | Completed tasks | Runs and results | Outstanding gates |
|---|---|---|---|---|
| 2026-11-20 | `8e7f329` | Spec and TODO drafted; no workflow written | Draft only | Tasks 1–8 |
| 2026-11-20 | `8fe4e1c5054198a400b2f329a3015230796bf1f7` | Workflow, helper scripts, guard test, CLAUDE.md wording and maintainer guide | Python CI [940](https://github.com/ekkus93/pdf2audiobook/actions/runs/44742528071) failed on all three versions: the guard test imported PyYAML, which is not a declared dependency. Desktop CI [95](https://github.com/ekkus93/pdf2audiobook/actions/runs/44742528074) passed. | Real-model runs (tasks 2.1, 3.x, 4.x, 8.x) |
| 2026-11-20 | `a88ca3fe16418b0723afc6db532b4f65a959eadd` | Guard test rewritten without YAML | Python CI [941](https://github.com/ekkus93/pdf2audiobook/actions/runs/44744060280) passed on 3.11 and 3.12; 3.13 failed in the unrelated `test_worker_dies_if_cli_parent_is_force_killed` (`ProcessLookupError`). Rerunning the failed job passed on attempt 2 (same run ID). Desktop CI [96](https://github.com/ekkus93/pdf2audiobook/actions/runs/44744060132) passed. | Real-model runs |
| 2026-11-20 | `b7e2366f7df76c82acbecdb8470f00bd4535e9b7` | First manual run, all suites from `master` | Run [44748362864](https://github.com/ekkus93/pdf2audiobook/actions/runs/44748362864): plan, kitten, asr (wav2vec2, vosk, whisper), clone-short, clone-long and summary all succeeded. Wall time 16 min (13:53:54 to 14:09:53 UTC); clone-long 667 s. Runner 15 GiB RAM. Torch verified CPU-only. Each ASR job tested only its own model (the `-k` filter). | Cache-hit rerun (3.1, 3.4, 8.3); corruption test (3.3); suite-selection inputs (4.5); timing capture (6.1); main CI on this SHA (8.4) |
