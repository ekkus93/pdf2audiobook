# Audio Verification Specification

**Status:** Proposed. This document defines an optional, local post-synthesis speech check for the Python CLI and Tauri desktop app. It does not change default conversion behavior.

## 1. Goal and limits

After TTS creates chapter audio, compare the spoken content with the chapter's intended narration using three independent ASR families:

1. OpenAI Whisper `medium.en`.
2. Meta Wav2Vec2 (`facebook/wav2vec2-base-960h`, or a pinned compatible replacement).
3. Vosk/Kaldi (`vosk-model-en-us-0.22-lgraph`, or a pinned compatible replacement).

The check detects possible text insertions, omissions, and substitutions. It does not establish that audio sounds natural, pronounce names correctly, or is free of clipping, distortion, or other acoustic defects. ASR consensus is evidence for review, never ground truth.

## 2. User experience

- Verification is off by default, has no effect on ordinary conversion, and is opt-in in both the CLI and desktop app.
- The CLI can verify existing workspaces explicitly and can optionally verify chapters after conversion. The desktop offers a per-conversion checkbox and a way to verify existing audio.
- Show chapter-level outcomes: `no_mismatch_detected`, `possible_mismatch`, `model_disagreement`, or `verification_unavailable`. Do not label audio simply “correct” or “verified.”
- For a possible mismatch, show the expected narration, the aligned transcript excerpts, model votes, and timestamps where available. Let the user play the chapter and jump to a flagged passage.
- Distinguish missing audio, stale audio, model failure, and transcript disagreement. A failed or unavailable model must not be counted as a vote.

## 3. CLI contract

Add an explicit command shaped like:

```text
pdf2audiobook verify-audio MANIFEST [--chapter N ...] [--chapter-range START:END] [--models all|MODEL ...] [--json]
```

Add `convert --verify-audio` as an opt-in convenience. It verifies only chapters synthesized or selected by that conversion. `verify-audio` can inspect existing chapter MP3s without rerunning TTS. Define stable JSON schemas for a run and each chapter result; include model IDs/revisions, status, aligned spans/timestamps, and machine-readable reason codes. Human output summarizes flags without printing full book text by default.

The CLI must support a model subset for machines with limited resources. A result based on fewer than three available model families is explicitly partial and cannot be reported as a three-way majority. Preserve existing conversion defaults, exit codes, output, and workspace files when verification is not requested.

## 4. Model setup and execution

- Keep ASR dependencies outside the default install. Provide separate optional extras or an equivalent install path so users can install only the backends they need.
- Provide CLI commands or clear documented steps to list backend readiness and fetch model weights. Pin model identities and revisions. Fetch weights only after an explicit user action; never download them silently during conversion or app startup.
- Run inference locally. Never send audio, narration text, transcripts, or file paths to a hosted service. The desktop app itself remains network-free; any user-requested model download is performed by the CLI and described before it begins.
- Resample/decode audio through the existing FFmpeg dependency as required by each backend. Bound memory, threads, and cancellation latency; process one chapter/model at a time by default.
- Keep the abstraction behind a small ASR backend interface. A missing model or incompatible backend reports unavailable and does not break conversion or playback.

## 5. Comparison and report

- Compare each transcript with the exact narration input used for synthesis, not OCR output re-read independently. Include accepted chapter edits and pronunciation transformations in that reference.
- Normalize only safe presentation differences (case, punctuation, whitespace, common number formatting); retain original text and model transcripts for the UI comparison.
- Align words or short phrases with timestamps. Use a documented threshold for edit distance and minimum phrase length to suppress harmless punctuation and short-clip artifacts.
- Use independent-family voting on aligned insertions, omissions, or substitutions. Two agreeing models may flag a suspected issue; one-model-only differences are `model_disagreement`. A failed model abstains.
- Save a versioned report in the workspace under `reports/audio_verification.json`. It may contain book text and transcripts: keep it local, do not include transcript text in application logs, errors, telemetry, or generic CLI progress output. Document how to remove it. Write atomically and tolerate an absent, stale, or malformed report.
- Record model IDs/revisions, backend versions, source audio hash, reference text hash, timestamps, normalized diff, and completion time so stale verification is detectable after audio or narration changes.

## 6. Repair workflow

Verification never rewrites narration text or audio automatically. For flagged chapters, the CLI and desktop provide these user-controlled actions:

1. **Listen and dismiss:** jump to the timestamp, play context, and mark the result reviewed without changing files.
2. **Retry synthesis:** regenerate only the selected chapter from the same narration, with the same or user-selected supported voice/speed. Use the existing selected-chapter/force conversion path where possible.
3. **Correct narration:** open the chapter text for editing, preserve a backup and approval history, then regenerate only that chapter. Keep source text, narration text, and ASR transcript distinct.
4. **Pronunciation correction:** use the existing pronunciation configuration where applicable, then regenerate only affected chapter audio.

Generate replacement audio and metadata in temporary files. Replace the current MP3 only after successful synthesis and validation; preserve the previous MP3 and sidecar as a recoverable backup. On failure, leave the current audio playable and report a content-free error. Re-run verification after a repair and mark old results stale when the audio or narration hash changes.

`regenerate-chapter` currently repairs generated chapter-text artifacts; do not treat it as the TTS repair command. Reuse `convert --chapter N --force` for synthesis if it satisfies the backup and atomicity requirements; otherwise add a dedicated safe repair operation.

## 7. Desktop integration

- Add an opt-in verification control to conversion options and a “Verify existing audio” action.
- Show progress separately from synthesis and allow cancellation without canceling or damaging completed audio.
- Display per-chapter status, timestamped transcript comparison, and actions from §6. Do not place transcript content in the app log or native error dialogs.
- Make the `tauri` bridge request/response typed and validate JSON with shared contracts. Keep one write-capable operation per workspace; verification is read-only until a user selects repair.
- The app uses the CLI for model setup and inference; it does not add an HTTP client or direct model-download code.

## 8. Security, privacy, and compatibility

- No audio or text leaves the machine. Model downloads are explicit, documented, and limited to configured model sources.
- Keep transcripts and paths out of logs and generic errors. Test with marker text in a title, source path, and narration.
- Reject symlink/path escapes when reading workspace audio or reports; use workspace locking and atomic writes.
- Missing optional dependencies, weights, FFmpeg, or unsupported audio must produce actionable local guidance and leave existing audio untouched.
- Support English models first. Future language support must select a compatible model set and must not silently apply English voting to another language.

## 9. Acceptance criteria

1. Default CLI conversion and desktop conversion remain unchanged, with no ASR import, model download, or inference unless opted in.
2. CLI can verify existing audio and optionally verify newly generated audio; JSON output follows a tested schema.
3. The three configured model families run locally and produce reproducible per-chapter reports; unavailable models abstain.
4. A fixture with a known spoken insertion is flagged by the chosen majority rule; a fixture where only one backend hallucinates that insertion is reported as disagreement, not as a confirmed defect.
5. Mismatch results link to timestamps and expected text, and are not presented as proof of bad audio.
6. A user can listen, dismiss, retry synthesis, or correct narration and regenerate one chapter without losing the prior valid MP3.
7. Failed/canceled ASR or repair cannot corrupt or delete existing chapter audio; stale reports are detected.
8. Tests cover CLI contracts, comparisons, model failure/abstention, cancellation, privacy, path safety, report atomicity, repair rollback, and Tauri integration.
9. Documentation describes install/model-download costs, supported models, resource use, privacy, output reports, limitations, and repair commands.

## 10. Open decisions

- Whether conversion should stop for a decision on a majority mismatch or finish and report it; recommended default is finish and warn.
- Whether verified/no-mismatch reports are retained by default or only mismatch summaries are retained; transcripts are sensitive, so prefer storing only flagged excerpts unless the user opts to retain full transcripts.
- Exact comparison thresholds and resampling settings must be selected using a small set of clean, accented, short, noisy, and intentionally corrupted samples before release.
- Whether CLI-only verification ships before desktop integration; recommended implementation order is CLI backend and report first, then desktop UI.
