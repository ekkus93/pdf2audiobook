# PDF2Audiobook — Test Coverage TODO, Round 3

**Status:** Not started. Scope and requirements: `docs/PDF2AUDIOBOOK_TEST_COVERAGE_3_SPEC.md` (R1–R7).
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

- [ ] TC2.01 A narration proposal equal to the source text is rejected with reason `no_change`, the block's text is unchanged, and the decision is recorded (lines 343–352).
  - Evidence: not run yet.
- [ ] TC2.02 A classification below 0.75 confidence is rejected with reason `low_confidence` and a warning naming the block (lines 479–489).
  - Evidence: not run yet.
- [ ] TC2.03 Book text placed in the mocked response appears in neither the warnings nor the decision records.
  - Evidence: not run yet.
- [ ] TC2.04 Mutation check (R6): invert the confidence comparison and make the no-change check always false; show TC2.01 and TC2.02 fail.
  - Evidence: not run yet.

## Phase TC3 — Commit recovery and conversion faults (R3, R4)

- [ ] TC3.01 A read-only audio folder during staging: the previous MP3 and sidecar are unchanged, and the error holds no path (`audio/commit.py` lines 48–49).
  - Evidence: not run yet.
- [ ] TC3.02 A staged file removed before the rename: the commit fails safely and the previous audio stays (lines 119–120).
  - Evidence: not run yet.
- [ ] TC3.03 A journal left behind by a stopped commit whose staged files are gone: recovery drops it and reports no commit finished (lines 138–139, 146).
  - Evidence: not run yet.
- [ ] TC3.04 A TTS provider that cannot be created: the chapter is marked failed, its previous audio and sidecar are unchanged, and no staged file remains (`conversion.py` lines 475–478).
  - Evidence: not run yet.
- [ ] TC3.05 Mutation check (R6): skip the staged-file cleanup and show TC3.04 fails. Revert.
  - Evidence: not run yet.

## Phase TC4 — CLI refusals (R5)

- [ ] TC4.01 `asr`: unknown model name and declined download (`cli/asr.py` lines 28–33, 69, 71).
  - Evidence: not run yet.
- [ ] TC4.02 `regenerate-chapter` and `recover`: refused options and missing manifest (`cli/repair.py` lines 45, 58, 61, 63, 90, 93, 95).
  - Evidence: not run yet.
- [ ] TC4.03 `batch`: refused option combinations and a per-book failure reported without stopping the run (`cli/batch.py` lines 63, 70, 85, 91, 126–129, 136, 143, 159).
  - Evidence: not run yet.
- [ ] TC4.04 `verify-audio`: refusals and the report output branches (`cli/verify.py` lines 96, 127–136, 163, 165, 183, 293, 306, 308, 310).
  - Evidence: not run yet.
- [ ] TC4.05 Every test in TC4 asserts the exit code, the fixed message or JSON error, and that no path, file name or book title appears.
  - Evidence: not run yet.

## Phase TC5 — Acceptance

- [ ] TC5.01 Re-run the coverage command and record each target's new statements missed / total, and the overall figure (R7). Name any target still short, with the reason.
  - Evidence: not run yet.
- [ ] TC5.02 Full Python suite passes with the same skips as before (the opt-in smoke tests only); ruff, format and mypy on 3.11–3.13 are clean.
  - Evidence: not run yet.
- [ ] TC5.03 CI passes on the final commit; ledger rows added to this file and to `docs/PDF2AUDIOBOOK_TODO.md` with the full SHA and run IDs.
  - Evidence: not run yet.

## Found while testing

- **TC1.06, backend load errors are not content-free.** `WhisperBackend._load` (`verification/backends.py`) lets the library's load exception through unchanged. With a message that includes the weights path, the path reaches the caller (`RuntimeError: cannot read weights at <path>`). The run layer masks it in reports, but the backend's error does not meet `CLAUDE.md`'s content-free rule. Test: `test_a_model_that_fails_to_load_raises_a_content_free_error` (xfail, strict). The fix (wrap load errors in `AudioError` with fixed text) is a source change, not a test change, so it is for the owner to decide.
