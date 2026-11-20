# PDF2Audiobook Voice Cloning VC5.05 Resume Fix TODO

**Status:** Complete; fixed in `282f6f0`, CI green
**Date:** 2026-11-20
**Baseline:** `master` at `77d522b`
**Specification:** [VC5.05 Resume Fix Specification](PDF2AUDIOBOOK_VOICE_CLONING_VC505_SPEC.md) (V1–V4)
**Task reopened:** [Voice Cloning TODO](PDF2AUDIOBOOK_VOICE_CLONING_TODO.md), VC5.05

## Working rules

- Work in the order below. Task 1 must run against the parent commit, so its failing test is recorded before the fix.
- Use `[x]` only when the implementation exists and its named tests pass. Tick VC5.05 in the voice cloning TODO only after every item here is ticked and the audit is updated.
- One fix per commit. Conventional Commits with a scope, lowercase imperative subject, no body.
- Check CI after every push. A failed run blocks the next task until it is fixed or explained.
- Errors, logs and `--json` stay content-free. Fixtures are synthetic and CI stays offline. Never commit reference audio, transcripts, weights or private paths.

## 1. Regression test (V1, V3)

- [x] 1.1 Remove the `xfail` marker from `tests/test_voice_cloning_known_limitations.py::test_finished_audio_reuses_without_sdk_while_reference_exists`. Run it against `77d522b`; record the failing ID and the observed synthesis count (8 versus 4).
  Evidence: Parent `77d522b`: `--runxfail` fails with 8 synthesis calls against 4; xfail removed.
- [x] 1.2 Add a test where the package is removed and every chapter is already finished: no provider is constructed, and no new synthesis call occurs.
  Evidence: Parent `77d522b`: the same test fails (8 against 4). Fixed test asserts zero provider construction.
- [x] 1.3 Add a test where the package is removed and one chapter needs new synthesis (speed change): conversion refuses with the existing content-free message, and the provider construction counter stays at zero.
  Evidence: Guard test: passes on the parent too (refusal already worked); keeps V3 from regressing.

## 2. Reuse the recorded identity when the reference is unchanged (V1)

- [x] 2.1 In `conversion.py` `_voice_run`, when a recorded identity exists and the reference audio digest matches `reference_audio_sha256`, use the recorded identity. When a transcript is supplied, reuse it only if its digest matches `reference_text_sha256`; otherwise keep the fresh identity.
  Evidence: `conversion.py` `_recorded_reference_matches`; used by `_voice_run`.
- [x] 2.2 Confirm `valid_recorded_identity` still rejects a recorded identity whose backend version differs from an *installed* package.
  Evidence: New `valid_recorded_identity` test: rejects a different installed backend, accepts an absent one.
- [x] 2.3 Run tasks 1.1–1.3 and the existing `tests/test_voice_cloning_conversion.py` resume and repair tests. Confirm all pass unchanged.
  Evidence: 114 voice-cloning tests pass after the fix (resume, repair and config included).

## 3. Regeneration still happens when identity changes (V2)

- [x] 3.1 Test: the reference audio bytes change at the same path. The affected chapters regenerate and the analysis manifest bytes stay identical.
  Evidence: Guard test: same-size audio replacement regenerates; manifest bytes unchanged. Passes on parent too.
- [x] 3.2 Test: the transcript changes. The affected chapters regenerate.
  Evidence: Guard test: changed transcript regenerates.
- [x] 3.3 Test: an installed backend version differs from the recorded `backend_versions`. The affected chapters regenerate.
  Evidence: Guard test: a different installed backend version regenerates.
- [x] 3.4 Test: a generation setting or model revision changes. The affected chapters regenerate, and the others are untouched.
  Evidence: Guard test: a speed change regenerates. Model-revision regeneration is covered by existing VC5.02 tests; not repeated here.

## 4. Privacy and contract checks (V4)

- [x] 4.1 Add a marker test: the resume path emits no reference path, transcript text or digest beyond those already emitted, in both human and `--json` output.
  Evidence: Marker test over human and `--json` output: no reference path, transcript text or private marker.
- [x] 4.2 Run the existing marker-based privacy tests unchanged.
  Evidence: Existing privacy and marker tests pass unchanged in the full run.

## 5. Identity and documentation

- [x] 5.1 Confirm that existing finished audio keeps its fingerprint (no regeneration after the fix for a workspace whose recorded identity still matches). Add a test using a sidecar written before the fix.
  Evidence: Sidecar bytes and MP3 mtimes unchanged on resume.
- [x] 5.2 Update `docs/PDF2AUDIOBOOK_VOICE_CLONING_REVIEW_AUDIT.md` (VC5.05) and the known-limitations note in `docs/PDF2AUDIOBOOK_VOICE_CLONING_TODO.md` to reflect the fix.
  Evidence: Audit VC5.05 row and P2 note updated to resolved; review TODO bullet updated.
- [x] 5.3 Update `docs/guides/voice-cloning.md` if it describes the cache behaviour when the optional package is removed.
  Evidence: `docs/guides/voice-cloning.md` states that resume needs no SDK while the reference exists.

## 6. Finish

- [x] 6.1 Run `/verify`, plus mypy on Python 3.12 and 3.13, and the full offline pytest run. Record counts; the strict expected failure should now pass as a normal test.
  Evidence: Full offline suite 2,816 passed, 6 skipped before the validator test was added; voice files 114 passed after; lock, Ruff, format and mypy 3.11–3.13 pass.
- [x] 6.2 Confirm the desktop checks are unaffected, or run them if `desktop/` was touched.
  Evidence: Fix touches no `desktop/` file; desktop checks not required.
- [x] 6.3 Record the exact-head CI run in the ledger and tick VC5.05 in the voice cloning TODO.
  Evidence: Python CI 934 and Desktop CI 89 are green on `282f6f0`; VC5.05 ticked in the voice cloning TODO.

## Ledger

| Date | Commit | Completed tasks | Validation | Outstanding gates |
|---|---|---|---|---|
| 2026-11-20 | `77d522b` | Reproduced the gap: `test_finished_audio_reuses_without_sdk_while_reference_exists` with `--runxfail` fails with 8 synthesis calls instead of 4. Mechanism traced to `tts/cloning.py` `snapshot_reference` (fresh `backend_versions`) and `conversion.py` `_voice_run`. | Draft only; no code changed. | Tasks 1–6 |
| 2026-11-20 | `282f6f004bdf2d60a47e480ca806f13e5526b859` | Tasks 1–6 complete; fix in `conversion.py`, regression and guard tests, guide and audit updated | Full offline suite 2,816 passed/6 skipped; voice files 114 passed after the fix; lock, Ruff, format and mypy 3.11–3.13 pass. Python CI [934](https://github.com/ekkus93/pdf2audiobook/actions/runs/44721019288) and Desktop CI [89](https://github.com/ekkus93/pdf2audiobook/actions/runs/44721019453) green. | VC0.03 and VC8.04 accelerator gates only |
