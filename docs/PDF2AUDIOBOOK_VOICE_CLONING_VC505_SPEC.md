# PDF2Audiobook Voice Cloning VC5.05 Resume Fix Specification

**Status:** Proposed (draft)
**Date:** 2026-11-20
**Companion:** [VC5.05 Resume Fix TODO](PDF2AUDIOBOOK_VOICE_CLONING_VC505_TODO.md)
**Baseline:** `master` at `77d522b`
**Supplements:** [Voice Cloning Specification](PDF2AUDIOBOOK_VOICE_CLONING_SPEC.md) (§6 cache identity, §9 acceptance), [Voice Cloning Review Audit](PDF2AUDIOBOOK_VOICE_CLONING_REVIEW_AUDIT.md) (VC5.05)

## 1. Purpose and scope

VC5.05 is reopened. The gap is reproduced by the strict expected-failure test `tests/test_voice_cloning_known_limitations.py::test_finished_audio_reuses_without_sdk_while_reference_exists`. With the reference audio and transcript still present, removing the optional backend package makes a conversion that should reuse finished audio attempt synthesis again. The probe at `a01cfdc` observed **8** synthesis calls where the original run made **4**.

### Mechanism (read from code, reproduced by the test)

- `tts/cloning.py` `snapshot_reference` builds a *fresh* reference identity from the current audio and transcript digests, plus `backend_versions` taken from the currently installed packages (`package_versions()`).
- `conversion.py` `_voice_run` replaces the recorded identity with the fresh one whenever the reference is present and a transcript is supplied, or whenever the transcript must be recomputed. It reuses the recorded identity only in the narrow branch where `reference.transcript is None` and the audio digest matches.
- The fresh identity feeds `clone_metadata`, which `pipeline.chapter_audio_fingerprint` uses. A different `backend_versions` value therefore yields a different chapter fingerprint, so the finished MP3 is stale even though nothing in the audio or its text changed.
- `valid_recorded_identity` already accepts a recorded identity when the current package is *missing* (`current.get(key) is not None` guards the comparison). Only a *different installed* version rejects it. The stale-audio check is therefore inconsistent with the validator.

### Intended behaviour

A finished clone chapter is valid for as long as its recorded identity is valid. The identity is invalidated by a change to the reference audio, the transcript, the generation settings, the model revision, or an *installed* backend version that differs from the recorded one. It is **not** invalidated merely because an optional backend has been removed, since reusing finished audio needs no backend. If synthesis is needed in that state, the existing refusal applies.

## 2. Requirements

### V1: Reuse the recorded identity when the reference is unchanged

- When a recorded clone identity exists and the current reference audio digest matches its `reference_audio_sha256`, the reference identity used for fingerprints and sidecars is the recorded identity.
- The same applies when a transcript is supplied: its digest must match the recorded `reference_text_sha256`. A mismatch keeps the fresh identity, so the audio is regenerated.
- Recorded identities are still validated by `valid_recorded_identity`, so a *different installed* backend version still rejects reuse and regenerates.

**Acceptance:**
- The strict expected-failure test passes with its `xfail` marker removed: after the package is removed, the synthesis call count stays at the original 4 (today it is 8).

### V2: Regeneration still happens when identity truly changes

Each of these must still regenerate affected audio only, with the other chapters untouched:
- the reference audio bytes change (same path, new content);
- the transcript changes;
- an installed backend version differs from the recorded `backend_versions`;
- the model revision or a generation setting changes.

**Acceptance:** One regression test per trigger shows the affected chapters are re-synthesized and the analysis manifest bytes do not change.

### V3: Missing optional backend and synthesis still refuse clearly

- With the package removed and every chapter already finished, conversion completes without a model load.
- With the package removed and a chapter that needs new synthesis (for example after a speed change), conversion refuses with the existing content-free "Provide the original voice reference" or missing-package message, and no model is loaded.

**Acceptance:** Two tests, one per case, with a construction counter showing no provider was built in the refusal case.

### V4: Privacy and content-free output

- No new error, log or `--json` field carries reference paths, transcript text or digests beyond those already emitted.

**Acceptance:** The existing marker-based privacy tests pass unchanged, and one new test asserts that the resume path emits no reference marker.

## 3. Identity

- V1 changes **no** persisted identity: it reuses identities already recorded. Sidecars written before this fix stay valid.
- V1 does not change the fingerprint of any chapter whose recorded identity still matches. Existing finished audio is not regenerated.
- The legacy (non-clone) identity is unchanged, since the reference path is not entered.

## 4. Known limitations (documented, not solved here)

- Removing the optional backend and then changing the reference audio regenerates audio and then refuses, which is the intended order.
- Recorded versions are compared only for packages that are installed. A package that is removed and later reinstalled at a different version is caught when it is reinstalled, not when it is removed.

## 5. Validation

- Each requirement has a regression test. V1 is run against its parent `77d522b` first, with the failing test ID recorded.
- Run `/verify` and mypy on Python 3.12 and 3.13.
- Run the desktop checks only if the commit touches `desktop/`. This fix should not touch it.
- Check CI after each push.
