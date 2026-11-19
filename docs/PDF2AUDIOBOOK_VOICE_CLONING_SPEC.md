# PDF2Audiobook Voice Cloning Specification

**Status:** CLI and Tauri implementation present; real-model release acceptance remains open.
**Date:** 2026-11-18
**Companion:** [Voice Cloning TODO](PDF2AUDIOBOOK_VOICE_CLONING_TODO.md)
**Baseline:** `master` at `451551c`, plus the working-tree configuration initializer and Settings editor.
**Scope:** Local KittenTTS 2 voice cloning in both the Python CLI and Tauri desktop app.

## 1. Purpose and upstream support

Let a user choose a short recording and narrate a book, selected chapters, or a repair in that
speaker's voice. Preserve chapter review, approved narration, pronunciation handling, progress,
resume, MP3 tagging, audio verification, and M4B packaging.

The current `mini`, `micro`, and `nano` aliases select KittenTTS 0.8 models. The full
`KittenML/kitten-tts-2` model supports reference-conditioned synthesis. Its Python API accepts
`reference` and optional `reference_text`, and rejects simultaneous `voice` and `reference`.
These are distinct from the smaller Kitten TTS 2 Mini/Nano/Pico models, which do not support
cloning. See the [upstream Python API](https://github.com/KittenML/KittenTTS/blob/main/docs/api.md)
and [model support matrix](https://docs.kittenml.com/models).

This extension uses those capabilities locally; hosted speech APIs, saved hosted voice IDs,
fine-tuning, microphone recording, multilingual cloning, and multiple cloned speakers within
one chapter are outside the first release. English reference speech and narration ship first.
Cloning quality and speaker similarity require listening; ASR agreement cannot establish either.

## 2. VC1 — Compatibility, dependencies, and model setup

- Keep `tts.provider = "kitten"`, its default `mini` model, the eight existing voices, and Piper
  unchanged. Add the explicit model alias `kitten2` for the full cloning-capable model. Never
  switch to it automatically when a recording is supplied to a lightweight model.
- Keep ML dependencies optional. Verify whether the locked `kittenml` version supports the
  necessary API before changing constraints; reuse the `kitten` extra when possible. Record
  any SDK/decoder dependency changes and regenerate `uv.lock` deliberately. Upstream's
  [package metadata](https://github.com/KittenML/KittenTTS/blob/main/pyproject.toml) is evidence
  to inspect, not a substitute for testing the pinned installation.
- Pin model revision, decoder artifacts, conditioning format, and backend options for the
  supported implementation. Do not identify installed weights only by a mutable model name.
  Record applicable code/model licenses and tested hardware in the acceptance ledger.
- Add `tts models [--json]` and `tts fetch kitten2 [--yes] [--json]`. Listing reports package,
  weights, backend/device, and optional reference-transcription readiness without loading or
  downloading models. Fetch shows sources, sizes, destination, and required artifacts before
  downloading; `--yes` supports callers that have already presented that information.
- App startup, configuration initialization/editing, `doctor`, `voices`, and dry-run must not
  import/load KittenTTS 2, perform inference, or download weights. Synthesis with missing
  dependencies or weights gives setup guidance; it never falls back to another speaker/model.
- Publish measured CPU/GPU memory, storage, synthesis speed, and cancellation behavior before
  release. Do not promise realtime CPU performance based on upstream marketing alone.

## 3. VC2 — Configuration and voice selection

Add an optional section, disabled by default:

```toml
[tts.kitten]
model = "kitten2"
speed = 1.0

[tts.voice_clone]
enabled = true
reference_audio = "/recordings/narrator.wav"
reference_text_file = "/recordings/narrator.txt" # optional; see VC3
```

The built-in values are `enabled = false` and both paths unset. Ordinary `config init` must
not enable cloning, select the large model, create a reference recording, or bake private
paths into generated defaults. `config validate` checks types and combinations without loading
models; reference media are checked when planning synthesis.

Expose `PDF2AUDIOBOOK_CLONE_VOICE`, `PDF2AUDIOBOOK_REFERENCE_AUDIO`, and
`PDF2AUDIOBOOK_REFERENCE_TEXT_FILE`. Add matching optional fields to `tts.profiles` alongside
its existing `kitten_model`, so an exact filename-stem profile can select a clone.

Preserve the existing precedence: explicit command options, then the matching book profile,
then environment overrides, then global TOML, then built-in values. Treat recording/transcript
as a pair: overriding a recording discards a lower-priority transcript unless its replacement
is also supplied. Explicitly disabling cloning suppresses lower-priority clone settings.
Relative paths follow the CLI working directory; desktop pickers supply absolute paths.

Use a typed resolved voice selection distinguishing a built-in voice from reference
conditioning. A recording path must never masquerade as a built-in voice name. When cloning
is active, an inherited built-in default such as Jasper is inactive. Explicit `--voice` with
cloning is an error. A profile that explicitly selects both is invalid.

For the first release, a selected chapter with `voice_id` or `[[voice:...]]` markers conflicts
with cloning. Preflight those chapters before synthesis and explain how to remove the override
or select built-in narration. Unselected chapters do not block a selective conversion. Never
silently ignore approved chapter/passage voice choices.

## 4. VC3 — Reference validation and preparation

The following are project limits for the first release, to be verified against the pinned model:

- Accept local WAV, FLAC, or MP3 files, at most 10 MiB and 5–30 seconds after decoding. Require
  a readable regular file with decodable, finite, non-silent audio. Reject network URLs,
  devices, FIFOs, unsupported formats, empty audio, and out-of-range duration. Do not silently
  crop a long recording or choose a segment of a multi-speaker recording.
- Explain that references should contain one clear speaker and little background noise.
  Automated validation does not certify speaker count or recording quality.
- Decode through bounded FFmpeg execution to a canonical mono PCM snapshot. Fix and version
  its sample rate and normalization policy in the compatibility spike. Snapshot the supplied
  bytes consistently before deriving hashes; detect a file changed during capture. Use that
  immutable snapshot throughout the run, even if the original subsequently changes.
- Accept an optional nonempty UTF-8 transcript file, at most 64 KiB. It contains the exact
  words spoken in the reference, not the book text. Normalize line endings consistently;
  do not apply book cleanup, pronunciation replacements, citations, or equation edits to it.
- Without a supplied transcript, use a ready local Whisper backend from the existing ASR
  subsystem. If its dependencies/weights are unavailable, ask for a transcript file or explicit
  model setup. Never let an SDK's implicit transcription download models or contact a service.
  Resolve the transcript locally and always pass `reference_text` to the TTS SDK.
- Prepare conditioning once per distinct selection per run and reuse it across chunks and
  chapters where the SDK permits. Keep snapshots, transcripts, and embeddings private; remove
  temporary artifacts on success, failure, and cancellation. Do not copy the user's original
  recording into book workspaces or delete/change it.

## 5. VC4 — CLI contract

Add these unset-by-default options to `convert`, `batch`, and `resynthesize`:

```text
--clone-voice / --no-clone-voice
--reference-audio PATH
--reference-text-file PATH
```

Reference options require effective cloning to be enabled; explicit reference flags combined
with effective disabled cloning are invalid. Retained, inactive TOML paths are allowed.
Cloning requires a recording and a model whose capabilities include cloning. Reject unsupported
combinations before any model load or replacement of existing audio.

Proposed examples, after the optional dependencies and model artifacts are installed:

```bash
uv run pdf2audiobook tts models --json
uv run pdf2audiobook tts fetch kitten2
uv run pdf2audiobook convert book.pdf --no-llm --tts-model kitten2 --clone-voice \
  --reference-audio ./narrator.wav --reference-text-file ./narrator.txt
uv run pdf2audiobook batch ./books --no-llm --tts-model kitten2 --clone-voice \
  --reference-audio ./narrator.wav --reference-text-file ./narrator.txt
uv run pdf2audiobook resynthesize ./audiobooks/BOOK/manifest.json --chapter 3 \
  --tts-model kitten2 --clone-voice --reference-audio ./narrator.wav \
  --reference-text-file ./narrator.txt
```

Extend `resynthesize` model/provider selection as necessary; it must not assume today's
global voice/model when repairing audio originally synthesized with cloning.

`convert --dry-run` resolves settings, selection conflicts, and reference media validity, and
reports whether cloning prerequisites are ready. It produces no audio, conditioning, ASR
transcript, model load, or download; a supplied transcript is not required merely to plan.
Existing analysis/OCR side effects of dry-run remain documented.

Use existing exit-code families with additive stable `reason` codes:

| Failure | Exit | Reason |
|---|---|---|
| Invalid options/reference metadata or voice-selection conflict | 2 | `voice_reference_invalid` or `voice_selection_conflict` |
| Model/provider does not support cloning | 2 | `voice_clone_unsupported` |
| Missing SDK, weights, device/backend, or local transcription prerequisites | 6 | `voice_clone_unavailable` |
| Reference decode/conditioning failure or change during capture | 6 | `voice_reference_invalid` or `voice_reference_changed` |
| Interruption | 130 | Existing interrupted result |

Keep batch/partial-failure behavior consistent with existing commands. Describe clone mode,
readiness and reason codes in additive JSON contracts, including `doctor` and `voices` capability
reporting. Diagnostics show configured/unset reference status, not reference text or private
recording paths. Existing clients and built-in voice listing continue to work.

## 6. VC5 — Provider and synthesis pipeline

Extend `tts/` adapters and resolved selection rather than creating a second audiobook pipeline.
Select reference-conditioned generation only for an explicitly supported KittenTTS 2 model.
Pass the snapshot and resolved transcript, and omit the upstream `voice` argument completely.

Preserve bounded chunking, pauses, source-offset progress, chapter selection, sample rate,
pronunciations, citation/equation processing, and mono finite output validation. The reference
transcript must never become narration. Verify the pinned SDK's speed and chunk-limit support;
adapt through supported options or deterministic audio processing, never ignored/unknown SDK
keywords. Include any speed transformation in synthesis identity.

A backend failure must be content-free and must not trigger a change to another voice. Keep
existing workspace locks and chapter failure accounting. A canceled/failed clone repair keeps
the previous MP3 and sidecar playable; reuse `resynthesize` staging, backups, and verification.
Bound cancellation during conditioning/model inference with process isolation if necessary;
record measured limits rather than treating a chunk boundary as a guarantee.

## 7. VC6 — Identity, resume, and downstream compatibility

Conditioning participates in chunk-cache keys, progress/resume identity, chapter fingerprints,
and sidecar rendering inputs. Include:

- A versioned clone-selection/conditioning identity and canonical reference PCM SHA-256.
- Effective transcript SHA-256; for automatic transcription, the ASR identity/revision.
- TTS model and decoder artifact revisions, SDK/backend versions, relevant generation/seed
  settings, and preparation/speed processing versions.

Compare actual content, not just pathname, size, or mtime. Two recordings at the same path must
not reuse one another's audio. A changed effective transcript or model must invalidate affected
clone audio. Moving identical files must not change the content identity. Do not promise
byte-identical fresh generations from stochastic inference; cache identity is input identity.

Store only the necessary hashes and content-free mode/version metadata in sidecars/reports.
Do not store raw reference audio, reference transcripts, embeddings, or absolute reference paths
there. With cloning inactive and an unchanged installed SDK, legacy cache keys/fingerprints
remain identical; omit clone-only keys rather than writing unconditional null/default fields.
Any intentional SDK upgrade and resulting legacy model-identity change must be documented.

Reusing already valid cloned MP3s, playback, M4B packaging, and verifying those files must not
require cloning dependencies or the original recording. Repairs/new synthesis require a
reproducible clone selection. If a repair would otherwise substitute a built-in voice for
recorded clone audio without explicit intent, stop with guidance to provide the reference or
explicitly choose `--no-clone-voice`. Never reconstruct a reference from a digest.

Voice selection changes affect synthesis, not chapter analysis, boundaries, approvals, or text.
ASR comparison still uses exact narration and audio hashes; it does not assess voice similarity.

## 8. VC7 — Tauri integration and user experience

- Add “Built-in voice” and “Clone from recording” choices to book options and the chapter
  “Speak again” flow. Clone selection explicitly selects the supported model, explains model
  readiness, and offers a native WAV/FLAC/MP3 picker plus optional transcript entry/file picker.
  Clone requests omit built-in `voice` arguments, including the app's remembered default.
- Give clear inline errors for incompatible models, missing/invalid references, unavailable
  local transcription, and chapter/passage voice conflicts. Keep draft values after failures.
  Turning cloning off restores ordinary voice controls without erasing saved defaults.
- Expose optional clone defaults in Settings through the shared TOML configuration flow.
  Persist recording/transcript paths only when the user explicitly saves defaults. Keep typed
  transcript drafts out of `settings.json`, local storage, and ordinary book metadata.
- The app delegates model listing/fetch, reference preparation, transcription, and synthesis
  to the CLI. Model downloads happen only through the explicit setup action. Add no direct
  HTTP client, network permission, microphone permission, or in-app model inference.
- Extend TypeScript/Rust request types, argument builders, schemas, and real-output fixtures
  together. Never send transcript contents in argv: write typed transcript drafts to private
  temporary UTF-8 files, retain them until the child exits, and clean them on every exit path.
  The app must not manufacture a reference path from a redacted diagnostic placeholder.
- Show preparation and synthesis progress through the existing run screen, with cancellation.
  Reuse chapter playback, audio verification, and safe repair controls. A shared-config
  default may be shown as “From configuration” without exposing its private paths in tables.
- Keep reference paths/transcripts out of command Details and app logs, including failed
  requests. Actual CLI file arguments can be visible to local process-inspection tools;
  transcript contents and audio bytes must never be arguments.

## 9. VC8 — Privacy, tests, and release acceptance

All reference audio, transcripts, conditioning, and narration stay local. Only explicit model
setup downloads public model artifacts; no recording is uploaded. Existing remote-LLM consent
requirements remain separate. Document use of one's own or an authorized reference recording.

Normal CI uses generated tones/synthetic text and fake providers/ASR, with no model downloads.
Test untrusted filenames, path/URL rejection, symlink handling, bounded decoding, concurrent
source changes, content-free errors/logs, cancellation, and temporary-file cleanup. Permit
explicit user-selected regular-file targets only; refuse broken links and unsafe file types.

Release requires all of the following, for both CLI and Tauri:

1. Legacy Kitten/Piper behavior and non-clone identities are preserved for the same SDK.
2. Valid references work for full conversion, batch, selected chapters, and safe resynthesis.
3. Settings/CLI/profile precedence, paired reference replacement, and explicit disable work.
4. Invalid or conflicting input fails before synthesis; no silent fallback/download occurs.
5. Reference/transcript/model changes invalidate the correct caches without changing analysis.
6. Failed/canceled work preserves prior audio and removes only application-owned temporaries.
7. Packaging, playback, and ASR inspection of completed audio work without its reference/model.
8. Typed bridge contracts and desktop controls exercise the same selection and validation.
9. Opt-in real-model acceptance includes CPU and an available supported accelerator, long-form
   chunk continuity, listening for speaker similarity, speed, failure, and cancellation.
10. Documentation records exact tested versions/revisions, resource measurements, install/fetch
    steps, privacy, limitations, and any acceptance gate not yet completed.

No release-complete status is justified by fake-provider tests alone. Missing hardware or model
access is recorded as an outstanding acceptance gate, not a passed test. Dependency/model pins,
canonical PCM policy, and measured resource/cancellation limits are recorded in VC0 of the TODO.
Unverified real-model and hardware gates remain open. Hosted cloning remains a separate future proposal.
