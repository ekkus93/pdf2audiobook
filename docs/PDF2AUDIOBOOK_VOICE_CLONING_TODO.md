# PDF2Audiobook Voice Cloning TODO

**Status:** CLI/Tauri delivered; review reopened VC5.05; accelerator acceptance remains open.
**Date:** 2026-11-18
**Last reviewed:** 2026-11-20
**Specification:** [Voice Cloning Specification](PDF2AUDIOBOOK_VOICE_CLONING_SPEC.md) (VC1–VC8)
**Baseline:** `master` at `451551c`, plus the working-tree configuration initializer and Settings editor.
**Delivery:** Both the CLI and Tauri app are required for completion.
**Task audit:** [All 40 tasks and clauses](PDF2AUDIOBOOK_VOICE_CLONING_REVIEW_AUDIT.md) — 37 verified; VC5.05 and two hardware tasks open.


> Commit-series provenance: historical checks below describe the reviewed working tree.
> R1 committed that tree in dependency order; use the
> [review follow-up ledger](PDF2AUDIOBOOK_VOICE_CLONING_REVIEW_TODO.md) for exact committed
> revisions and CI evidence. Historical counts are recorded evidence, not new measurements.

## Current validation state

Final code revision: `99416560b9081dd61f8fecd1c52d870fdc0a4c0f`. All rows below were measured on its
exact exported Git tree after the last code change, then committed unchanged. Later
documentation commits record this evidence and do not change the tested code. Local logs,
package artifacts and synthetic screenshots are retained outside Git under the review
validation cache (`review-2026-11-19/r5/`). Commands below reproduce the corresponding gates.

| Gate | Revision | Date | Current result/count | Evidence |
|---|---|---|---|---|
| Lockfile | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 137 packages resolved; locked sync passed | `uv lock --check`; `uv sync --locked --extra dev`; [Python CI #928](https://github.com/ekkus93/pdf2audiobook/actions/runs/44713371948) |
| Ruff lint | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 0 findings | `uv run --extra dev ruff check .`; [Python CI #928](https://github.com/ekkus93/pdf2audiobook/actions/runs/44713371948) |
| Ruff format | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 505 files already formatted | `uv run --extra dev ruff format --check .`; [Python CI #928](https://github.com/ekkus93/pdf2audiobook/actions/runs/44713371948) |
| mypy 3.11 | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 110 source modules; 0 issues | `uv run --extra dev mypy --python-version 3.11`; [Python CI #928](https://github.com/ekkus93/pdf2audiobook/actions/runs/44713371948) |
| mypy 3.12 | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 110 source modules; 0 issues | `uv run --extra dev mypy --python-version 3.12`; [Python CI #928](https://github.com/ekkus93/pdf2audiobook/actions/runs/44713371948) |
| mypy 3.13 | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 110 source modules; 0 issues | `uv run --extra dev mypy --python-version 3.13`; [Python CI #928](https://github.com/ekkus93/pdf2audiobook/actions/runs/44713371948) |
| Full offline pytest | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | **2,807 passed, 6 skipped, 1 xfailed** | `uv run --extra dev pytest -q -ra`; local 173.92 s; [Python CI #928](https://github.com/ekkus93/pdf2audiobook/actions/runs/44713371948) confirms identical counts on all three versions |
| CLI smoke | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 3/3 passed | `--help`, `config show --json`, `doctor --json`; isolated configuration; [Python CI #928](https://github.com/ekkus93/pdf2audiobook/actions/runs/44713371948) |
| Wheel smoke | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 1 wheel built; clean install/import and 3/3 CLI smokes passed | `uv build --wheel`; separate fresh venv; installed-source location verified; [Python CI #928](https://github.com/ekkus93/pdf2audiobook/actions/runs/44713371948) |
| sdist smoke | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 1 sdist built; clean install/import and 3/3 CLI smokes passed | `uv build --sdist`; separate fresh venv; installed-source location verified; [Python CI #928](https://github.com/ekkus93/pdf2audiobook/actions/runs/44713371948) |
| Desktop lint | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 0 errors/warnings | `npm run lint` in the exported desktop source |
| Desktop types | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 3 TypeScript configurations passed | `npm run typecheck` |
| Desktop Vitest | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 384 tests passed in 21 files | `npm test` |
| Frontend production build | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 1 production build passed | `npm run build`; existing Vite bundle-size advisory |
| Rust format | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 1 crate passed | `cargo fmt --check` |
| Rust clippy | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | All targets passed; 0 warnings | `cargo clippy --all-targets -- -D warnings` |
| Rust default tests | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 120 unit + 7 permission tests passed; 4 opt-ins ignored | `cargo test` |
| Rust real-CLI integrations | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 3/3 explicit opt-ins passed | Synthetic clone convert/resume/repair; shared-config initialize/validate/save; read-only bridge requests; each run with `--ignored` |
| Native walkthrough | [`9941656`](https://github.com/ekkus93/pdf2audiobook/commit/99416560b9081dd61f8fecd1c52d870fdc0a4c0f) | 2026-11-20 | 1/1 local synthetic walkthrough passed (70.39 s) | Native picker, typed draft, actual CLI MP3s, resume, selected repair, cancellation/cleanup and dark/light captures; Desktop CI #83 pending |

The six pytest skips are one optional Kitten smoke, three real-ASR opt-ins and two
real-clone opt-ins; none is caused by missing FFmpeg, Tesseract or Node. The strict
expected failure is the reproduced **VC5.05** retained-reference/dependency-removal
resume gap, **not passed acceptance**. Default Rust ignores four opt-ins; three offline
CLI integrations were run explicitly, while the real-model bridge was not repeated.
The Xvfb walkthrough exercises playback controls/seek, not physical speaker output.

**Supersession:** every older software counter and individual timing observation in the
progress prose below is historical and superseded by this table for current validation.
The history is retained. Real-model, listening and resource/timing results from 2026-11-19
are recorded evidence, not re-measured here; accelerator tasks VC0.03/VC8.04 remain open.

## Working rules

- Follow the dependency order below. Check a task only when its implementation and named
  validation exist; record commit/test evidence and remaining gates in the ledger.
- Preserve existing Kitten/Piper defaults and inactive-cloning behavior. Use deterministic
  offline fixtures and fake SDK/ASR backends for CI; real models are explicit opt-in acceptance.
- Add new runtime modules to `pyproject.toml`'s mypy files. Update affected Python, Rust,
  TypeScript and JSON contracts together. Do not commit recordings, transcripts, model weights,
  conditioning caches, private paths, or generated workspaces.
- Keep fixes scoped to this feature. Record unrelated failures separately; skipped or blocked
  real-model/hardware checks remain open.

## VC0 — Compatibility spike and baseline (spec VC1, VC5, VC8)

- [x] VC0.01 Record current provider selection, profile precedence, voice overrides, speed,
  chunk/progress identity, sidecars, packaging and repair behavior. Identify integration points
  in `config.py`, `tts/`, `conversion.py`, `audio/`, `cli/`, and `desktop/`.
- [x] VC0.02 Verify the locked SDK and a candidate pinned SDK against the full KittenTTS 2
  model. Record supported `reference`/`reference_text`, voice exclusion, conditioning reuse,
  speed behavior, chunk/output limits, and offline loading. Confirm smaller models are rejected.
- [ ] VC0.03 Resolve dependency compatibility and pin the model/decoder artifacts, revisions,
  backend settings, and canonical PCM policy. Record model/code license terms, download sizes,
  CPU/GPU memory, generation speed and cancellation measurements without committing artifacts.
- [x] VC0.04 Define capability/readiness and clone-identity contracts from the spike. Establish
  golden legacy identities for a fixed SDK and deterministic fixture selections.

## VC1 — Optional installation and model setup (spec VC1)

- [x] VC1.01 Keep ML dependencies optional; adjust the `kitten` extra only as verified by VC0.
  Regenerate/review `uv.lock` when needed, and check resolution for Python 3.11–3.13.
- [x] VC1.02 Add the explicit `kitten2` alias and capability detection. Preserve existing model
  aliases, provider values and voice lists; reject unsupported cloning without loading a model.
- [x] VC1.03 Implement `tts models` and `tts fetch kitten2`, including JSON output, explicit
  download action, source/size/destination reporting, revision/integrity checks, offline reuse,
  interrupted-download cleanup, and actionable package/weights/device readiness.
- [x] VC1.04 Test that startup, `config init`, `config validate`, `doctor`, `voices`, model
  listing and dry-run do not import/load the large model, infer speech, or access the network.

## VC2 — Configuration and resolved voice selection (spec VC2)

- [x] VC2.01 Add disabled-by-default clone settings, optional reference paths, environment
  mappings, and matching per-book profile fields. Extend validation and config-source reporting.
- [x] VC2.02 Implement typed built-in/reference selection. Keep default voices inactive during
  cloning; reject explicit `--voice`, selected chapter voice overrides, and paragraph markers
  that conflict with the first-release clone mode.
- [x] VC2.03 Implement precedence and paired-reference replacement: a newly selected recording
  cannot inherit another recording's transcript. Support explicit disabling of inherited clones.
- [x] VC2.04 Add tests for the complete precedence matrix, inactive/missing paths, relative
  paths, config initialization defaults, selected versus unselected chapter conflicts, and
  redacted diagnostics. Pin unchanged non-clone behavior in regression tests.

## VC3 — Reference preparation and local provider (spec VC3, VC5)

- [x] VC3.01 Implement bounded media validation and private immutable snapshots. Cover WAV,
  FLAC and MP3, byte/duration limits, malformed/empty/non-finite/silent input, regular-file and
  symlink policy, unsafe file types/URLs, and mutation during/after capture.
- [x] VC3.02 Implement bounded UTF-8 transcript-file reading and consistent line endings.
  With no transcript, use only a ready local Whisper backend; provide missing-model guidance
  and prevent implicit SDK transcription/network downloads.
- [x] VC3.03 Add a lazy KittenTTS 2 adapter that passes reference and resolved transcript while
  omitting `voice`. Reuse conditioning per selection, sanitize backend prints/errors, and
  validate mono finite output. Implement verified speed and chunk handling from VC0.
- [x] VC3.04 Integrate existing pauses, narration transforms, source progress and chapter
  selection. Test that reference transcript/audio never enters the narrated book text.
- [x] VC3.05 Test conditioning/inference failures, bounded cancellation and resource cleanup.
  Use a worker-process boundary if the SDK cannot meet the measured cancellation contract.

## VC4 — CLI commands and diagnostics (spec VC4)

- [x] VC4.01 Add `--clone-voice/--no-clone-voice`, `--reference-audio` and
  `--reference-text-file` to `convert`, `batch`, and `resynthesize`; extend repair model/provider
  selection and help examples. Preserve unset flag semantics and existing exit-code families.
- [x] VC4.02 Add clone readiness/capabilities and stable reason codes to JSON schemas, fixtures,
  diagnostics and human errors. Redact reference paths and never emit reference transcript text.
- [x] VC4.03 Implement dry-run media/selection checks without TTS/ASR inference or downloads.
  Report missing prerequisites separately from invalid input and preserve existing dry-run scope.
- [x] VC4.04 Add offline CLI tests for full conversion, batch profiles, chapter/range selection,
  optional transcript, disabling, invalid combinations, missing dependencies, partial failures,
  interruptions, private errors, and unchanged behavior without cloning.

## VC5 — Cache identity, resume, and repair safety (spec VC6)

- [x] VC5.01 Include conditioning version, reference PCM/transcript digests, auto-transcription
  identity where used, model/decoder revisions, backend and generation settings in chunk caches,
  progress/resume records, chapter fingerprints and rendering inputs.
- [x] VC5.02 Test same-path replacement with equal size/mtime, transcript changes, changed model
  revisions, identical content moved to a new path, and immutable in-flight snapshots. Ensure
  only affected synthesis becomes stale and chapter analysis/approvals/text are untouched.
- [x] VC5.03 Keep clone-only fields out of legacy identities and sidecars when disabled. Test
  legacy golden compatibility for the same SDK; document any intentional SDK identity change.
- [x] VC5.04 Integrate safe resynthesis staging/backups and detect missing clone selection
  during repairs. Require explicit intent to switch existing clone audio to a built-in voice.
- [ ] VC5.05 Test failed/canceled clone repairs retain valid prior MP3/sidecar pairs. Verify
  packing, playback and ASR inspection of finished audio need neither cloning models nor the
  original recording; ASR must assess narration content, not speaker similarity.

## VC6 — Tauri bridge and lifecycle (spec VC7)

- [x] VC6.01 Extend Rust/TypeScript options and repair requests, argument builders, capability
  and error schemas, and fixtures. Test awkward paths remain single arguments without a shell.
- [x] VC6.02 Pass typed transcript drafts through private temporary files, never argv text.
  Keep them alive until the child exits; test completion, failure, cancellation, window close,
  and startup cleanup of application-owned leftovers.
- [x] VC6.03 Redact reference fields in command Details, event logs and generic errors. Preserve
  workspace locking and add marker-based privacy tests across successful and failed requests.
- [x] VC6.04 Add bridge-to-real-CLI integration coverage using a synthetic reference and fake
  synthesis, plus opt-in real-model coverage. Confirm no network or microphone permissions/client
  dependencies are added to the desktop app.

## VC7 — Tauri screens and interaction (spec VC7)

- [x] VC7.01 Add built-in/clone selection to book options, the supported model choice, native
  reference picker, optional transcript entry/file picker, readiness and inline validation.
- [x] VC7.02 Add Settings defaults through the shared config flow. Persist paths only on an
  explicit save, keep typed transcript drafts transient, and support configuration-sourced
  references without using redacted placeholder strings as paths.
- [x] VC7.03 Extend “Speak again” with clone selection and safe reuse/change of the reference.
  Show preparation/synthesis progress and cancellation through the existing run screen.
- [x] VC7.04 Test request parity with CLI, inherited defaults, mode switches, chapter/paragraph
  conflicts, missing local ASR, failed saves/runs retaining drafts, and safe repair/playback.
  Cover labels, keyboard operation, error focus, and the existing themes.
- [x] VC7.05 Extend the native walkthrough to exercise reference selection, synthesis, repair,
  resume and cancellation. Capture the clone controls and results without private recordings.

## VC8 — Documentation and release acceptance (spec VC8)

- [x] VC8.01 Update user guides, maintainer guidance, the main specification, Tauri specification
  and command examples. Explain full KittenTTS 2 versus 0.8/small models, local setup/fetch,
  reference/transcript preparation, defaults, limits, resource costs, privacy and cache behavior.
- [x] VC8.02 Run applicable documented Python checks: lockfile, Ruff lint/format, mypy, full
  offline pytest, CLI smoke, and clean installed-package smoke. Record passed/failed/skipped
  results accurately and keep unrelated environment failures distinct.
- [x] VC8.03 Run desktop lint, type checks, Vitest, production frontend build, Rust fmt/clippy/
  tests and native walkthrough. Validate typed fixtures and permission/network checks.
- [ ] VC8.04 Run opt-in real-model acceptance with an authorized reference on CPU and an
  available supported accelerator. Listen for similarity and chunk continuity; measure speed,
  memory, cancellation, warm resume and selective repair. Keep private media outside Git.
- [x] VC8.05 Review every acceptance item in spec §9 against implementation/test evidence.
  Record missing hardware/model access as an unfinished gate. Both CLI and desktop must be
  delivered before declaring the feature complete.

## Acceptance mapping

| Spec §9 criterion | Primary implementation/validation tasks |
|---|---|
| 1. Legacy compatibility | VC0.04, VC2.04, VC5.03 |
| 2. Conversion, batch, selection and repair | VC4.04, VC7.03, VC7.05 |
| 3. Precedence and disabling | VC2.03, VC2.04, VC7.04 |
| 4. Validation, no fallback/download | VC1.04, VC3.01–VC3.03, VC4.02–VC4.04 |
| 5. Identity and analysis isolation | VC5.01–VC5.03 |
| 6. Failure/cancellation safety | VC3.05, VC5.04, VC5.05, VC6.02 |
| 7. Finished audio without reference/model | VC5.05, VC7.04 |
| 8. CLI/desktop parity | VC6.01, VC6.04, VC7.04, VC7.05 |
| 9. Real-model acceptance | VC0.03, VC8.04 |
| 10. Documentation and remaining gates | VC8.01–VC8.05 |

## Progress ledger

> Historical checkpoints: all counters below are superseded by the Current validation state
> table above. Earlier “only accelerator gates remain” conclusions predate the reopened VC5.05.

| Date | Commit/tree | Completed tasks | Validation | Outstanding gates |
|---|---|---|---|---|
| 2026-11-18 | `451551c` + existing config work | Spec and TODO drafted; no implementation tasks checked | Documentation links, requirement coverage and checklist structure | VC0–VC8 implementation and acceptance |

### Baseline and compatibility evidence (2026-11-18)

- VC0.01: `tts/selection.py` resolves CLI-explicit choices over a filename-stem profile,
  which overrides the merged environment/global settings. Chapter `voice_id` wins over the
  default; approved paragraph markers are checked in `conversion.py`. Chunk identities and
  progress include model/voice/speed; chapter identity is `pipeline.chapter_audio_fingerprint`;
  `conversion._rendering_inputs` currently records footnotes and conditional citations only.
  Repair uses the same forced conversion and `audio/commit.py` staging/backups; packaging and
  ASR reference construction consume existing audio/text rather than rebuilding a provider.
- Source inspection: verified the locked `kittenml==0.9.6` wheel against lockfile SHA-256
  `5362a22c0caf4def3ff2a3ac3c5a24e18bbcea94866d62c1762ee4a24b8084df`. Its
  `KittenTTS2.generate` accepts `reference`/`reference_text`, forbids simultaneous `voice`,
  caches reference conditioning per path/transcript, and has no `speed` keyword. Its decoder
  fetches `ResembleAI/chatterbox-turbo/s3gen_meanflow.safetensors` unless redirected offline.
  Source verification alone was not a real-model pass; the locked-graph CPU evidence below
  now completes VC0.02.
- Public model metadata: `KittenML/kitten-tts-2` revision
  `c93cb7c271baa51d9ae8204d5277988906f235a2`; artifact pinning is being implemented.
- Host: 7.1 GiB RAM, approximately 16 GiB disk free, and no `nvidia-smi`. Accelerator
  measurements/listening remain outstanding (VC0.03/VC8.04). Continue independent software
  work; do not mark simulated synthesis as real-model acceptance.

### Software checkpoint 1 (2026-11-18)

- VC0.04 / VC2.01 / VC2.03 / VC3.01: typed built-in/reference selection, disabled
  clone configuration and three environment variables, profile/CLI pairing precedence,
  redacted reference fields, bounded canonical snapshots, and content-based identities are
  implemented. `tests/test_voice_cloning.py` covers moved references, same-size/mtime content
  replacement, mutation during capture, WAV/FLAC/MP3, duration/silence, explicit symlink
  targets, unsafe inputs, private crash cleanup, and worker timeout/reaping.
- Validation: `uv run --extra dev pytest -q tests/test_voice_cloning.py tests/test_config.py
  tests/test_config_init.py tests/test_cli_help_examples.py tests/test_citation_identity.py
  tests/test_tts_model_identity.py`: **99 passed**. Ruff lint/format passed; mypy passed
  for **110 runtime modules**. Legacy model golden at SDK 0.9.6 is
  `1f3c2200e71ea50ebed4f2cde48c21ec55f3509b8c126f1dd1ccdbe295ba66b8`.
- Model setup: fetched and SHA-256 verified the 31 pinned artifacts (full model, external
  decoder, and eight existing built-in voices) into the user model cache, outside Git.
  Decoder revision: `749d1c1a46eb10492095d68fbcf55691ccf137cd`; full artifact pins are
  shipped in `tts/kitten2_manifest.json`. This is download/integrity evidence, not inference
  or listening acceptance. CPU SDK installation/spike is in progress in an isolated /tmp env.
- Next: conversion/cache/repair integration tests, complete CLI diagnostics and JSON
  contracts, then the Rust/TypeScript bridge and desktop controls. Hardware gates remain open.

### Software checkpoint 2 (2026-11-18)

- CLI conversion, dry-run, batch/repair options, typed clone selections, private-pipe
  conditioning and speech, and content-addressed chunk/chapter identities are integrated.
  Reference changes invalidate audio without changing analysis; clone sidecars contain only
  digests/settings. Explicit repair intent is required to switch away from cloned audio.
- Offline integration: **19 passed** across clone conversion, legacy conversion and repair;
  **53 passed** across clone/reference/discovery/contract tests; subsequent expanded reference
  and CLI suites: **47 passed**. Tests exercise actual FFmpeg MP3s, missing-reference resume,
  selected chapter overrides, interrupted artifact downloads, repeated worker conditioning,
  backend-output suppression, and force-killed parent/worker cleanup.
- Desktop: shared Rust/TypeScript reference options and model setup requests, redacted Details,
  private typed-transcript files held through child exit, startup cleanup, book/repair controls
  and explicit-save shared TOML defaults are implemented. **374 Vitest tests passed**; Rust
  **118 unit + 7 permission tests passed**, with 2 explicit real-CLI tests still opt-in.
  Lint, TypeScript checks and mypy (110 runtime modules) passed at this checkpoint.
- Real CPU compatibility: the direct SDK constructor loaded the pinned full model and external
  decoder fully offline at 24 kHz with SDK 0.9.6 / torch 2.15.0+cpu / torchaudio 2.11.1+cpu /
  transformers 5.23.0 in an isolated environment. Cold loading took **7m54s wall**, **116s CPU**,
  peak **3,344,632 KiB RSS** on this busy 7.1-GiB host (substantial paging). This is not a locked
  dependency-graph, inference or listening acceptance pass. Preparation timeout now allows
  15 minutes and cancellation remains separately bounded. Real inference is in progress.
- Remaining: full precedence/batch/repair/privacy matrices, lifecycle/native walkthrough,
  release checks, documentation and real-model/hardware/listening gates. No feature commit yet.

### Software checkpoint 3 and CPU acceptance (2026-11-19)

- CLI and desktop implementation now cover the remaining precedence, reference pairing,
  explicit-disable, range/paragraph-conflict, model-revision, partial-failure, cancellation,
  packing and ASR-narration matrices. `tests/test_voice_cloning*.py` includes synthetic
  private-marker fixtures, actual FFmpeg MP3 publication, optional local-ASR success/failure,
  and explicit built-in repair that ignores retained reference paths. Model revision changes
  rebuild selected speech while preserving other audio and the analysis manifest.
- Preparation/conditioning runs before chapter synthesis, with its own progress stage and
  exit-code-6 failures. Worker errors distinguish failed reference conditioning from missing
  model/resources without exposing backend output. Request deadlines cover blocked stdin
  as well as inference; worker shutdown reaps orphaned ASR temporaries while preserving
  locked active jobs. Non-POSIX startup remains usable; unsupported cloning fails explicitly.
- Discovery of official legacy Kitten voices now uses their eight-name offline catalog,
  preserving synthesis defaults and the missing-package diagnostic without constructing the
  SDK or downloading weights. Custom models without a known offline catalog report no list.
  The optional SDK constraint is exactly 0.9.6; `uv.lock` changed only that requirement, not
  its resolved package versions. Python 3.11–3.13 resolution/type checks passed in the prior
  run; current lock/Ruff/mypy checks pass (110 modules).
- Current full offline Python run: **2,751 passed, 5 skipped, 2 failed**. Both failures are
  pre-existing expectations in `test_verify_audio_cli.py` that omit `whisper_low_memory` on
  this 7.1-GiB host. They remain separate from feature failures; VC8.02 stays open. The new
  focused model-revision case also passed. Subsequent preparation/cancellation matrix checks
  passed; final counts will be recorded below after all additions.
- Desktop rerun: **383 Vitest tests passed**, lint/type checks and production frontend build
  passed (existing Vite chunk-size advisory only). Rust **119 unit + 7 permission tests
  passed**; all **3 synthetic real-CLI bridge tests passed**. The fourth ignored test is a
  newly added opt-in real-model Rust request/CLI test, separate from the `real_cli` filter.
- Native clone walkthrough passed on 2026-11-18 with actual CLI/FFmpeg and explicitly synthetic
  speech: recording picker, typed transcript, conversion, warm resume, selective repair/backups,
  cancellation and private-file cleanup. Its temporary screenshots were lost across the
  interruption. A reproducible isolated D-Bus/Xvfb helper and dark/light captures are now
  being validated; CI is configured to exercise cloning for executable and AppImage runs.
- Real CPU test: `tests/test_voice_cloning_real.py` **passed** using the upstream public Bruno
  sample and the locked graph with CPU wheels (`torch==2.14.1+cpu`,
  `torchaudio==2.11.0+cpu`, `kittenml==0.9.6`, other versions constrained by `uv.lock`).
  It produced **two 8.4-second MP3s** and verified warm resume without loading a model.
  Pytest wall time **599.08 s**; measured process-tree wall **603.54 s**,
  **801.07 s CPU**, peak **4,432,680 KiB RSS**. Substantial paging limits these host timings.
- Real selective repair at speed 1.25 also passed: **384.45 s** wall; chapter 1 unchanged,
  chapter 2 backed up, new duration **6.84 s** versus **8.40 s**. The real-model Rust bridge
  subsequently passed conversion and warm resume (**1 passed, 399.08 s**). The earlier locked-SDK cancellation measurement was **0.032 s**
  with its model-loading worker reaped; deterministic timeout/forced-parent-death tests pass.
- A prior SDK 0.9.6 / torch 2.15.0+cpu candidate spike loaded and conditioned the reference,
  but was stopped after **23m46s** without generated speech on the overloaded host. It is
  not a successful inference benchmark. No CUDA device is available. On 2026-11-19 the user
  answered **“Not reviewed yet”** for the reference/generated speaker comparison; listening
  acceptance is explicitly pending.
- Durable local validation logs, generated audio and measurements now live outside Git under
  `~/.cache/pdf2audiobook/validation/2026-11-19/`; the prepared CPU CLI is in
  `~/.cache/pdf2audiobook/acceptance-venv/`. No recordings, weights, transcripts or generated
  workspaces were added to the repository. No feature commit/push has been made.

### Spec §9 acceptance audit (2026-11-19; release incomplete)

| Criterion | Evidence and remaining gate |
|---|---|
| 1. Legacy compatibility | Golden SDK-0.9.6 identity, existing conversion/repair suites and unchanged inactive rendering inputs; official voice discovery is now offline metadata. |
| 2. Conversion/batch/selection/repair | Real CPU conversion and targeted repair; offline batch/range/partial-failure tests; native synthetic walkthrough. |
| 3. Precedence/disabling | Global/environment/profile/CLI pairing matrix, explicit disable repair, redacted inherited desktop profiles. |
| 4. Validation/no fallback/download | Bounded immutable-media/transcript tests, discovery import/network guards, exact errors, explicit fetch/integrity and cancellation tests. |
| 5. Identity/analysis isolation | Same-size/mtime replacement, moved content, transcript/model revision and immutable snapshot cases; manifest bytes remain unchanged. |
| 6. Failure/cancellation | Failed/canceled repairs preserve prior pairs; stdin/inference deadlines, process reaping, ASR orphan cleanup, Rust child lifetime/shutdown/startup cleanup. |
| 7. Finished audio independence | Pack/M4B and ASR-narration construction after reference deletion; playback uses the existing MP3-only protocol. |
| 8. CLI/desktop parity | Typed Rust/TypeScript/schema fixtures, awkward-path and privacy tests, native synthetic walkthrough; real Rust bridge conversion/warm resume passed. |
| 9. Real-model acceptance | CPU conversion/resume/repair, five-chunk assembly, and user speaker-similarity/consistency review passed; generated pacing was slower. Accelerator measurements remain open. |
| 10. Documentation/release checks | Guides/specs/maintainer contracts updated; baseline memory-warning tests repaired, full Python suite passes, earlier timing variation recorded; accelerator gates remain open. |

### Final software checks (2026-11-19)

- VC0.02: the selected candidate pin is the already-locked SDK **0.9.6**, now exercised
  through real full-model CPU conversion, warm resume and selective repair. No SDK upgrade
  was needed. Direct SDK source, worker contract tests and real execution verify reference/
  transcript support, omission of built-in voice, conditioning reuse, FFmpeg speed adjustment,
  offline pinned loading and the adapter's 350-character/120-second output bounds. Smaller
  models reject cloning before model construction. Full release/listening gates remain open.
- CLI reference flags retain raw strings until validation. A URL that resembles an existing
  local path is rejected rather than normalized into that path. All six combinations of
  convert/batch/repair and recording/transcript flags pass; the expanded CLI/help run reports
  **52 passed**. The prior final reference/conversion matrix reports **71 passed**.
- VC7.04/VC7.05/VC8.03: native walkthrough and session-wrapper cleanup now both exit **0**.
  The run covers native reference selection, typed transcript, actual CLI/FFmpeg with explicit
  synthetic speech, warm resume, repair backups, cancellation and private-file cleanup.
  Dark/light clone-control captures were inspected; keyboard/focus, inherited profiles,
  failed-run draft retention, shared-settings failures and stable errors have Vitest coverage.
  The full frontend **383 tests**, production build, lint/type checks, Rust fmt/clippy,
  **119 unit + 7 permission tests**, and **3 synthetic real-CLI bridge tests** passed.
- The native helper isolates X11, D-Bus, config/data/runtime and local-only file selection;
  shutdown retries avoid a transient desktop-filesystem cleanup race. Captures and native logs
  are in the external validation directory. The machine has no usable audio output device;
  the player-position check is UI/protocol evidence, not a listening result.
- Both host-dependent Python warning failures reproduced against a clean archive of committed
  baseline `451551c` (**2 failed**) with baseline source imports. No unrelated test expectations
  were changed. Clean installed wheel and sdist smokes passed: help, config, doctor, model/voice discovery,
  bundled manifest availability, no eager ML imports, and exclusion of desktop assets.
  The final full suite reports **2,765 passed, 6 skipped, 2 failed in 298.51 s**;
  only the two confirmed baseline warning expectations fail.
- The opt-in real-model bridge originally stopped before synthesis because its tracked PDF
  fixture was empty. Its harness now generates a text PDF. A separate opt-in longer sample
  is designed to exercise at least three real chunks and save a chapter for continuity listening; neither
  human similarity nor continuity is inferred from successful MP3 generation.

- The opt-in Rust bridge now passes against the real full model: **1 passed in 399.08 s**,
  actual CLI conversion followed by warm resume with unchanged MP3 modification times.
  The longer real multi-chunk CPU sample subsequently passed; see the final evidence below. Workflow contract tests were
  updated for the verified isolated native wrapper after the full suite exposed their old
  literal command expectations; this was a feature-related test correction, not a baseline issue.

- Final non-model gates: lockfile, Ruff lint/format, Python 3.11–3.13 mypy (**110 modules**),
  CLI smoke, clean wheel/sdist smokes, and Git whitespace checks passed. The final full Python
  run is **2,765 passed, 6 skipped, 2 baseline failures**. No feature test remains failing.
  Native dark/light captures and all desktop gates above passed; remote CI and packaged
  AppImage execution were configured, not run from this local session.

### Final real CPU evidence and resume point (2026-11-19)

- The longer real-model test **passed in 1,456.74 s**. All **5 chunks** assembled into a
  **73.728-second MP3**, using the same reference-conditioned worker. GNU time reports
  **1,459.05 s wall**, **2,362.42 s CPU**, peak **4,462,864 KiB RSS** (about 4.26 GiB), and
  substantial paging. The first part overlapped the offline Python suite on this 7.1-GiB host;
  these are observed host measurements, not a steady-state or realtime performance promise.
- Generated chapter: `real-audio/continuity/continuity-77db1ac207/audio/001 - Chapter 1.mp3`
  beneath the external validation directory above. The synthetic source PDF was preserved in
  `continuity-inputs/`; the public upstream Bruno reference and transcript remain outside Git.
  The user subsequently confirmed speaker similarity and consistency; see the listening result below.
- Real model-loading cancellation **passed**: exit **130**, **0.164 s** to stop, worker reaped,
  private files cleaned. Active-inference cancellation also **passed**: exit **130**, **1.423 s** to stop,
  worker reaped and private files cleaned.
- VC8.05: every spec §9 criterion has implementation/test evidence or an explicit unfinished
  acceptance gate in the audit above. Both CLI and desktop software are delivered; this audit
  completion does **not** declare the feature release-complete.

Remaining release prerequisites:

- **VC0.03 / VC8.04:** accelerator memory/speed measurements require a supported device;
  no supported accelerator is currently usable in this session. The user has now confirmed
  speaker similarity and consistency throughout the CPU sample; only the accelerator portion
  of these tasks remains open. Generated narration was perceived as slower than the reference.

### Listening-review handoff and accelerator recheck

- Prepared a local comparison page at `listening-review/index.html` under the external
  validation directory, with copies of the public reference and generated chapter. Review
  speaker identity, consistency across passages, and audible defects; a general agreement to
  proceed is not a listening acceptance result.
- Corrected the hardware inventory: KFD topology exposes AMD Renoir (`gfx90c`) integrated
  graphics. This session lacks read/write access to `/dev/kfd`, no ROCm utilities were found,
  and the prepared acceptance environment uses CPU-only Torch. The earlier absence of NVIDIA
  devices did not establish absence of all GPUs. No supported accelerator benchmark has run;
  VC0.03/VC8.04 remain open. No driver, group-membership or permission changes were made.

### User listening result

- The user compared the public reference recording with the 73.728-second, five-chunk CPU
  chapter and reported: **“It sounds like the same person but the second one was slower.
  The voice was consistent throughout.”**
- **Speaker similarity and audible consistency pass for this sample.** This supersedes the
  earlier “Not reviewed yet” status. Slower delivery is recorded as a pacing observation;
  the feedback does not establish absence of every possible audio defect.
- The acceptance fixture used the default narration speed **1.0**. The existing CLI `--speed`
  option and desktop speed control can adjust pacing; no global defaults were changed based
  on this comparison. The 1.25-speed CPU repair was already verified separately.
- VC8.04 remains unchecked for the unperformed accelerator acceptance, not for missing human
  speaker/consistency review. VC0.03 still needs accelerator measurements; the baseline warning
  failures were subsequently fixed as recorded below.

### Host-memory test repair

- At the user's request, fixed the two pre-existing verification CLI test failures. Fake-backend
  tests now default to a simulated 16-GiB host instead of reading the machine's physical RAM.
  Runtime warning behavior is unchanged.
- Added explicit warning coverage for low/enough/unknown RAM, the 8-GiB threshold, CPU/CUDA
  selection and unavailable Whisper, plus combined low-memory/missing-FFmpeg warnings.
  These are offline fake-backend tests, not accelerator acceptance.
- Targeted verification CLI suite: **38 passed**. Lockfile, Ruff lint/format and mypy
  (**110 runtime modules**) passed. The final full offline Python suite also passed, as recorded below.
- Accelerator acceptance is deferred to the different machine the user plans to provide;
  VC0.03/VC8.04 stay open.

- First full rerun after the memory fix: **2,773 passed, 6 skipped, 1 failed in 468.40 s**.
  The two original warning failures passed. The remaining failure was the unchanged
  `test_half_million_character_chapter_keeps_pause_count_with_linear_progress`: **15.82 s**
  against its 15-second wall-clock guard; all correctness assertions passed.
- Follow-up timing evidence: the progress module reproduced that timing failure at **60.63 s**
  (**32 other tests passed**). Subsequent single-test runs passed on committed baseline
  `451551c` (**4.51 s**) and the current tree (**6.09 s**). These variable timings are recorded
  separately from the memory fix; the timing threshold and synthesis code were not changed.
  The subsequent final full run passed, including this benchmark; see the completion result below.

- **VC8.02 complete:** final full offline Python suite **2,774 passed, 6 skipped in 469.24 s**.
  The six skips are explicit optional Kitten/ASR/real-clone checks. The existing timing
  benchmark passed in this full run; its earlier failures and differing runtimes remain
  recorded above. No timing threshold or runtime synthesis behavior was changed.
- The requested memory-test repair is complete. The implementation change is confined to
  `tests/test_verify_audio_cli.py`; Ruff lint/format, lockfile validation, mypy and the complete
  offline Python suite pass. Only **VC0.03 / VC8.04 accelerator acceptance** remains open,
  pending the user's move to a different machine.

### Review acceptance correction (2026-11-20)

- VC5.05 is **partially verified and reopened**. Failure/cancellation preservation,
  packing, playback and ASR narration inspection pass, but the shared spec also
  requires finished conversion reuse without cloning dependencies. With the
  recording and transcript still present, removing optional backend metadata
  changes the fresh identity and attempts synthesis again. The new strict expected
  failure in `tests/test_voice_cloning_known_limitations.py` reproduces this case
  against parent `a01cfdcdd6a4b7907abe53d06b8ce24ec0abfeee`; it remains unfixed
  within this review's R2/R3 behavior scope. Do not treat the expected failure as
  a passed acceptance criterion. **37/40** original tasks are currently checked.
- The historical “only accelerator gates remain” statements above described the
  earlier review and are superseded by this correction and the follow-up audit.
  VC0.03 and VC8.04 still need supported-accelerator evidence. CPU/listening
  results remain recorded evidence from 2026-11-19, not re-measured here.
