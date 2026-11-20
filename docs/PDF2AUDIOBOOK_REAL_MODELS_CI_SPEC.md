# PDF2Audiobook Real-Model CI Workflow Specification

**Status:** Proposed (draft; not approved)
**Date:** 2026-11-20
**Companion:** [Real-Model CI Workflow TODO](PDF2AUDIOBOOK_REAL_MODELS_CI_TODO.md)
**Baseline:** `master` at `8e7f329` (R1 criterion reworded)
**Supplements:** `docs/MAINTAINER_GUIDE.md` (CI and opt-in tests), [Voice Cloning Specification](PDF2AUDIOBOOK_VOICE_CLONING_SPEC.md) (§9 real-model acceptance), [Audio Verification Guide](guides/audio-verification.md)

## 1. Purpose and scope

The opt-in real-model tests currently run only on a developer's machine. This makes them slow, depends on that machine's free memory, and leaves no record of a passing run. This specification adds a **separate, manually started workflow** that runs them on GitHub-hosted runners:

- the Kitten real-model smoke test;
- the three real ASR backends (`whisper`, `wav2vec2`, `vosk`);
- the real CPU voice-cloning tests, short and long-form.

It does not change the main CI, does not gate pull requests or pushes, and does not measure voice quality. A green run shows that the real models load and produce output on a clean runner. It does **not** show speaker similarity, pacing, or audible quality, which still need a person listening.

### Why this is a separate workflow

`CLAUDE.md` says CI must not depend on the network, and that real-model checks are opt-in and never part of CI. This workflow keeps both rules for the main CI: the real-model job is not in `ci.yml` and is not a required check. It is a deliberate exception for an explicitly started run, and the wording of `CLAUDE.md` is amended to say so (W7 below).

## 2. Requirements

### W1: Trigger and gating

- Trigger: `workflow_dispatch` only, started by hand, with inputs `suites` (`kitten`, `asr`, `clone-short`, `clone-long`, default: all) and `asr_models` (default: `wav2vec2,vosk,whisper`).
- No `push`, `pull_request` or `schedule` trigger. The workflow never runs on its own; a schedule would need a new decision.
- The workflow is not listed as a required check and never blocks a merge.
- Each run runs on the commit selected in the Actions UI; the run records the exact SHA.

**Acceptance:**
- `ci.yml` and `desktop.yml` are unchanged.
- A test (`tests/test_real_models_ci.py`) asserts that `real-models.yml` has no `push`, `pull_request` or `schedule` trigger, and that `ci.yml` does not reference it.

### W2: Runner and resources

- Runner: `ubuntu-latest` (4 vCPU and 16 GB RAM on public repos at the time of writing; confirm against GitHub's documentation and record the actual `nproc`/`free -h` output in the run log).
- Job `timeout-minutes`: 180 for the clone jobs, 120 for ASR, 60 for Kitten.
- Each suite is its own job, so one failure does not hide the others, and the long-form clone job runs last.

**Acceptance:**
- A run log prints the runner's CPU count, memory and disk before any model loads.

### W3: Dependencies pinned to the lockfile

- Install with `uv sync --locked --extra kitten --extra dev --extra asr-wav2vec2 --extra asr-vosk`, adding `--extra asr-whisper` only for the Whisper job.
- Use the repository's pinned uv version (as in `ci.yml`), and keep `tests/test_ci_uv_pin.py` as the cross-check.
- PyTorch: the runner has no GPU, so the job installs the CPU build of `torch` from the PyTorch CPU index, at the exact version that `uv.lock` resolves (the lock itself is not changed). The override is applied after `uv sync --locked`, so `--locked` still checks the lock. The job fails if the installed `torch` reports a CUDA version. This is the same CPU setup used for the 2026-11-19 real-model runs (`torch 2.14.1+cpu`).

**Acceptance:**
- The job log shows that `torch` is a CPU build (`torch.version.cuda` is `None`) at the locked version, and that `uv.lock` was not modified.

### W4: Model weights and caching

- Model downloads go through the project's own commands and pinned revisions: `pdf2audiobook tts fetch kitten2`, `pdf2audiobook asr fetch <models> --yes`, and the Kitten `mini` model for the smoke test.
- Cache the model directories with `actions/cache`, keyed by the pinned revision of each model. Approximate sizes: Kitten 2 about 1.6 GB, Whisper medium.en 1.5 GB, wav2vec2 378 MB, vosk 131 MB. These fit the 10 GB per-repository cache limit.
- A cache miss downloads and verifies every artifact; a hit must still pass the SHA-256 check (the project's readiness code already does this).

**Acceptance:**
- A second run with a warm cache performs no download (the log records cache hits).
- A corrupted cached file is rejected and re-fetched by the project code, not trusted.

### W5: Privacy and artifacts

- The Bruno reference and transcript come from the pinned Kitten 2 model's voices file, not from the repository. They are written to a runner temporary directory and deleted in an `always()` step.
- No audio, transcript, generated MP3, or model weight is uploaded as an artifact. Only a summary (`pytest -ra` output, timing lines and the resource report) is uploaded, and it is checked for reference paths and transcript text before upload.
- Secrets: none. The workflow needs no tokens beyond the default `GITHUB_TOKEN` with read permission.
- `permissions: contents: read` at the top level.

**Acceptance:**
- A test scans the uploaded summary for the reference transcript text and for the runner temporary path; the test fails the job if either appears.

### W6: Timing evidence

- Each long job writes wall time and peak RSS (`/usr/bin/time -v`) to its log.
- A generation request that exceeds the 300-second deadline fails its job, so a passing job shows that every request stayed under the deadline on that runner. Per-request durations would need instrumentation in the product code; that is out of scope for this workflow and is recorded as a limitation if the deadline ever needs to be measured directly.

**Acceptance:**
- The long job's log contains the `/usr/bin/time` lines, and the run summary states whether each clone job passed.

### W7: Documentation and invariant wording

- `CLAUDE.md` invariant "Live LLM smoke … is opt-in and never part of CI; CI must not depend on the network" is extended with: "The manually started `real-models.yml` workflow is the one exception for real-model tests; it is not part of the main CI and never gates a change."
- `docs/MAINTAINER_GUIDE.md` documents how to start the workflow, what each suite proves, the cache keys, and what a green run does **not** prove.

**Acceptance:** Both documents are updated in the same commit as the workflow.

## 3. Identity

No product identity changes. This workflow only runs existing code and tests.

## 4. Known limitations

- A green run does not establish voice quality, speaker similarity, or pacing (listening remains a human step).
- GitHub runners have no GPU. The accelerator gates (VC0.03, VC8.04) stay open and must run on a GPU machine.
- Runner speed and memory vary between jobs. A slow run can still exceed the 300-second request deadline; W6 measures this rather than assuming it.
- Whisper medium needs about 7 GB peak on CPU; the 16 GB runner is expected to be sufficient, which W2 verifies.
- The workflow depends on the pinned model hosts being reachable. A host outage fails the run, which is a network result, not a code result.

## 5. Validation

- Lint and test the workflow file: `actionlint` and the trigger test in W1, run in the main CI, which stays offline.
- Run the workflow once by hand from `master`, because `master` is the only branch. Record the run ID, its timings, and whether each suite passed in the ledger. A second run on a warm cache confirms W4.
- Confirm that the main CI and desktop CI are unaffected: their run IDs stay green on the commit that adds the workflow.
