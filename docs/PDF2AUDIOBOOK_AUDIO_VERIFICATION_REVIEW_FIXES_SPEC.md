# Audio Verification Review Fixes Specification

**Status:** Proposed. This specification addresses four defects found while reviewing the completed audio verification feature. It supplements, and does not replace, `PDF2AUDIOBOOK_AUDIO_VERIFICATION_SPEC.md`.

## 1. Goals

Make verification evidence correspond to the audio actually synthesized, prevent transcript retention beyond the user's explicit choice, ensure a 2-of-3 vote represents genuinely co-located differences, and bound decoder memory for long chapters. Preserve the existing opt-in behavior, report schema compatibility where possible, local-only processing, and the ability of unavailable models to abstain.

## 2. Exact narration reference

`Reference.exact` must gate comparison. If current narration chunks do not match the synthesis ledger, verification must not compare ASR output against the changed text as though it were spoken. Return an explicit stale/unavailable result with a stable reason code, or safely recover the exact historical synthesis reference if the ledger supports it. Do not silently substitute OCR or current edited text. Keep CLI and desktop status displays clear about why no comparison was made.

## 3. Transcript retention on partial runs

Transcript retention is controlled by the current invocation's explicit `--keep-transcripts` choice. When a report is rewritten after a partial run without that option, retained chapters must not continue exposing full transcripts from an earlier run. Remove transcript fields from all chapters in the newly written report, while retaining permitted flagged excerpts and non-sensitive vote metadata. Ensure the top-level retention field accurately describes the complete report. Apply the rule consistently to CLI JSON output and desktop report reads; write updates atomically.

## 4. Spatially valid model consensus

Difference clustering must not use transitive proximity to join a chain of separate differences into one multi-model vote. Define a deterministic cluster rule with a stable anchor or bounded total span, and require two distinct model families to agree within the documented positional tolerance. A third model's nearby but bridging difference must not manufacture consensus. Preserve one-model disagreement behavior and deterministic ordering.

## 5. Bounded-memory audio processing

Replace whole-file WAV reads with streaming decode/window processing. Keep peak audio-buffer memory bounded by a documented window size plus a small overlap, independent of chapter duration. Preserve sample-rate conversion, timestamps, model window boundaries, cancellation checks, and cleanup of temporary decoded audio. If FFmpeg cannot decode or the input format is unsupported, report an actionable model failure without damaging source audio.

## 6. Testing and acceptance

Add deterministic regression tests for each defect:

1. Changed pronunciation/settings or a stale synthesis ledger prevents comparison against the current reference; an exact ledger still verifies normally.
2. A full transcript-retaining report followed by a partial run without retention contains no old full transcripts, including in serialized JSON; explicit retention still works.
3. Three differences at positions 0, 2, and 4 with a two-word pair tolerance do not become a confirmed 2-of-3 flag solely through bridging; genuinely co-located two-model differences still confirm.
4. A long synthetic WAV is processed in bounded chunks; instrumentation demonstrates buffer size does not scale with total duration, and cancellation releases temporary resources.

Run targeted verification tests and the full Python suite. Confirm CLI report schemas, Tauri report rendering, default conversion behavior, and privacy guarantees remain intact. Do not require downloaded ASR models for deterministic regression tests; keep real-model acceptance opt-in.

## 7. Implementation boundaries

Keep changes within verification reference selection, comparison, backend audio decoding, report merge/serialization, and their CLI/desktop consumers. Update the main audio verification spec where behavior or status codes change. Avoid unrelated report format or conversion changes. Document any report migration behavior and memory bound in user-facing audio verification docs.
