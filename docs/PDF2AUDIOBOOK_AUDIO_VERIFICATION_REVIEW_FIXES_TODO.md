# Audio Verification Review Fixes TODO

**Status:** Complete: all items done; the CI notes below record one flaky AppImage step and two earlier failed attempts. Scope and acceptance criteria: `docs/PDF2AUDIOBOOK_AUDIO_VERIFICATION_REVIEW_FIXES_SPEC.md`.

## AVF1 — Enforce exact narration references

- [x] AVF1.01 Choose and document behavior for a non-exact reference: mark stale/unavailable with a reason, or retrieve the exact historical synthesis reference when safely available.
  - Evidence: chose the stale/unavailable branch, not historical recovery (the ledger proves what
    was spoken per chunk, but recovering it would mean re-deriving text the chapter file no longer
    holds). New reason `narration_not_spoken` (contracts, both schemas, UI, CLI text); spec §15;
    README. Commit 59afafa.
- [x] AVF1.02 Enforce `Reference.exact` before transcript comparison; do not vote against changed narration text.
  - Evidence: `verify_book` (run.py) gives every chapter with `Reference.exact` false the result
    `verification_unavailable`/`narration_not_spoken` before any model is run; `stale_chapters`
    treats it as stale. `test_changed_pronunciations_are_not_compared_with_the_audio` asserts no
    backend heard the chapter. Commit 59afafa.
- [x] AVF1.03 Add regression tests for changed pronunciation/settings, stale ledger, and normal exact-reference verification.
  - Evidence:
    `tests/test_verify_audio_cli.py::test_changed_pronunciations_are_not_compared_with_the_audio`
    (changed pronunciation: not compared, chapter 1 still verified, original settings verify again);
    existing `tests/test_verification_reference.py` ledger tests
    (`test_changed_pronunciations_are_no_longer_exact`, `test_the_ledger_is_what_proves_exactness`).
    Commit 59afafa.
- [x] AVF1.04 Verify CLI JSON, human output, and desktop UI explain a skipped comparison accurately.
  - Evidence: CLI JSON reason `narration_not_spoken`; human text "so it wasn't compared; speak the
    chapter again first" (`report.py`, asserted in the same test); desktop `AudioCheck.test.tsx`
    "explains a chapter that wasn't compared because its narration changed" (17 tests in the file
    pass). Commits 59afafa, 6487185.

## AVF2 — Honor transcript-retention choice across partial reports

- [x] AVF2.01 Define the merge rule: without current `--keep-transcripts`, remove full transcripts from every chapter in the rewritten report, including unselected chapters.
  - Evidence: `run.py` removes `transcripts` from every chapter of the written report unless this
    run has `--keep-transcripts`, including chapters it didn't verify (`without_transcripts`).
    `test_a_partial_run_without_retention_removes_earlier_transcripts`. Commit 9dff47b.
- [x] AVF2.02 Ensure the report-level retention field reflects all stored chapter data; retain only allowed excerpts and vote metadata.
  - Evidence: report `keep_transcripts` is now `retains_transcripts(chapters)` (true only while some
    chapter holds transcripts), not the run's flag; excerpts and vote metadata are kept (asserted:
    chapter 2 keeps `status` and is without transcripts). Commit 9dff47b.
- [x] AVF2.03 Add tests for full-retention followed by partial non-retaining verification, JSON serialization, and explicit retention.
  - Evidence: `test_a_partial_run_without_retention_removes_earlier_transcripts` and
    `test_explicit_retention_still_keeps_transcripts_and_reads_never_show_them` (both serialized-
    text checks, counting the `"transcripts"` key in the file and the output). Both fail on the
    previous `run.py`/`report.py` and pass now (checked by swapping the files). Commit 9dff47b.
- [x] AVF2.04 Confirm desktop report access and atomic report writes preserve the same privacy rule.
  - Evidence: the desktop never opens `reports/audio_verification.json` (grep of `desktop/src-tauri`
    and `desktop/src`: only `audio-report show` through the CLI); `saved_report` (used by reads)
    strips transcripts, `mark_reviewed` rewrites the file as it is, and every write goes through
    `write_json`/`atomic_write`. Commit 9dff47b.

## AVF3 — Prevent transitive consensus clusters

- [x] AVF3.01 Specify a deterministic anchored or bounded-span clustering rule and positional tolerance.
  - Evidence: rule written in `compare.vote`'s docstring and in README and spec §15: differences in
    position order; a difference joins a group only if within `SLACK_WORDS` (2) of the group's first
    difference; two model families make a confirmed flag; ties by model order. Commit c39f5c7.
- [x] AVF3.02 Update difference grouping so a bridging third model cannot join separate model findings into a false majority.
  - Evidence: `compare.vote` groups against the anchor (`group[0]`) instead of any member, so a
    bridging difference can't join two separate findings. Commit c39f5c7.
- [x] AVF3.03 Add chain-proximity regression coverage (including positions 0, 2, and 4), plus positive co-located consensus and one-model disagreement cases.
  - Evidence: `tests/test_verification_compare.py`:
    `test_a_chain_of_nearby_differences_does_not_become_one_consensus` (positions 0, 2, 4: no three-
    model flag; the one at 4 stands alone),
    `test_a_bridging_third_model_cannot_manufacture_a_majority`,
    `test_co_located_differences_from_two_families_still_confirm`,
    `test_one_model_alone_never_confirms_...`,
    `test_the_same_differences_give_the_same_flags_in_any_order`. The two chain tests fail on the
    previous `compare.py`. Commit c39f5c7.
- [x] AVF3.04 Re-run comparison fixtures and the planted-anomaly benchmark; document any changed outcomes or threshold adjustments.
  - Evidence: the planted-anomaly benchmark was re-run on CPU (the GPU was held by a process outside
    this session, so Whisper ran on CPU): 23 Kitten cases, 399.8 s of audio, transcripts from the
    three models, scored with the old and new voting on the same transcripts. Planted edits caught
    11/11 both ways; clean-case confirmed flags 1 both ways (not investigated); one-model
    differences 9 old vs 10 new at the default settings (min_words 2, slack 2): the new rule no
    longer merges a difference into a group through a chain. No thresholds changed. The case set
    differs from the 32 cases of spec §13 (its transcripts were lost when the scratchpad was
    cleared), so the 18/18 figure is not comparable. Whisper ran at RTF 4.27 on CPU (1,706 s),
    wav2vec2 0.037, vosk 0.261.

## AVF4 — Bound memory during audio decode

- [x] AVF4.01 Define a maximum decoder window, overlap, and expected peak audio-buffer memory independent of chapter duration.
  - Evidence: `backends.py`: 30 s maximum window, 5 s search before each cut, 1 s read block; the
    buffer holds at most one window (measured 480,000 samples, 1.92 MB) at 2, 10 and 30 minutes;
    traced peak allocation about 5.5 MB regardless of length. Documented in README ("Memory") and
    spec §15. Commit 81e5973.
- [x] AVF4.02 Stream decoded/resampled samples into ASR windows without loading the entire chapter into memory.
  - Evidence: `iter_windows` reads the decoded WAV in blocks and yields windows as it goes;
    `windows()` and the streaming path share `_cut`;
    `test_streaming_windows_are_the_same_as_the_whole_file_split` (same split points and same
    samples). Whisper and wav2vec2 use it through `_windows`, Vosk reads blocks directly. Commit
    81e5973.
- [x] AVF4.03 Preserve timestamps, cancellation responsiveness, error handling, and cleanup of temporary files/buffers.
  - Evidence: window start offsets are checked (`test_streaming...`, and the existing timestamp
    tests); cancellation is checked between windows and the generator closes the file
    (`test_stopping_early_releases_the_decoded_file` counts open file descriptors);
    `test_stopping_removes_the_decoded_scratch_audio` (exit 130, scratch folder empty); decode
    failures are per chapter (`test_an_undecodable_chapter_is_reported_and_the_audio_is_left_alone`:
    the MP3 bytes are unchanged). Commit 81e5973.
- [x] AVF4.04 Add long synthetic-audio tests that assert bounded chunk sizes and verify cancellation cleanup.
  - Evidence: `test_the_buffer_does_not_grow_with_the_chapter` (2 min and 10 min give the same
    peak), `test_peak_allocations_stay_small_for_a_long_chapter` (tracemalloc, 10 min of audio),
    `test_stopping_early_releases_the_decoded_file`,
    `test_stopping_removes_the_decoded_scratch_audio`. Commit 81e5973.
- [x] AVF4.05 Document practical resource behavior and any FFmpeg format limitations.
  - Evidence: README "Memory" paragraph: the audio held at once is about 1.9 MB; the decoded 16 kHz
    WAV is kept in a temporary folder during the check (about 32 KB per second of audio) and removed
    afterwards; FFmpeg limits: a chapter it can't decode is `audio_undecodable`, and without FFmpeg
    the report has `ffmpeg_missing` and every chapter is `audio_undecodable`
    (`test_a_missing_ffmpeg_is_said_once_and_no_chapter_is_listened_to`). Commits 81e5973, 6487185,
    f57e1a7.

## AVF5 — Integration and acceptance

- [x] AVF5.01 Update audio verification docs and report/UI contracts for changed stale-reference or retention behavior.
  - Evidence: README (reasons, transcript retention, memory), spec §15 (behavior and report
    migration), desktop README (not-compared and undecodable chapters), MAINTAINER_GUIDE (where the
    rules live); both report schemas list `narration_not_spoken` and `audio_undecodable`;
    `test_desktop_contracts.py` and `test_verification_contracts.py` pass. Commits 59afafa, 81e5973,
    f57e1a7.
- [x] AVF5.02 Run focused Python tests for AVF1–AVF4, then the full Python suite.
  - Evidence: focused tests for AVF1–AVF4 (`test_verify_audio_cli.py`, `test_verification_*.py`,
    `test_resynthesize.py`) pass; full Python suite on the current head state: 2612 passed, 4
    skipped (the skips are the opt-in real-model smoke tests); ruff and format clean; mypy clean on
    3.12 (and on 3.11 and 3.13 in CI, where Python CI #886 passed).
- [x] AVF5.03 Run relevant desktop contract/UI tests and confirm report privacy and status rendering.
  - Evidence: desktop `npm run lint`, `npm run typecheck`, `npx vitest run` (351 tests, including
    the AudioCheck reason and retention-related display tests), `cargo fmt --check`, `cargo clippy
    -- -D warnings`, `cargo test` (110 unit tests, 7 fixture tests), and the `privacy.rs` test that
    verification excerpts never reach the app log. Desktop CI #43 passed.
- [x] AVF5.04 Confirm normal conversion remains opt-in and does not load ASR backends or fetch models.
  - Evidence: `test_ordinary_and_dry_run_conversions_load_no_asr_library` (convert, `--dry-run`,
    `--force`: no ASR module imported, no download) and `test_show_imports_no_asr_library`; both in
    the full suite. The fixes add no code to conversion.
- [x] AVF5.05 Review the final diff for report compatibility, migration notes, and complete acceptance evidence; update this TODO's status and evidence.
  - Evidence: diff reviewed for report compatibility: `schema_version` stays 1; added enum values
    and an optional `warnings` code only; reads hide transcripts on old reports; migration notes in
    spec §15 and README "Transcript retention". CI at f57e1a7: Python CI #888 and Desktop CI #43
    passed (both walkthroughs).

## Progress ledger

| Commit | Items | Change | CI |
| --- | --- | --- | --- |
| 59afafa | AVF1.01-AVF1.04 | narration not spoken, not compared | Python CI #883 [43939533372](https://github.com/ekkus93/pdf2audiobook/actions/runs/43939533372) success; Desktop CI #38 [43939533343](https://github.com/ekkus93/pdf2audiobook/actions/runs/43939533343) success |
| 9dff47b | AVF2.01-AVF2.04 | transcript retention across partial runs | Python CI #884 [43939732301](https://github.com/ekkus93/pdf2audiobook/actions/runs/43939732301) failure (mypy: shadowed `chapters` in run.py, fixed in 81e5973); Desktop CI #39 [43939732452](https://github.com/ekkus93/pdf2audiobook/actions/runs/43939732452) failure (same mypy error in its Python step) |
| c39f5c7 | AVF3.01-AVF3.04 | anchored consensus | Python CI #885 [43940203586](https://github.com/ekkus93/pdf2audiobook/actions/runs/43940203586) failure (same mypy error, fixed in 81e5973); Desktop CI #40 [43940203560](https://github.com/ekkus93/pdf2audiobook/actions/runs/43940203560) failure (same cause) |
| 81e5973 | AVF4.01-AVF4.05 | bounded streaming decode, undecodable reports | Python CI #886 [43940604069](https://github.com/ekkus93/pdf2audiobook/actions/runs/43940604069) success; Desktop CI #41 [43940604152](https://github.com/ekkus93/pdf2audiobook/actions/runs/43940604152) success (both walkthroughs) |
| 6487185 | AVF1.04, AVF4.05 | clear human output | Python CI #887 [43940861913](https://github.com/ekkus93/pdf2audiobook/actions/runs/43940861913) success; Desktop CI #42 [43940861712](https://github.com/ekkus93/pdf2audiobook/actions/runs/43940861712) failure (AppImage walkthrough could not add the book through the file dialog: the same flaky step as Desktop CI #35) |
| f57e1a7 | AVF5.01-AVF5.05 | docs and final head | Python CI #888 [43940979565](https://github.com/ekkus93/pdf2audiobook/actions/runs/43940979565) success; Desktop CI #43 [43940979535](https://github.com/ekkus93/pdf2audiobook/actions/runs/43940979535) success (both walkthroughs) |
