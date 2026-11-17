# PDF2Audiobook — Test Coverage TODO, Round 3

**Status:** In progress. Phases TC0–TC5 are worked; six items are open and need a decision or a push (TC1.06, TC3.02, TC3.03, TC3.05, TC4.05, TC5.03), see the Notes and "Found while testing". Scope and requirements: `docs/PDF2AUDIOBOOK_TEST_COVERAGE_3_SPEC.md` (R1–R7).
**Date:** 2026-11-17
**Baseline:** master head 5bbe03e (branch `tauri`), 95% statement coverage, 2612 passed, 4 skipped.
**Specification:** `docs/PDF2AUDIOBOOK_TEST_COVERAGE_3_SPEC.md`

## Working rules

- Work in the order below. Check an item only when its tests exist, pass on the head, and (for R1–R4) have a recorded mutation result (spec R6). Check a parent only when all its subitems are checked.
- Tests only: no file under `src/` changes. A test that exposes a defect is marked `xfail(strict=True)` and the defect goes in "Found while testing".
- Every error-path test asserts the fixed message (or exit code and JSON error) and that no path, file name, book text or OS error text appears.
- Stand-ins for model libraries and filesystem faults are installed per test with `monkeypatch` or `sys.modules`; nothing is installed globally.
- One area per commit: `test(<scope>): cover <area>`, no body, no `Co-Authored-By` trailer. Run `ruff check`, `ruff format --check`, mypy on 3.11–3.13 and the full pytest suite before each commit.
- After CI finishes, add a ledger row in a separate `docs:` commit with the full SHA and the real run ID, to this file and to `docs/PDF2AUDIOBOOK_TODO.md`. The ledgers are append-only.

## Phase TC0 — Baseline

- [x] TC0.01 Record the baseline coverage of every target module in spec §2 (statements missed / total) with the coverage command, at 5bbe03e.
  - Evidence: run at 5bbe03e (the tree was clean apart from untracked docs) with `pytest --cov=pdf2audiobook --cov-report=term-missing`: 10,201 statements, 483 missed, 95% overall. Target modules, statements missed / total: `verification/backends.py` 73 / 196; `llm/__init__.py` 7 / 182; `audio/commit.py` 7 / 96; `conversion.py` 20 / 311; `cli/verify.py` 17 / 157; `cli/batch.py` 11 / 92; `cli/repair.py` 7 / 44; `cli/asr.py` 8 / 48. Partial-branch counts were not measured (spec §2 says statements only).

## Phase TC1 — Recognizer backends (R1)

- [x] TC1.01 Offline stand-ins for `whisper`, `transformers` (Wav2Vec2) and `vosk`, installed per test, that return fixed words and times.
  - Test: a stand-in model that reports a fixed word list for each window; no test imports the real library.
  - Evidence: `tests/test_verification_backends_offline.py` installs stand-ins for `whisper`, `torch`, `transformers` and `vosk` in `sys.modules` per test (`_install_whisper`, `_install_transformers`, `_install_vosk`, `_install_torch`); none of the eleven checks loads a real library or weights.
- [x] TC1.02 Whisper: a word at position *t* in a window starting at offset *o* is reported at *o + t* for the second and later windows (lines 156–157, 161–166).
  - Evidence: `test_whisper_reports_each_window_at_its_offset` (65 s of audio, at least three windows, one word per window; start and end times match offset + local time). Passes on the head.
- [x] TC1.03 Wav2Vec2: frame offsets are converted with `inputs_to_logits_ratio / RATE` and shifted by the window offset (lines 245–261, 264–286).
  - Evidence: `test_wav2vec2_adds_each_window_offset_to_frame_times` (frames 10–15 at 320 samples per frame, every window); `test_wav2vec2_loads_from_the_folder_without_the_network` (both loads use `local_files_only`). Passes on the head.
- [x] TC1.04 Vosk: word timestamps are read from the result and the stop check runs between blocks (lines 295–301, 304–321).
  - Evidence: `test_vosk_keeps_word_times_and_reads_the_model_it_was_given` (blocks of 8,000, 8,000 and 4,000 bytes; the model path ends with the pinned unpack folder); `test_vosk_stops_between_blocks` (`Cancelled` raised at the second block). Passes on the head.
- [x] TC1.05 Device selection (`auto` uses CUDA only when torch reports it), the thread limits, and `close()` releasing the model (lines 136, 181, 184, 188–193, 208–218, 332–333).
  - Evidence: `test_whisper_chooses_the_device_and_limits_threads` (three cases: auto with CUDA, auto without, and an explicit CPU choice; thread count and fp16 flag); `test_close_releases_the_model_and_the_gpu_cache` and `test_close_on_cpu_leaves_the_gpu_cache_alone`. Passes on the head.
- [ ] TC1.06 A model that fails to load raises the documented failure, and its message holds no path or library text.
  - Evidence: `test_a_model_that_fails_to_load_raises_a_content_free_error` is written as `xfail(strict=True)`. Run with `--runxfail` it fails as the defect predicts: the backend raises `RuntimeError: cannot read weights at <path>` unchanged, not an `AudioError`. See "Found while testing".
  - Note: not met, so unchecked. The run layer does turn a failing model into `model_failed` and keeps the path out of reports (`verification/run.py` `_listen`), but the backend itself lets the library's message through, which conflicts with the content-free rule in `CLAUDE.md`. Fixing it is a source change, outside this round's tests-only rule, so it needs a decision.
- [x] TC1.07 Mutation check (R6): drop the window offset in Whisper, then the Wav2Vec2 ratio, and show that TC1.02 and TC1.03 fail. Revert after each.
  - Evidence: on a scratch edit of `verification/backends.py`, each mutation was applied, the named test failed, and `git checkout` restored the file (no diff afterwards): Whisper offset dropped → `test_whisper_reports_each_window_at_its_offset` fails; Wav2Vec2 frame ratio dropped → `test_wav2vec2_adds_each_window_offset_to_frame_times` fails. A device mutation (always CPU) also fails `test_whisper_chooses_the_device_and_limits_threads`.

## Phase TC2 — LLM decision branches (R2)

- [x] TC2.01 A narration proposal equal to the source text is rejected with reason `no_change`, the block's text is unchanged, and the decision is recorded (lines 343–352).
  - Evidence: `test_a_narration_identical_to_its_source_is_rejected_as_no_change` (decision `narration` / `rejected` / `no_change`, no warning, source text unchanged). Passes on the head.
- [x] TC2.02 A classification below 0.75 confidence is rejected with reason `low_confidence` and a warning naming the block (lines 479–489).
  - Evidence: `test_a_classification_below_the_threshold_is_rejected_and_warned_about` (warning `LLM classification low confidence: b1`, decision `classification` / `rejected` / `low_confidence`); `test_a_classification_at_the_threshold_is_kept` (0.75 is accepted). Passes on the head.
- [x] TC2.03 Book text placed in the mocked response appears in neither the warnings nor the decision records.
  - Evidence: the same two tests place a secret string in the mocked `reason` field and the source text, and assert neither appears in the warnings or in the serialized decision records (`model_dump_json`). Passes on the head.
- [x] TC2.04 Mutation check (R6): invert the confidence comparison and make the no-change check always false; show TC2.01 and TC2.02 fail.
  - Evidence: on scratch edits of `llm/__init__.py` (restored with `git checkout`, no diff afterwards): inverting the classification threshold (`< 0.75` → `> 0.75`) fails `test_a_classification_below_the_threshold_is_rejected_and_warned_about`; disabling the no-change check fails `test_a_narration_identical_to_its_source_is_rejected_as_no_change`.

## Phase TC3 — Commit recovery and conversion faults (R3, R4)

- [x] TC3.01 A read-only audio folder during staging: the previous MP3 and sidecar are unchanged, and the error holds no path (`audio/commit.py` lines 48–49).
  - Evidence: `test_a_read_only_audio_folder_leaves_the_previous_audio` (folder chmod 0o500; the backup folder cannot be made; `AudioError` raised; previous MP3 and sidecar byte-identical; the path is absent from the message; the staged MP3 is removed). `test_the_backup_copies_the_previous_audio_when_a_hard_link_is_refused` covers lines 48–49, the copy fallback: the read-only test reaches the error path at the backup step, not those lines. Both pass on the head (skipped when run as root).
- [ ] TC3.02 A staged file removed before the rename: the commit fails safely and the previous audio stays (lines 119–120).
  - Evidence: `test_a_failed_publish_says_so_and_names_no_path` reaches lines 119–120 (the rename fails because the destination is a folder) and checks the fixed message and that no path appears. Passes on the head. The scenario the item describes, a staged MP3 removed before the rename, is a different path and fails the stated outcome: see `test_a_staged_mp3_that_vanishes_mid_commit_fails_and_keeps_the_old_sidecar` (strict xfail) and "Found while testing".
  - Note: not met, so unchecked. The commit reports success and publishes the new sidecar over the previous MP3. Fixing it changes `audio/commit.py`, which is outside this round's tests-only rule.
- [ ] TC3.03 A journal left behind by a stopped commit whose staged files are gone: recovery drops it and reports no commit finished (lines 138–139, 146).
  - Evidence: `test_recovery_skips_an_unreadable_journal_and_keeps_it` reaches lines 138–139 (a journal that can't be read is logged and kept; the count is 0). `test_recovery_removes_leftover_staged_files_and_folders` reaches line 146 (a stray folder inside `.staging` is removed). Both pass on the head.
  - Note: not met as written, so unchecked. A journal whose staged files are gone does not reach lines 138–139: `_finish` finds nothing to rename, returns normally, and recovery counts it as finished (checked directly: the function returns 1). The item's expected outcome ("reports no commit finished") therefore contradicts the code. Which outcome is right is a decision for the owner.
- [x] TC3.04 A TTS provider that cannot be created: the chapter is marked failed, its previous audio and sidecar are unchanged, and no staged file remains (`conversion.py` lines 475–478).
  - Evidence: `test_a_chapter_whose_voice_engine_cannot_start_keeps_its_audio` (a converted book, then `--chapter 2 --force` with `create_tts_provider` raising `AudioError`: non-zero exit, MP3 and sidecar byte-identical, no staged MP3, no path in the output). A measured run of the TC3 tests alone shows `conversion.py` lines 475–478 are no longer missing. Passes on the head.
- [ ] TC3.05 Mutation check (R6): skip the staged-file cleanup and show TC3.04 fails. Revert.
  - Evidence: on a scratch edit of `audio/commit.py` (`_cleanup_staged` made a no-op; `git checkout` restored it, no diff afterwards): `test_a_read_only_audio_folder_leaves_the_previous_audio` fails (the staged MP3 is left behind). `test_a_chapter_whose_voice_engine_cannot_start_keeps_its_audio` still passes, because no staged MP3 exists yet when the provider fails to start.
  - Note: not met as written, so unchecked. The mutation is caught by TC3.01, not TC3.04. TC3.04 can't fail this way, since the provider fails before anything is staged.

## Phase TC4 — CLI refusals (R5)

- [x] TC4.01 `asr`: unknown model name and declined download (`cli/asr.py` lines 28–33, 69, 71).
  - Evidence: `test_asr_fetch_refuses_an_unknown_model_name` (non-zero exit; the input name is not echoed); `test_asr_fetch_declined_download_exits_1_and_downloads_nothing` (answer `n`: exit 1, no fetch); `test_asr_list_interrupted_exits_130_with_a_json_error` and `test_asr_fetch_interrupted_exits_130` (lines 28–29, 71); `test_asr_fetch_prints_the_list_when_nothing_needs_downloading` (line 69); `test_asr_list_failure_names_no_path` (lines 32–33). Passes on the head.
- [x] TC4.02 `regenerate-chapter` and `recover`: refused options and missing manifest (`cli/repair.py` lines 45, 58, 61, 63, 90, 93, 95).
  - Evidence: `test_regenerate_chapter_refuses_an_unknown_footnote_policy` (line 45, exit 2, fixed wording); `test_regenerate_chapter_lists_its_backups_in_the_human_output` (line 58); `test_regenerate_chapter_passes_interrupts_and_exits_through` (lines 61, 63); `test_recover_lists_its_backups_in_the_human_output` (line 90); `test_recover_passes_interrupts_and_exits_through` (lines 93, 95); `test_regenerate_chapter_refuses_a_missing_manifest` and `test_recover_refuses_a_missing_manifest` (no path in output). Passes on the head.
- [x] TC4.03 `batch`: refused option combinations and a per-book failure reported without stopping the run (`cli/batch.py` lines 63, 70, 85, 91, 126–129, 136, 143, 159).
  - Evidence: `test_batch_refuses_a_source_that_is_not_a_folder` (line 63); `test_batch_refuses_a_folder_without_pdfs` (line 70); `test_batch_applies_the_provider_and_cover_options` (lines 85, 91); `test_batch_refuses_per_book_tts_settings_that_do_not_validate` (lines 126–129, a Piper voice that is not a number); `test_batch_interrupted_while_converting_exits_130` (line 136); `test_batch_interrupted_before_any_book_exits_130` (line 159); `test_batch_reports_a_failed_book_and_still_converts_the_next` (line 143: an OS failure on the first book, the second is still converted; no path in output). Passes on the head.
- [x] TC4.04 `verify-audio`: refusals and the report output branches (`cli/verify.py` lines 96, 127–136, 163, 165, 183, 293, 306, 308, 310).
  - Evidence: `test_verify_audio_passes_an_exit_code_through` (96); `test_audio_report_says_when_a_book_is_not_verified_yet` (127–128); `test_audio_report_shows_its_out_of_date_chapters` (130–132); `test_audio_report_show_passes_an_exit_code_through` (133–134); `test_audio_report_show_failure_names_no_path` (135–136); `test_audio_report_dismiss_confirms_in_the_human_output` (163); `test_audio_report_dismiss_passes_an_exit_code_through` (165); `test_the_convert_verify_hook_does_nothing_without_outputs` (183); `test_resynthesize_warns_when_a_chapter_voice_overrides_the_option` (293); `test_resynthesize_prints_the_verification_summary_in_the_human_output` (306); `test_resynthesize_passes_interrupts_and_exits_through` (308, 310); `test_verify_audio_interrupted_exits_130` (92–94). Passes on the head.
- [ ] TC4.05 Every test in TC4 asserts the exit code, the fixed message or JSON error, and that no path, file name or book title appears.
  - Evidence: 35 tests in `tests/test_cli_refusals.py`; every refusal, failure and human-output test asserts its wording or exit code and, for the failure tests, that the path marker and the temporary folder are absent.
  - Note: not met as written, so unchecked. Several tests assert only the exit code, because the command prints no message on that path: the interrupt and exit-passthrough tests (`test_*_interrupts_*`, `test_*_passes_an_exit_code_through`, `test_*_interrupted_*`, and `test_verify_audio_interrupted_exits_130`). Adding a JSON-error assertion to each would meet the item literally; that is a small follow-up, not done here.

## Phase TC5 — Acceptance

- [x] TC5.01 Re-run the coverage command and record each target's new statements missed / total, and the overall figure (R7). Name any target still short, with the reason.
  - Evidence: the same command as TC0.01 at the head after TC4 (commit e7cf441 plus the two factory and readiness tests): 10,201 statements, 353 missed, 97% overall (was 483 missed, 95%). Target modules, missed before → after: `verification/backends.py` 73 → 1 (line 136, an end-of-file guard that doesn't normally run); `llm/__init__.py` 7 → 2 (lines 170–171: a no-change rejection in `propose_llm_cleanup`, which is not one of the §2 targets); `audio/commit.py` 7 → 0; `conversion.py` 20 → 16 (the §2 line 475–478 is covered; the remaining lines are outside §2); `cli/verify.py` 17 → 0; `cli/batch.py` 11 → 1 (line 127, a re-raise of `typer.Exit` inside an exception handler); `cli/repair.py` 7 → 0; `cli/asr.py` 8 → 1 (line 31, the same re-raise). Partial-branch counts were not measured. Shortfalls: the single lines named above, all with the reasons given.
- [x] TC5.02 Full Python suite passes with the same skips as before (the opt-in smoke tests only); ruff, format and mypy on 3.11–3.13 are clean.
  - Evidence: at the head after TC4: `pytest -q -ra` → 2669 passed, 4 skipped (the same four opt-in smoke tests as before: `test_kitten_real_smoke.py`, three in `test_verification_backends.py`), 2 xfailed (the two defects in "Found while testing"). `ruff check .` and `ruff format --check .` clean. mypy clean on 3.12 and 3.13 (and 3.11 in the earlier checks of this round). Mypy on 3.11 was not repeated after the last test additions; tests are outside mypy's file list.
- [ ] TC5.03 CI passes on the final commit; ledger rows added to this file and to `docs/PDF2AUDIOBOOK_TODO.md` with the full SHA and run IDs.
  - Evidence: not run yet.
  - Note: blocked. CI runs only after a push, and this loop doesn't push without being asked. Once the user says to push, CI can be read with `gh api` and the ledger rows written in a separate `docs:` commit.

## Found while testing

- **TC3.02, a vanished staged MP3 publishes the new sidecar.** `commit_chapter_audio` (`audio/commit.py`, `_finish`) skips the MP3 rename when the staged MP3 is missing, but still renames the staged sidecar. The commit then returns success, with the previous MP3 and the sidecar of audio that was never published. The stale check would flag the mismatch, but the module's own promise ("never left with an MP3 and a sidecar that don't belong together") does not hold. Test: `test_a_staged_mp3_that_vanishes_mid_commit_fails_and_keeps_the_old_sidecar` (strict xfail). The fix is a source change for the owner to decide.
- **TC1.06, backend load errors are not content-free.** `WhisperBackend._load` (`verification/backends.py`) lets the library's load exception through unchanged. With a message that includes the weights path, the path reaches the caller (`RuntimeError: cannot read weights at <path>`). The run layer masks it in reports, but the backend's error does not meet `CLAUDE.md`'s content-free rule. Test: `test_a_model_that_fails_to_load_raises_a_content_free_error` (xfail, strict). The fix (wrap load errors in `AudioError` with fixed text) is a source change, not a test change, so it is for the owner to decide.
