# Audio Verification TODO

**Status:** Complete: AV0–AV6 done (see the notes on AV2.05 and AV6.02 for what was not run). Scope and acceptance criteria: `docs/PDF2AUDIOBOOK_AUDIO_VERIFICATION_SPEC.md`.

## AV0 — Baseline and decisions

- [x] AV0.01 Record the current `convert --chapter N --force` behavior: output replacement, sidecar invalidation, backup behavior, interruption behavior, and JSON/progress contracts.
  - Evidence: Recorded in spec §11 from `conversion.py`, `audio/encoding.py` and
    `audio/freshness.py`, and checked with real Kitten runs on a copy of the converted Harbour
    demo book. A forced `--chapter 2` run replaced the MP3 (sha256 `63dbcbab2959` to
    `a6fbf266bd91`) and sidecar in place, with no backup and no temporary files left. A forced
    `--chapter 10` run sent SIGTERM at 291 of 1,427 characters exited 130 with the `Interrupted`
    JSON error, left the MP3 and sidecar byte-identical (`396b68a424fc`, `fe3d8651508a`),
    `run_status.json` `stopped`, and no temporary WAV. Gaps for AV4 listed in §11.
- [x] AV0.02 Decide report retention, default warning behavior, supported model revisions, language scope, and model-download UX; record decisions in the spec.
  - Evidence: Spec §12, taken from §10's recommendations and open to the owner: flagged
    excerpts only unless `--keep-transcripts`; `convert --verify-audio` finishes and warns,
    `verify-audio` exits 0 when it ran; pinned models (Whisper `medium.en` via
    `openai-whisper==20250625` and its SHA-256-bearing URL, `facebook/wav2vec2-base-960h` at
    `22aad52d435eb6dbaf354bdad9b0da84ce7d6156` from the Hugging Face API, Vosk
    `en-us-0.22-lgraph` 130,557,655 bytes by HEAD request); extras `asr-whisper`, `asr-wav2vec2`,
    `asr-vosk`, `asr` (all resolve on Python 3.11 and 3.13 with `uv pip compile`; `torch` is
    already pulled in by `kitten`); English only, judged from the TTS voice; explicit
    `asr list` / `asr fetch` with confirmation. Note: the Vosk archive's SHA-256 is pinned in
    AV0.03 after downloading it.
- [x] AV0.03 Benchmark the three ASR families on generated chapter audio and define normalization, alignment, mismatch thresholds, resource limits, and cancellation expectations.
  - Evidence: Spec §13. `scripts/asr_benchmark.py` (`make`, `run`, `score`) made 32 Kitten
    cases (1,027 s) from the demo books with planted insertions, omissions and substitutions,
    noise at 10 and 0 dB, numbers and a short title; ran Whisper `medium.en`, Wav2Vec2 and Vosk
    on GPU and CPU with the pinned weights (downloaded and checked: Whisper by its SHA-256,
    Vosk archive SHA-256 `d9838b4aaa82a75c4a17f5aca300eaca129aaab2a7cbf951bafbb500eb9c4334`);
    and scored with the production core (`verification/compare.py`, eb6db7b). Real-time
    factors GPU/CPU: Whisper 0.043/0.771 (7.1 GB on CPU), Wav2Vec2 0.001/0.037, Vosk 0.196.
    Chosen rules confirmed 18/18 planted edits with one other confirmed flag, a real Kitten
    misreading of "1,250" heard by all three models; 10 one-model differences. Note: real
    accented or recorded speech was not tested (Kitten voices stand in); the cancellation
    latencies are expectations from the measured speeds, tested in AV3.05.

## AV1 — Shared contracts and comparison core

- [x] AV1.01 Define typed ASR backend, model readiness, transcript segment, alignment, vote, and chapter-result contracts.
  - Evidence: `verification/contracts.py` (`AsrBackend` protocol, `Readiness`, `Word`/`Transcript`,
    `Difference`, `Flag` with votes, `ModelRun`, `ChapterResult`, status and reason enums);
    `tests/test_verification_contracts.py` (6). Commits eb6db7b, bd22b67; Python CI #863/#865 and
    Desktop CI #18/#20 passed.
- [x] AV1.02 Implement safe narration-reference selection that matches the exact text and pronunciation transforms sent to TTS.
  - Evidence: `verification/reference.py` builds the reference from the same `_chunk_plan` the TTS
    step speaks (voice markers, citation masking, pronunciations) and calls it exact only when every
    chunk's text SHA-256 matches the synthesis ledger; `tests/test_verification_reference.py` (8:
    what was spoken, changed text, missing audio, replaced MP3, changed pronunciations, symlinked
    MP3, non-English Piper voice, ledger exactness). Commit bd22b67; Python CI #865 passed.
- [x] AV1.03 Implement normalization, word/phrase alignment, timestamps, and 2-of-3 family voting; missing/failed models abstain.
  - Evidence: `verification/compare.py`: normalization (case, punctuation, British/American
    spelling, compounds, number values incl. years, decimals and split digits), word alignment with
    timestamps, 2-of-3 voting and `chapter_outcome`; failed or missing models abstain and mark the
    result partial. Commit eb6db7b; Python CI #863 passed.
- [x] AV1.04 Add deterministic tests for matching speech, a two-model insertion, one-model hallucination, omission, substitution, disagreement, short clips, number normalization, and timestamp bounds.
  - Evidence: `tests/test_verification_compare.py` (19): matching speech, two-model insertion, one-
    model hallucination, omission with its time, phrase substitution, one-word number substitution,
    number values, split numbers, short clips, timestamp bounds, abstaining and disagreeing models.
    Thresholds were checked on the AV0.03 benchmark (18/18 planted edits). Commit eb6db7b; Python CI
    #863 passed.
- [x] AV1.05 Define and test versioned JSON schemas for model readiness and verification results.
  - Evidence: `desktop/contracts/asr-models.schema.json` and `audio-verification.schema.json`
    (`schema_version` 1) with fixtures; `tests/test_verification_contracts.py` validates serializer
    output and checks the schemas list every status, reason and model;
    `tests/test_desktop_contracts.py` and the Rust contract test cover both (RESULTS 16). Commit
    bd22b67; Python CI #865 and Desktop CI #20 passed.

## AV2 — Optional CLI model support

- [x] AV2.01 Add isolated optional dependency groups for Whisper `medium.en`, Wav2Vec2, and Vosk/Kaldi; keep default installs unchanged.
  - Evidence: `pyproject.toml` extras `asr-whisper`, `asr-wav2vec2`, `asr-vosk` and `asr`; `uv.lock`
    gained only additions. `tests/test_verification_optional.py` (3) checks each extra, that the
    default install has no ASR package, and that importing the CLI loads no ASR library. Commit
    d33e005; Python CI #866 passed on 3.11–3.13 and the clean-venv wheel smoke.
- [x] AV2.02 Add CLI model-list/readiness and explicit model-fetch commands with pinned revisions, integrity checks, cache-location output, and no implicit downloads.
  - Evidence: `asr list [--json]` and `asr fetch MODEL... [--yes] [--json]`
    (`verification/models.py`): pinned URL, size and SHA-256 per file, `.part` download then rename,
    stamp file, checked Vosk unpack with traversal refusal, location from `PDF2AUDIOBOOK_ASR_DIR` or
    the XDG cache; confirmation unless `--yes`, `--json` needs `--yes`.
    `tests/test_verification_models.py` (13) incl. wrong checksum, oversized download, content-free
    network failure, escaping archive, listing never downloads. A real `asr fetch all --yes` took
    29.5 s. Commit 56aa81f; Python CI #867 passed.
- [x] AV2.03 Implement local inference adapters behind the common backend interface; add model identity/version reporting, resource bounds, and graceful unavailable results.
  - Evidence: `verification/backends.py`: Whisper, Wav2Vec2 and Vosk behind `AsrBackend`, ffmpeg
    decode to 16 kHz mono, 30 s windows cut at the quietest point, thread caps, stop checks between
    windows, third-party stdout silenced; readiness reports model id, revision, package version,
    weights and size; a missing package or weights gives an unavailable result. Commit fda1183;
    Python CI #868 passed.
- [x] AV2.04 Add offline/fake-backend tests plus opt-in integration smoke tests for each installed backend.
  - Evidence: `tests/test_verification_backends.py` (7 offline: windows, decode, offsets, stop
    requests, readiness without imports) plus 3 opt-in smoke tests with `PDF2AUDIOBOOK_ASR_SMOKE=1`,
    which passed locally for all three installed backends on Kitten speech;
    `tests/test_verify_audio_cli.py` uses a fake backend. Commits fda1183, 2af7a65; Python CI
    #868/#870 passed (smoke tests skipped there by design).
- [x] AV2.05 Document model licenses, disk/RAM/CPU costs, supported OS/Python combinations, and explicit network behavior for downloads.
  - Evidence: README "Installing the speech recognizers": licenses (MIT, Apache-2.0), download
    sizes, disk, RAM and CPU/GPU speeds from spec §13, Python 3.11–3.13 on Linux/macOS/Windows, and
    that only `asr fetch` uses the network. Commit 7159805; Python CI #869 passed. Note: only Linux
    was run; macOS and Windows support is from the packages' published wheels.

## AV3 — CLI verification and reports

- [x] AV3.01 Add `verify-audio MANIFEST` with chapter/range/model selection, progress, cancellation, human summary, and stable `--json` output.
  - Evidence: `verify-audio MANIFEST` with `--chapter` (repeatable), `--chapter-range`, `--models`,
    `--device`, progress, Ctrl+C (exit 130 keeping finished chapters), human summary and `--json`
    following the schema. `tests/test_verify_audio_cli.py`. A real run on the 13-chapter Harbour
    demo took 3 minutes. Commit 2af7a65; Python CI #870 passed.
- [x] AV3.02 Verify audio hashes, chapter artifact state, source text hashes, safe workspace paths, and stale/missing audio before inference.
  - Evidence: before inference each chapter's MP3 must be a regular file inside `audio/` (no
    symlinked file or folder) whose SHA-256 and size match its sidecar and whose text matches the
    chapter file; otherwise `audio_missing` or `audio_stale` without loading a model. Tests:
    `test_a_symlinked_mp3_is_not_read`,
    `test_an_audio_folder_linked_outside_the_workspace_is_not_read`,
    `test_a_chapter_title_cannot_lead_outside_the_audio_folder`, reference tests. Commits 2af7a65,
    f03889e.
- [x] AV3.03 Write the versioned report atomically; follow the spec's transcript-retention decision and exclude content from logs/errors.
  - Evidence: `reports/audio_verification.json` written atomically (schema 1), merged with earlier
    chapters; only flagged excerpts unless `--keep-transcripts` (§12); errors and logs are content-
    free. Tests `test_transcripts_are_kept_only_on_request`,
    `test_human_output_keeps_book_text_out_unless_asked`,
    `test_a_malformed_report_is_replaced_and_others_are_kept`. Commit 2af7a65; Python CI #870
    passed.
- [x] AV3.04 Add opt-in `convert --verify-audio`; ensure ordinary and dry-run conversions do not load ASR packages or fetch models.
  - Evidence: `convert --verify-audio` checks only the chapters converted, adds `audio_verification`
    and the `audio_possible_mismatch` warning, refuses `--dry-run`.
    `test_ordinary_and_dry_run_conversions_load_no_asr_library` runs both in a subprocess and
    asserts no ASR module is imported and no network is opened. Commit 423d47b; Python CI #871
    passed.
- [x] AV3.05 Add CLI contract, privacy marker, path traversal, symlink, cancellation, malformed report, and stale-report tests.
  - Evidence: `tests/test_verify_audio_cli.py` (16): schema contract, privacy (book text only with
    `--details`), symlinked MP3, audio folder linked outside the workspace, chapter title with
    `../`, cancellation, malformed report, stale report, unknown chapters and ranges. The outside-
    folder test failed before f03889e (a symlinked `audio/` was read) and passes after. Commits
    2af7a65, f03889e.
- [x] AV3.06 Document CLI setup, verify-existing and verify-after-convert examples, JSON fields, interpretation, and limitations.
  - Evidence: README "Checking a converted book" with verify-existing and verify-after-convert
    examples, the JSON fields, how to read each status and the limits of ASR evidence;
    MAINTAINER_GUIDE contract bullet. Commit 2ebeb44; Python CI #872 passed.

## AV4 — Safe chapter repair

- [x] AV4.01 Audit and, if necessary, harden selected-chapter forced conversion so synthesis writes temporary MP3/sidecar files and atomically replaces valid output only after validation.
  - Evidence: hardened. Every chapter MP3 is now encoded to `audio/.staging/`, and `audio/commit.py`
    writes the new sidecar beside it, then a journal, then renames both into place; conversion first
    finishes a journaled commit and removes unjournaled staged files and leftover `tmp*` folders
    (the AV0.01 gaps). `tests/test_chapter_audio_commit.py` (8); 5 of them fail against the previous
    conversion code. Commit 5b58072; Python CI #873 and Desktop CI #28 passed.
- [x] AV4.02 Preserve recoverable backups of prior audio and metadata; test failed synthesis, cancellation, disk-full, and interrupted commit behavior.
  - Evidence: the previous MP3 and sidecar are linked into `audio/.backup/` (newest three per
    chapter, outside the chapter list and `pack-m4b`). Tests: failed synthesis, interrupted
    synthesis (exit 130), disk full while staging (content-free error), commit stopped after its
    journal and finished by the next run, stray staging cleanup, backup limit. Commit 5b58072;
    Python CI #873 passed.
- [x] AV4.03 Add a CLI action for targeted retry and document editing chapter narration/pronunciation before re-synthesis; keep text repair separate from `regenerate-chapter` artifact recovery.
  - Evidence: `resynthesize MANIFEST --chapter N [--voice] [--speed] [--cover]` speaks only the
    chosen chapters again from the analyzed book, through the safe commit, keeping the cover already
    in the MP3. README "Fixing a flagged chapter" covers listening, retrying with another voice,
    pronunciations and text edits, how to restore a backup, and that `regenerate-chapter` only
    rewrites chapter text files. `tests/test_resynthesize.py` (8). Commit 28ce7c8.
- [x] AV4.04 Re-run verification after repair and invalidate reports when chapter text, pronunciation inputs, model settings, or audio hashes change.
  - Evidence: after `resynthesize`, chapters verified before are verified again (`--no-verify-audio`
    skips; `--verify-audio` forces). `stale_chapters` reports a result stale when the chapter text,
    pronunciations (expected narration), audio hash or the ASR model revisions change. Tests
    `test_a_chapter_checked_before_is_checked_again_after_repair`,
    `test_a_repair_makes_the_old_result_stale`, `test_results_from_other_model_revisions_are_stale`,
    `test_results_go_stale_when_audio_or_narration_change`. Commit 28ce7c8. Note: "model settings"
    is taken as ASR model revisions plus TTS settings; a TTS voice or model change regenerates the
    audio, so its new hash makes the result stale.

## AV5 — Tauri desktop workflow

- [x] AV5.01 Add typed bridge requests and shared schemas for readiness, verification progress/results, cancel, and selected-chapter repair.
  - Evidence: bridge requests `asr_list`, `asr_fetch`, `verify_audio`, `audio_report`,
    `audio_dismiss`, `resynthesize` and `ConvertOptions.verify_audio` (`engine/request.rs`), with
    CLI commands `audio-report show`/`dismiss` added for the saved report and reviewed marks;
    verify, dismiss and resynthesize hold the book's one write slot. Contracts `audio-report`,
    `audio-dismiss` and `convert` (now with `audio_verification`, also `resynthesize`) with fixtures
    from real runs (spec §14); `contracts.rs` RESULTS 19; Rust tests `audio_verification_requests`,
    `audio_requests_refuse_empty_or_bad_values`,
    `audio_verification_writes_only_through_the_book_lock`. Commits cdea06b, 9ca2845 (no CI runs of
    their own; covered by 5880ed3: Python CI #877, Desktop CI #32 passed).
- [x] AV5.02 Add per-conversion opt-in and “Verify existing audio”; show model availability and route explicit setup/download through the CLI.
  - Evidence: the book options' *Check the new audio with speech recognition* switch (off by
    default, sends `verify_audio`) and *Audio check → Verify existing audio* (a run of its own on
    the Run page); the panel lists each recognizer's readiness and *Download recognizers…* shows
    sizes and folders, then runs `asr fetch --yes` through the CLI. Tests: `bookOptions.test.ts`,
    BookPage `checks the new audio only when that option is switched on`, AudioCheck download test.
    Commit 5880ed3; Desktop CI #32 passed.
- [x] AV5.03 Show chapter result, model votes, expected/transcribed excerpt, timestamp playback, stale state, and clear limits of ASR evidence.
  - Evidence: `AudioCheck.tsx` shows each chapter's verdict, reason, the recognizers that voted and
    partial results, each passage's kind, time, excerpt and what each model heard, confirmed vs one-
    model disagreements, out-of-date results and the limits of ASR evidence; *Listen* plays from 2 s
    before the passage (`Player.tsx` seek). Real-app walkthrough: the player started at 1.51 s
    (binary) and 1.72 s (AppImage) for a passage at 3.5 s (Desktop CI #36). Commits 5880ed3,
    ce0e558.
- [x] AV5.04 Add user-controlled listen/dismiss, retry with selected voice/speed, and edit-corrected-narration then regenerate actions; preserve the previous MP3 until replacement succeeds.
  - Evidence: *Sounds right* / *Not reviewed* (`audio-report dismiss`, changes no file; kept across
    re-verification of the same audio), *Speak again…* with voice and speed (`resynthesize`, re-
    verified, previous MP3 kept until replaced and then in `audio/.backup/`), *Correct the text*
    (opens the review page). Tests in `AudioCheck.test.tsx`, `test_verify_audio_cli.py` (dismiss),
    `test_resynthesize.py`, `test_chapter_audio_commit.py`. Commits cdea06b, 5880ed3.
- [x] AV5.05 Add frontend/Rust tests for opt-in defaults, unavailable models, partial votes, cancellation, stale results, privacy, playback seeking, and repair rollback.
  - Evidence: frontend tests (350 in all): opt-in default (`bookOptions.test.ts`, BookPage),
    unavailable and uninstalled models, partial votes, stale results, unreadable results, engine
    failures without book text (`AudioCheck.test.tsx`, 16), cancellation messages for verify and
    repair (`Run.test.tsx`), playback seeking (`Player.test.tsx`; fails on the previous player).
    Rust: request tests and `privacy::verification_excerpts_never_reach_the_app_log`. Repair
    rollback is tested at the CLI (`test_chapter_audio_commit.py`, `test_resynthesize.py`), which
    the app calls. Commits 9ca2845, 5880ed3.
- [x] AV5.06 Update desktop and main README documentation and add a deterministic end-to-end fixture covering a flagged passage and repair.
  - Evidence: desktop README "Checking the audio" and main README (desktop pointer, `audio-report`);
    `e2e/walkthrough.mjs` verifies, finds the flagged passage in chapter 2, listens, marks it
    reviewed and speaks the chapter again, with `e2e/fake_asr.mjs` answering from the real-output
    fixtures and `e2e/fixtures/silence.mp3`. It found that the AppImage crashed when a chapter
    played (no GStreamer audio sink), fixed by bundling GStreamer (ce0e558). Desktop CI #33/#34
    failed (NaN player time in the AppImage, then the crash), #35 failed at the file dialog step
    (flaky, before the audio check), #36 passed both walkthroughs. Commits e83ce3e, b48b9a2,
    ce0e558.

## AV6 — Acceptance

- [x] AV6.01 Run the full Python and desktop checks; verify default conversion stays offline from ASR and unchanged.
  - Evidence: at 187f50b, Python CI #881 and Desktop CI #36 passed (all Python checks on 3.11–3.13,
    frontend lint/types/350 tests/build, fmt/clippy/cargo test, AppImage and `.deb`, both
    walkthroughs); locally pytest 2597 passed, 4 skipped. Default conversion stays offline and
    unchanged: `test_ordinary_and_dry_run_conversions_load_no_asr_library` (convert, `--dry-run`,
    `--force`: no ASR module, no network), `test_the_default_install_has_no_asr_package`,
    `test_show_imports_no_asr_library`; `convert --json` without `--verify-audio` has no
    `audio_verification`.
- [x] AV6.02 Run the three-model local acceptance set: clean speech, a known insertion, a one-model false positive, and a repair; record versions, timings, and resource use.
  - Evidence: spec §14 (real models, GPU and CPU): clean book 11/13 chapters clean in 3 min 05 s,
    4.6 GB; one-model false positives (Vosk ch. 9 and 10, a Whisper hallucination) shown as
    disagreements; a spliced insertion confirmed by Wav2Vec2 and Vosk at 19.9 s; `resynthesize`
    repaired and re-verified it clean in 31.3 s with the old audio backed up; CPU-only chapter 85 s
    for 89 s of audio, 6.7 GB. Versions recorded there. Note: recorded or accented speech, non-
    English, macOS and Windows not run.
- [x] AV6.03 Review report privacy, model licenses, package/installer size impact, and supported-machine behavior before marking complete.
  - Evidence: spec §14 Review: report privacy (excerpts only by default, never in logs or errors,
    local only), licenses (MIT, Apache-2.0, BSD; nothing redistributed), size (default install
    unchanged; `asr` extra about 310 MB plus PyTorch; models 2.0 GB; desktop bundles no ASR,
    AppImage grew 82.1 → 93.2 MB for GStreamer), supported machines (GPU optional, low-memory
    warning, abstaining models, English only).

## Progress ledger

| Commit | Items | CI |
| --- | --- | --- |
| aa3b6f2f82a24528c6d85fbf9cebce994bc1dc82 | AV0.01 | Python CI #861 [43652330203](https://github.com/ekkus93/pdf2audiobook/actions/runs/43652330203) success; Desktop CI #16 [43652330208](https://github.com/ekkus93/pdf2audiobook/actions/runs/43652330208) success |
| 9d1bbf080a9a11f249d5444a9b91cd91e717b330 | AV0.02 | Python CI #862 [43652451452](https://github.com/ekkus93/pdf2audiobook/actions/runs/43652451452) success; Desktop CI #17 [43652451448](https://github.com/ekkus93/pdf2audiobook/actions/runs/43652451448) success |
| eb6db7bad2c8ed07e3e7306160c18317120754c6 | AV1.01, AV1.03, AV1.04 | Python CI #863 [43654800130](https://github.com/ekkus93/pdf2audiobook/actions/runs/43654800130) success; Desktop CI #18 [43654800175](https://github.com/ekkus93/pdf2audiobook/actions/runs/43654800175) success |
| bb5842886acff517f0cc6d76b5c27c60ed908904 | AV0.03 | Python CI #864 [43654851448](https://github.com/ekkus93/pdf2audiobook/actions/runs/43654851448) success; Desktop CI #19 [43654851449](https://github.com/ekkus93/pdf2audiobook/actions/runs/43654851449) success |
| bd22b67c9e51260c2a934e1c45757197860ce185 | AV1.02, AV1.05 | Python CI #865 [43655217657](https://github.com/ekkus93/pdf2audiobook/actions/runs/43655217657) success; Desktop CI #20 [43655217651](https://github.com/ekkus93/pdf2audiobook/actions/runs/43655217651) success |
| d33e0055089a887732a7c16e392909db07fe141f | AV2.01 | Python CI #866 [43655282779](https://github.com/ekkus93/pdf2audiobook/actions/runs/43655282779) success; Desktop CI #21 [43655282763](https://github.com/ekkus93/pdf2audiobook/actions/runs/43655282763) success |
| 56aa81fb2ce2e9225dec286cb8f9bbda04f4e9d6 | AV2.02 | Python CI #867 [43655688603](https://github.com/ekkus93/pdf2audiobook/actions/runs/43655688603) success; Desktop CI #22 [43655688582](https://github.com/ekkus93/pdf2audiobook/actions/runs/43655688582) success |
| fda1183dfb459e9a1cde70745198f78913dda70a | AV2.03, AV2.04 | Python CI #868 [43656048740](https://github.com/ekkus93/pdf2audiobook/actions/runs/43656048740) success; Desktop CI #23 [43656048759](https://github.com/ekkus93/pdf2audiobook/actions/runs/43656048759) success |
| 7159805ead5b86b2f72b8eb27c32fe3bedd51627 | AV2.05 | Python CI #869 [43656217910](https://github.com/ekkus93/pdf2audiobook/actions/runs/43656217910) success; Desktop CI #24 [43656218047](https://github.com/ekkus93/pdf2audiobook/actions/runs/43656218047) success |
| 2af7a653213efae9a2e5bb290dfb37d3ad11f20b | AV3.01-AV3.03, AV3.05 | Python CI #870 [43656894828](https://github.com/ekkus93/pdf2audiobook/actions/runs/43656894828) success; Desktop CI #25 [43656894812](https://github.com/ekkus93/pdf2audiobook/actions/runs/43656894812) success |
| 423d47b6d7a6262c40d6ff6839d661f38c7f3012 | AV3.04 | Python CI #871 [43657110588](https://github.com/ekkus93/pdf2audiobook/actions/runs/43657110588) success; Desktop CI #26 [43657110614](https://github.com/ekkus93/pdf2audiobook/actions/runs/43657110614) success |
| 2ebeb44ed0ca10061114565c946140454d83e0b2 | AV3.06 | Python CI #872 [43657154122](https://github.com/ekkus93/pdf2audiobook/actions/runs/43657154122) success; Desktop CI #27 [43657154099](https://github.com/ekkus93/pdf2audiobook/actions/runs/43657154099) success |
| 5b58072dfa8fd8f6dface7f3901af45f1bc5df09 | AV4.01, AV4.02 | Python CI #873 [43657885423](https://github.com/ekkus93/pdf2audiobook/actions/runs/43657885423) success; Desktop CI #28 [43657885380](https://github.com/ekkus93/pdf2audiobook/actions/runs/43657885380) success |
| 28ce7c86b9fbc65e0b12e76be74335a9e8272c4b | AV4.03, AV4.04 | Python CI #874 [43658498513](https://github.com/ekkus93/pdf2audiobook/actions/runs/43658498513) success; Desktop CI #29 [43658498503](https://github.com/ekkus93/pdf2audiobook/actions/runs/43658498503) success |
| f03889eb74c85d99015a678e3d0993471aa22f1c | AV3.02, AV3.05 | Python CI #875 [43658734433](https://github.com/ekkus93/pdf2audiobook/actions/runs/43658734433) success; Desktop CI #30 [43658734525](https://github.com/ekkus93/pdf2audiobook/actions/runs/43658734525) success |
| cdea06bc4e8f36b038b982732f7ba0fa2bf76534 | AV5.01, AV5.04 | no CI run of its own (pushed with 5880ed3) |
| 9ca2845d565cefdd78c769ff899c1f107f75f229 | AV5.01 | no CI run of its own (pushed with 5880ed3) |
| 5880ed3692d3b5c909880c5cc39ad3090bd3d377 | AV5.02-AV5.05 | Python CI #877 [43660833903](https://github.com/ekkus93/pdf2audiobook/actions/runs/43660833903) success; Desktop CI #32 [43660833929](https://github.com/ekkus93/pdf2audiobook/actions/runs/43660833929) success |
| e83ce3e7604865e64bcd01b2b07a47f64fffe0f5 | AV5.06 | Python CI #878 [43661473129](https://github.com/ekkus93/pdf2audiobook/actions/runs/43661473129) success; Desktop CI #33 [43661473127](https://github.com/ekkus93/pdf2audiobook/actions/runs/43661473127) failure (silent MP3 not committed: ignored by .gitignore) |
| b48b9a283dd35f880c726526e063c840606c769e | AV5.06 | Python CI #879 [43661495904](https://github.com/ekkus93/pdf2audiobook/actions/runs/43661495904) success; Desktop CI #34 [43661495870](https://github.com/ekkus93/pdf2audiobook/actions/runs/43661495870) failure (AppImage walkthrough: player time unreadable, AppImage page crashed on playback) |
| a3c03e8afb5c5dc5b2e36d3d2dd300a12797ff2b | AV6.01 | no CI run of its own (pushed with ce0e558) |
| 9ba09ecc157c15e8e745c88efc532b4725276089 | AV6.02, AV6.03 | no CI run of its own (pushed with ce0e558) |
| ce0e5580276fe9b1a96239d34ec195ef680c6044 | AV5.06 | Python CI #880 [43662600932](https://github.com/ekkus93/pdf2audiobook/actions/runs/43662600932) success; Desktop CI #35 [43662600940](https://github.com/ekkus93/pdf2audiobook/actions/runs/43662600940) failure (AppImage walkthrough could not add the book through the file dialog; flaky, before the audio check) |
| 187f50bf15b39798dafd74eea4c34ad21a56b6b2 | AV6.01 | Python CI #881 [43662616244](https://github.com/ekkus93/pdf2audiobook/actions/runs/43662616244) success; Desktop CI #36 [43662616168](https://github.com/ekkus93/pdf2audiobook/actions/runs/43662616168) success, both walkthroughs incl. AppImage playback |
