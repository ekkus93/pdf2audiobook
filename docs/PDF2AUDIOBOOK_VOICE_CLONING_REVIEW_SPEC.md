# PDF2Audiobook Voice Cloning Review Follow-up Specification

**Status:** Follow-up implemented; historical R1 green-CI criterion remains unresolved
**Date:** 2026-11-19
**Companion:** [Voice Cloning Review Follow-up TODO](PDF2AUDIOBOOK_VOICE_CLONING_REVIEW_TODO.md)
**Baseline:** `master` at `451551c`, plus the uncommitted voice-cloning working tree reviewed on 2026-11-19
**Supplements:** [Voice Cloning Specification](PDF2AUDIOBOOK_VOICE_CLONING_SPEC.md) (VC1–VC8), [Voice Cloning TODO](PDF2AUDIOBOOK_VOICE_CLONING_TODO.md)

## 1. Purpose and scope

A review of the voice cloning work against its TODO found four problems to fix, plus one gap in the review itself:

1. **Nothing is committed.** The feature is 62 modified and about 34 new files, with no commit or CI run. That breaks CLAUDE.md's per-task commit rule and leaves no history to bisect or revert.
2. **Warm-resume identity/reporting gap.** The initial review inferred a later refusal from a saved-identity branch, but parent-commit tests did not reproduce it: `_synthesize_selected` already transcribed locally when pending synthesis needed text. Tests instead reproduced changed provenance with an unchanged transcript digest, and a missing regeneration reason when the digest differed.
3. **Containment check runs after `mkdir`.** `tts/catalog.py` `fetch_model` creates the destination directory before it checks that the directory stays inside the model cache. The paths come from the pinned manifest, so the risk is small, but the check belongs first.
4. **Ledger inconsistency.** The checkpoint notes give several different full-suite totals as the run progressed, and the reader cannot tell which one is current.
5. **Review coverage.** The review spot-checked the TODO's tasks rather than verifying each one. This spec covers a complete per-task verification pass.

This spec does not change the feature's behavior beyond the findings. Hardware gates (VC0.03, VC8.04) stay open, as the TODO already records.

All invariants still hold: content-free errors and logs, private reference media outside Git, offline CI, no reference paths or transcript text in output, and no implicit downloads or model loads.

## 2. Requirements

### R1: Commit the feature in reviewable units

**Problem.** The entire feature is one uncommitted working tree.

**Requirement.**
- Commit the work to `master` in task-sized commits, one per TODO section or subsection, in dependency order (VC0 through VC8). Each commit passes lint, format, mypy on 3.11–3.13 and the test subset for the files it touches.
- Each commit uses the Conventional Commits format with a scope (`feat(tts)`, `feat(cli)`, `feat(desktop)`, `test(voice)`, `docs(voice)`), lowercase imperative subject, and no body.
- Generated or private material never enters Git: recordings, transcripts, model weights, conditioning caches, private paths and generated workspaces. Confirm with `git status` and a secrets scan before each commit.
- Check CI after every push. A failed run blocks the next commit until it is fixed or explained.

**Acceptance:**
- `git status` shows only the intentionally untracked `.serena/` and `audiobooks/`, and no voice-cloning paths.
- Every feature commit has a green CI run, recorded in the ledger.

### R2: Warm resume with an unchanged reference

**Problem and reproduction.** The original review referred to `_clone_preparation`,
but the integration context is actually `conversion.py` `_voice_run`. It restores
saved conditioning metadata when an unchanged recording has no supplied transcript:

```python
reference.identity = recorded
```

The initial claim that this later refuses synthesis was **read from code, not
reproduced**. Tests against `a01cfdcdd6a4b7907abe53d06b8ce24ec0abfeee` show that
`_synthesize_selected` already calls `complete_transcript` for pending synthesis.
They reproduce two narrower defects: unchanged normalized transcript SHA-256 still
changed ASR provenance, and changed-text regeneration recorded no reason. Missing
local ASR already refused before worker/model/network activity.

**Resolution.** Retain option (a), the existing lazy local path. Commit
`c1523415034f2563178e2dfe90fe5cb2c9ad4ac8` preserves saved identity for the same
normalized digest and records `voice_reference_changed` when changed text causes
regeneration. The following requirements preserve the original acceptance intent.

**Requirement.**
- Decide the intended behavior first, then implement it. The choice is between:
  - **(a)** when synthesis is needed and the transcript is missing, run the local ASR transcription that a first-time preparation would run, or
  - **(b)** keep the refusal, but make it name the fix: supply `--reference-text-file`, or enable local transcription.
- Whichever is chosen, the recorded identity must not change silently. A reused transcript digest must match the one recorded.
- The refusal stays content-free, and no ASR or download runs unless the user has enabled local transcription.

**Acceptance:**
- A test shows the warm-resume case with an unchanged reference and a changed chapter. Under (a), it transcribes locally and synthesizes. Under (b), it fails with the new message, with no model load.
- A test shows that a missing local ASR backend never downloads a model.
- The recorded identity is unchanged in both cases unless new transcription produced a different digest, in which case the audio is regenerated and the reason is recorded.

### R3: Check containment before creating directories

**Problem.** `tts/catalog.py` `fetch_model` runs:

```python
destination.parent.mkdir(parents=True, exist_ok=True)
if not destination.parent.resolve().is_relative_to(base):
    raise ConfigError(...)
```

The directory is created before the check, so an escaping path is created and then rejected.

**Requirement.**
- Resolve the destination's parent and check containment *before* `mkdir`. For a path that does not exist yet, resolve the deepest existing ancestor and check it, then create the rest only when the check passes.
- Refuse symlinked components that point outside the base.
- The refusal keeps its existing content-free `ConfigError` message.

**Acceptance:**
- A test with a manifest entry whose path escapes the cache root creates nothing outside the root and raises `ConfigError`.
- A test with a symlinked component pointing outside the root creates nothing outside the root.
- The normal fetch and offline reuse tests still pass unchanged.

### R4: One authoritative ledger

**Problem.** The checkpoint notes give several full-suite totals (2,751, 2,765, 2,773 and 2,774 passed) and several timing numbers. The current totals are scattered through the prose.

**Requirement.**
- Add a single "Current validation state" table to the TODO, with one row per gate: lockfile, Ruff lint, Ruff format, mypy 3.11/3.12/3.13, full offline pytest, CLI smoke, wheel and sdist smokes, desktop Vitest, Rust tests, native walkthrough. Each row gives the commit, the date and the counts.
- Mark superseded counts in the prose as superseded by the table. Do not delete the history.
- Each gate's count comes from a run after the last code change.

**Acceptance:** A reader finds the current count for each gate in one table, and every count in the table traces to a run on a named commit.

### R5: Complete per-task verification

**Problem.** The review spot-checked the TODO's tasks. Each checked task needs evidence that it was implemented as written.

**Requirement.**
- For each task marked `[x]`, record in a verification table:
  - the file and line(s) that implement it;
  - the test(s) that exercise it;
  - the verdict: **verified**, **partially verified** (with what is missing), or **not verified**.
- Unchecked tasks are recorded as open, with the reason.
- A task that is **not verified** or **partially verified** is either verified by a new test, or unticked with a note.
- The verification must cover the specification's privacy and identity requirements, not only the presence of code.

**Acceptance:** Every `[x]` task has a verdict, with evidence that a reader can check.

### R6: Keep the review honest

**Problem.** The review's bug list and verdicts rely on reading code and on earlier ledger claims.

**Requirement.**
- Every finding in this spec is either reproduced by a failing test before the fix (R2, R3) or recorded as "read from code, not reproduced" with the reason.
- Ledger claims that are carried forward (for example the timing benchmarks and the real-model runs) are labelled as recorded evidence, not re-measured.

**Acceptance:** Each finding in the TODO's ledger states how it was established.

## 3. Identity

- R2 may change the cache identity of warm-resume audio only when new transcription produces a different digest. In all other cases identity is unchanged.
- R3 and R4 change no identity.
- R1 changes no code.

## 4. Known limitations (documented, not solved here)

- R1's strict historical green-CI criterion remains open for
  `ed160e6b7ce509ab3c914281207add10bee7739b`: Python #913 (44636305313) failed
  because the updated optional-SDK assertion was staged later. Corrective
  `0cd79d6084da8491047135eb4b7408968ee731cf` is green; history was not rewritten.
- R5 reproduced an additional completed-conversion reuse gap against `a01cfdc`:
  removing optional backend metadata while the recording and transcript remain
  present attempts synthesis again. VC5.05 is reopened and its strict expected
  failure is not passed acceptance. Fixing this separate boundary is outside R2/R3.

- Accelerator acceptance (VC0.03, VC8.04) remains open until a supported device is available.
- Timing measurements on the 7.1-GiB host reflect paging and are not a performance promise.
- The real-model runs are recorded evidence from 2026-11-19 and are not repeated by this follow-up.

## 5. Validation

- Each fix has a regression test, run against its parent commit before the fix, with the failing test IDs recorded in the ledger.
- Run `/verify` and the Python 3.12 and 3.13 mypy checks for each commit.
- Run the desktop checks (lint, type checks, Vitest, production build, Rust fmt, clippy and tests) for any commit touching `desktop/`.
- Check CI after each push.

## 6. Verification record

R1's uncommitted state was reproduced by Git inspection; its per-SHA CI results,
including failed attempts, are retained in the [follow-up ledger](PDF2AUDIOBOOK_VOICE_CLONING_REVIEW_TODO.md).
R2's original refusal was not reproduced for the reason above; the narrower failures
were tested before the fix. R3's traversal and outside-symlink directory creation
was reproduced against immediate parent `c152341`, then fixed in `8888b4e`.
R4's counter inconsistency was observed in the historical prose and resolved with
the [current validation table](PDF2AUDIOBOOK_VOICE_CLONING_TODO.md#current-validation-state).
R5 covers all 40 tasks in the [source-linked audit](PDF2AUDIOBOOK_VOICE_CLONING_REVIEW_AUDIT.md):
37 verified, one partially verified/open, two open hardware gates. The final CPU real-model,
timing/memory/cancellation and user listening results carried forward here are recorded
evidence from 2026-11-19, not re-measured by this follow-up. New software counters name final code
`99416560b9081dd61f8fecd1c52d870fdc0a4c0f`; fake providers do not establish speaker similarity.
