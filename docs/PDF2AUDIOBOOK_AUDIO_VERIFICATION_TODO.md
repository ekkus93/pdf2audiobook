# Audio Verification TODO

**Status:** Not started. Scope and acceptance criteria: `docs/PDF2AUDIOBOOK_AUDIO_VERIFICATION_SPEC.md`.

## AV0 — Baseline and decisions

- [x] AV0.01 Record the current `convert --chapter N --force` behavior: output replacement, sidecar invalidation, backup behavior, interruption behavior, and JSON/progress contracts.
  - Evidence: Recorded in spec §11 from `conversion.py`, `audio/encoding.py` and
    `audio/freshness.py`, and checked with real Kitten runs on a copy of the converted Harbour
    demo book. A forced `--chapter 2` run replaced the MP3 (sha256 `63dbcbab2959` to
    `a6fbf266bd91`) and sidecar in place, with no backup and no temporary files left. A forced
    `--chapter 10` run sent SIGTERM at 291 of 1,427 characters exited 130 with the `Interrupted`
    JSON error, left the MP3 and sidecar byte-identical (`396b68a424fc`, `fe3d8651508a`),
    `run_status.json` `stopped`, and no temporary WAV. Gaps for AV4 listed in §11.
- [ ] AV0.02 Decide report retention, default warning behavior, supported model revisions, language scope, and model-download UX; record decisions in the spec.
- [ ] AV0.03 Benchmark the three ASR families on generated chapter audio and define normalization, alignment, mismatch thresholds, resource limits, and cancellation expectations.

## AV1 — Shared contracts and comparison core

- [ ] AV1.01 Define typed ASR backend, model readiness, transcript segment, alignment, vote, and chapter-result contracts.
- [ ] AV1.02 Implement safe narration-reference selection that matches the exact text and pronunciation transforms sent to TTS.
- [ ] AV1.03 Implement normalization, word/phrase alignment, timestamps, and 2-of-3 family voting; missing/failed models abstain.
- [ ] AV1.04 Add deterministic tests for matching speech, a two-model insertion, one-model hallucination, omission, substitution, disagreement, short clips, number normalization, and timestamp bounds.
- [ ] AV1.05 Define and test versioned JSON schemas for model readiness and verification results.

## AV2 — Optional CLI model support

- [ ] AV2.01 Add isolated optional dependency groups for Whisper `medium.en`, Wav2Vec2, and Vosk/Kaldi; keep default installs unchanged.
- [ ] AV2.02 Add CLI model-list/readiness and explicit model-fetch commands with pinned revisions, integrity checks, cache-location output, and no implicit downloads.
- [ ] AV2.03 Implement local inference adapters behind the common backend interface; add model identity/version reporting, resource bounds, and graceful unavailable results.
- [ ] AV2.04 Add offline/fake-backend tests plus opt-in integration smoke tests for each installed backend.
- [ ] AV2.05 Document model licenses, disk/RAM/CPU costs, supported OS/Python combinations, and explicit network behavior for downloads.

## AV3 — CLI verification and reports

- [ ] AV3.01 Add `verify-audio MANIFEST` with chapter/range/model selection, progress, cancellation, human summary, and stable `--json` output.
- [ ] AV3.02 Verify audio hashes, chapter artifact state, source text hashes, safe workspace paths, and stale/missing audio before inference.
- [ ] AV3.03 Write the versioned report atomically; follow the spec's transcript-retention decision and exclude content from logs/errors.
- [ ] AV3.04 Add opt-in `convert --verify-audio`; ensure ordinary and dry-run conversions do not load ASR packages or fetch models.
- [ ] AV3.05 Add CLI contract, privacy marker, path traversal, symlink, cancellation, malformed report, and stale-report tests.
- [ ] AV3.06 Document CLI setup, verify-existing and verify-after-convert examples, JSON fields, interpretation, and limitations.

## AV4 — Safe chapter repair

- [ ] AV4.01 Audit and, if necessary, harden selected-chapter forced conversion so synthesis writes temporary MP3/sidecar files and atomically replaces valid output only after validation.
- [ ] AV4.02 Preserve recoverable backups of prior audio and metadata; test failed synthesis, cancellation, disk-full, and interrupted commit behavior.
- [ ] AV4.03 Add a CLI action for targeted retry and document editing chapter narration/pronunciation before re-synthesis; keep text repair separate from `regenerate-chapter` artifact recovery.
- [ ] AV4.04 Re-run verification after repair and invalidate reports when chapter text, pronunciation inputs, model settings, or audio hashes change.

## AV5 — Tauri desktop workflow

- [ ] AV5.01 Add typed bridge requests and shared schemas for readiness, verification progress/results, cancel, and selected-chapter repair.
- [ ] AV5.02 Add per-conversion opt-in and “Verify existing audio”; show model availability and route explicit setup/download through the CLI.
- [ ] AV5.03 Show chapter result, model votes, expected/transcribed excerpt, timestamp playback, stale state, and clear limits of ASR evidence.
- [ ] AV5.04 Add user-controlled listen/dismiss, retry with selected voice/speed, and edit-corrected-narration then regenerate actions; preserve the previous MP3 until replacement succeeds.
- [ ] AV5.05 Add frontend/Rust tests for opt-in defaults, unavailable models, partial votes, cancellation, stale results, privacy, playback seeking, and repair rollback.
- [ ] AV5.06 Update desktop and main README documentation and add a deterministic end-to-end fixture covering a flagged passage and repair.

## AV6 — Acceptance

- [ ] AV6.01 Run the full Python and desktop checks; verify default conversion stays offline from ASR and unchanged.
- [ ] AV6.02 Run the three-model local acceptance set: clean speech, a known insertion, a one-model false positive, and a repair; record versions, timings, and resource use.
- [ ] AV6.03 Review report privacy, model licenses, package/installer size impact, and supported-machine behavior before marking complete.
