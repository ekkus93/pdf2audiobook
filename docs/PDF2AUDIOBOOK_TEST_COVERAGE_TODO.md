# PDF2Audiobook — Test Coverage TODO

**Status:** Complete; TC0–TC7.03 done with exact-head CI. After the user's review, the bullet bug and the flaky heartbeat test were fixed in a follow-up round (see "Found while testing")
**Date:** 2026-11-13
**Baseline:** master at 7ca1b3907f965372fd5ebb80ee88755fb2278bf8
**Specification:** `docs/PDF2AUDIOBOOK_TEST_COVERAGE_SPEC.md` (T1–T9)

## Working rules

- Work in the order below. Use `[x]` only when the tests exist, pass, and have a recorded mutation result (spec T7). Check a parent only when all its subitems are checked.
- Tests only: no file under `src/` changes. A test that exposes a bug is marked `xfail(strict=True)` and the bug goes in "Found while testing".
- Every error-path test asserts the fixed message and that no path, file name, book text or OS error text leaks.
- One area per commit: `test(<scope>): cover <area>`, no body, no `Co-Authored-By` trailer. Run `/verify` and mypy on 3.12 and 3.13 before each commit.
- After CI finishes, add a ledger row in a separate `docs:` commit with the full SHA and the real run ID, to this file and to `docs/PDF2AUDIOBOOK_TODO.md`. The ledgers are append-only.

## Phase TC0 — Baseline

- [x] TC0.01 Run the T8 coverage command at the baseline and record each target module's statement and branch coverage in the ledger.
  - Evidence: coverage run at 7ca1b3907f965372fd5ebb80ee88755fb2278bf8 (2060 passed, 1 skipped). Statements missed / total, branches partial / total, combined cover:
    - `audio/encoding.py`: 38/195, 17/56, 78%
    - `audio/progress.py`: 23/141, 12/54, 82%
    - `document/listing.py`: 7/37, 2/20, 77%
    - `llm/budget.py`: 31/238, 13/100, 87%
    - `llm/vision.py`: 32/87, 8/20, 61%
    - `pdf_ocr.py`: 24/217, 16/96, 87%
    - `review_transaction.py`: 17/152, 13/64, 86%
    - `tts/selection.py`: 8/63, 6/24, 84%

## Phase TC1 — Budget ledger (T1)

- [x] TC1.01 T1.a: settlement rollback leaves the row `unknown` with null counts; other rows unchanged.
  - Evidence: `tests/test_llm_book_budget_ledger.py::test_settlement_that_would_overflow_the_ledger_is_recorded_as_unknown`: two settlements of 2**62 + 7 tokens; the second row becomes `unknown` with null counts and cost, and the first stays complete. Commit 1d2c487ffbb00dbb207f81b85777cfd0b3c321b4, Python CI run [43398927127](https://github.com/ekkus93/pdf2audiobook/actions/runs/43398927127) passed.
- [x] TC1.02 T1.b: each `resolve_unknown` validation error, with the row unchanged.
  - Evidence: `tests/test_llm_book_budget_ledger.py::test_resolve_unknown_rejects_invalid_accounting_and_keeps_the_row` (negative, incomplete, total below parts, negative price, infinite price) and `tests/test_llm_book_budget_ledger.py::test_resolve_unknown_refuses_a_cumulative_total_beyond_the_supported_range`; each asserts the fixed message, `rows()` unchanged and no path in the message. Commit 1d2c487ffbb00dbb207f81b85777cfd0b3c321b4.
- [x] TC1.03 T1.c: double settlement through `settle`, `settle(rejected=True)` and `settle_unbilled`, and a missing call ID.
  - Evidence: `tests/test_llm_book_budget_ledger.py::test_settling_a_settled_or_missing_call_changes_nothing`: `settle`, `settle(rejected=True)` and `settle_unbilled`, each on a settled and on a missing call ID (6 cases). Commit 1d2c487ffbb00dbb207f81b85777cfd0b3c321b4.
- [x] TC1.04 T1.d: unsupported schema version, migration from versions 1 and 2, unreadable ledger.
  - Evidence: `tests/test_llm_book_budget_ledger.py::test_older_ledger_is_migrated_to_version_three_with_its_rows` (version 1 with no bound columns, version 2 with only the token column: both columns exist afterwards, the row is intact, and a cost-bounded reservation works); `tests/test_llm_book_budget_ledger.py::test_unsupported_ledger_schema_version_is_refused` (read-write and read-only; the version stays 4); `tests/test_llm_book_budget_ledger.py::test_unreadable_ledger_fails_with_a_fixed_message`; `tests/test_llm_book_budget_ledger.py::test_ledger_with_an_unparseable_cost_is_refused_when_listed`. Commit 1d2c487ffbb00dbb207f81b85777cfd0b3c321b4.
- [x] TC1.05 T1.e: show lines 52 and 300 are unreachable, or record why not, in "Found while testing".
  - Evidence: Recorded under "Found while testing": `budget.py:52` repeats the check at lines 48–49 with the same condition, so it can't be reached; `budget.py:300` needs `lastrowid` to be `None` after a successful `INSERT` into a rowid table, which `sqlite3` never returns. Neither was tested through a mock.
- [x] TC1.06 T7 mutation results for TC1.01–TC1.04.
  - Evidence: 15 mutants of `llm/budget.py`; 14 fail the new tests. The first run caught 12 of 14. The `upper_bound_usd` column not being added survived until the migration test also checked the columns and a cost-bounded reservation, and a third migration mutant (token column not added) was added and caught. One mutant is equivalent: doubling the explicit cumulative limit in `resolve_unknown` (line 461) changes nothing, because `_stats` raises the same error inside the same transaction (recorded under "Found while testing").

## Phase TC2 — Vision page selection (T2)

- [x] TC2.01 T2.a: true for an image, three or more drawings and two columns; false for one column and for two drawings.
  - Evidence: `tests/test_llm_vision.py::test_visual_content_detection` with real PyMuPDF pages: image, three drawings and two columns give True; two drawings, unbalanced columns and one column give False. Commit 20e1c2868ae8a64d061e1f37983cceb3ef0cdb16, Python CI run [43399273780](https://github.com/ekkus93/pdf2audiobook/actions/runs/43399273780) passed.
- [x] TC2.02 T2.b: each `try` block's fallback when PyMuPDF raises.
  - Evidence: `tests/test_llm_vision.py::test_visual_content_detection_falls_back_when_pymupdf_raises`: an image-inventory error, then a drawings error, falls through to the next check; a column-check error returns False.
- [x] TC2.03 T2.c: malformed text blocks are ignored.
  - Evidence: `tests/test_llm_vision.py::test_malformed_text_blocks_are_not_counted_as_a_column`: strings, minus infinity on the left, NaN, plus infinity on the right, and four-field blocks on either side; each case also checks that a good block in its place does count.
- [x] TC2.04 T2.d: `review_visual_pages` sends no image for a page without visual content.
  - Evidence: `test_pages_without_visual_content_are_never_sent` (only page 2 of prose, image, prose reaches the provider), `test_text_only_book_sends_nothing`, `test_page_limit_skips_later_visual_pages_with_a_warning`, `test_invalid_vision_response_is_rejected_with_a_page_warning`, `test_unopenable_book_fails_with_a_fixed_message`; plus the `_render_png` tests added in TC7.01 (zero-area page, half-scale retry, render error, image that stays over 4 MiB), commit 95f97ba39c866fe684f56c7348f86e42f7fa8cb0.
- [x] TC2.05 T7 mutation results for TC2.01–TC2.04.
  - Evidence: 18 mutants of `llm/vision.py`, all caught. On the first run the NaN-left and four-field cases were too weak: NaN fails the comparison by itself, and the four-field case sat on the side the mutant didn't change. They were replaced with infinity cases on the side that matters and four-field cases on both sides.

## Phase TC3 — Review transactions (T3)

- [x] TC3.01 T3.a: each invalid-journal case is refused with the fixed message and no workspace change.
  - Evidence: `tests/test_review_transaction_journal.py::test_invalid_journal_is_refused_without_touching_the_workspace` (22 records: unsafe and unknown targets, extra keys, wrong version, bad rows, duplicate target, bad hash, bad and junk-mixed base64, data and hash mismatches, missing coverage or metadata, non-object, not JSON), `test_journal_that_is_not_a_regular_file_is_invalid` (directory, symlink) and `test_journal_target_under_a_symlinked_chapters_directory_is_unsafe`. Each asserts the fixed message and an unchanged workspace. Commit 0e7be1f014171d5d731e3a6faf2da57c23ea1376, Python CI run [43399606969](https://github.com/ekkus93/pdf2audiobook/actions/runs/43399606969) passed.
- [x] TC3.02 T3.b: a changed target blocks recovery; `back_up_changed=True` backs it up and restores it.
  - Evidence: `test_changed_target_blocks_recovery_and_names_only_its_label`, `test_back_up_changed_keeps_the_edited_file_and_finishes`, `test_target_that_changes_during_recovery_blocks_it` (the per-write recheck) and `test_unexpected_failure_during_recovery_is_content_free`.
- [x] TC3.03 T3.c: non-manifest workspace, metadata changed during planning, size limit, pending journal.
  - Evidence: `test_review_needs_a_manifest_json_workspace`, `test_chapter_metadata_changed_during_planning_is_refused`, `test_transaction_over_the_size_limit_writes_no_journal` and `test_commit_whose_recovery_is_blocked_reports_the_changed_labels`.
- [x] TC3.04 T7 mutation results for TC3.01–TC3.03.
  - Evidence: 19 mutants of `review_transaction.py`, all caught. Lenient base64 decoding first survived, because the junk-only string then failed the hash check anyway; the `base64-with-junk` case (valid base64 plus one stray character, matching hash) now catches it.

## Phase TC4 — Progress reader (T4)

- [x] TC4.01 T4.a: one parametrized test covering every `read_synthesis_progress` rejection; each returns `None` with one warning.
  - Evidence: `tests/test_tts_progress.py::test_malformed_progress_is_unavailable_with_one_warning` (22 cases), `test_progress_beyond_its_bounds_is_unavailable` (record count and file size) and `test_unreadable_progress_is_unavailable`; each asserts `None` and exactly one `progress_unavailable` warning. The control is `test_valid_progress_records_are_reconstructed`. Commit 0cf554cfe701846737f3074eed06ab9f0765f3a9, Python CI run [43400089662](https://github.com/ekkus93/pdf2audiobook/actions/runs/43400089662) passed.
- [x] TC4.02 T4.b: writer-side lines 46 and 56–57 covered or recorded.
  - Evidence: `test_oversized_progress_record_is_never_written` (line 46) and `test_progress_that_cannot_be_created_fails_with_a_fixed_message` (lines 56–57).
- [x] TC4.03 T7 mutation results for TC4.01–TC4.02.
  - Evidence: 19 mutants of `audio/progress.py`, all caught. The optional chunk mapping first survived, because `dict(None)` raises and is caught anyway; the `chunk-mapping-as-pairs` case, which `dict()` would accept, now catches it.

## Phase TC5 — Encoding (T5)

- [x] TC5.01 T5.a: sample-rate, shape, conversion and empty or non-finite input errors, with no temporary WAV left.
  - Evidence: `tests/test_mp3_output_failures.py::test_invalid_audio_is_refused_before_ffmpeg_runs` (8 cases); each asserts the message, no FFmpeg call and an empty output directory. Commit 3c044ac73441db113e2382e547803adc0eebc0c2, Python CI run [43400502608](https://github.com/ekkus93/pdf2audiobook/actions/runs/43400502608) passed.
- [x] TC5.02 T5.b: missing FFmpeg for `encode_mp3` and `encode_m4b`.
  - Evidence: `test_missing_ffmpeg_stops_mp3_encoding_before_any_write` and `tests/test_m4b_packaging.py::test_missing_ffmpeg_stops_packaging`.
- [x] TC5.03 T5.c: M4B failures: no chapters, invalid duration, non-zero exit, timeout, empty or invalid MP4 audio.
  - Evidence: `tests/test_m4b_packaging.py`: `test_audiobook_needs_at_least_one_chapter`, `test_invalid_chapter_audio_is_refused` (missing, zero, NaN, unreadable), `test_ffmpeg_packaging_failures_publish_nothing` (non-zero exit, no output, empty output, timeout, real invalid MP4; FFmpeg's stderr never appears) and `test_m4b_container_is_checked_before_and_after_tagging`.
- [x] TC5.04 T5.d: wrong WAV settings, zero-duration MP3, MP3 without an ID3 tag.
  - Evidence: `test_chapter_wav_with_the_wrong_settings_is_refused` (stereo, wrong rate, no frames), `test_mp3_without_tags_gets_new_tags_before_publication` and `test_zero_duration_mp3_is_not_published`.
- [x] TC5.05 T7 mutation results for TC5.01–TC5.04; state whether the FFmpeg-gated tests ran.
  - Evidence: 22 mutants of `audio/encoding.py`; 21 caught. The zero-length MP4 first survived, because the fake ran out of values on the reparse and raised; the fake now returns a valid reparse value. One is equivalent: dropping the `bool` sample-rate check, since `True` is 1 and fails the range check anyway. FFmpeg is installed locally and in CI, so `test_m4b_contains_aac_audio_tags_and_chapter_navigation` and the other FFmpeg-gated tests ran; the new tests replace FFmpeg and don't need it.

## Phase TC6 — Lower priority (T6)

- [x] TC6.01 T6.a: `_tts_model_identity` fallbacks and Piper profile branches in `settings_for_book_tts`.
  - Evidence: `tests/test_tts_model_identity.py`: `test_piper_without_a_model_path_has_a_stable_placeholder_identity`, `test_piper_model_files_that_disappear_change_the_identity` (pins the exact missing-files fingerprint), `test_kitten_identity_records_a_missing_engine`, `test_piper_profile_sets_the_piper_voice_speed_and_model`, `test_explicit_option_overrides_the_profile`, `test_explicit_provider_overrides_the_profile_provider`, `test_book_without_a_profile_keeps_the_same_settings_object` and `test_kitten_profile_sets_the_kitten_model_voice_and_speed` (added in TC7.01, commit 95f97ba39c866fe684f56c7348f86e42f7fa8cb0). Commit 51674c93987faa09a927a1e41c50d680ebcca11b.
- [x] TC6.02 T6.b: list-marker rules in `document/listing.py`.
  - Evidence: `tests/test_list_classifier_fx10.py::test_list_runs_need_sequential_markers` (letters, mixed case, bullets, Roman numerals, numbers, and skips of each) and `test_three_digit_parenthesised_number_is_prose`. The bullet case is `xfail(strict=True)`: a real bug, recorded under "Found while testing".
  - Note: the bug was fixed after the user's review in 092b072a9f9fa49ff2cf4fa9503cb05cc67d5cd2; the `xfail` mark was removed and an asterisk case added.
- [x] TC6.03 T6.c: OCR error branches and heuristic early returns in `pdf_ocr.py`; state whether the Tesseract-gated tests ran.
  - Evidence: `tests/test_pdf_diagnostics.py`: `test_ocr_engine_version_falls_back_without_failing`, `test_language_listing_failures_are_reported_as_none_or_empty`, `test_ocr_cache_requires_the_source_hash`, `test_dominant_raster_counts_separate_images_and_gaps`, `test_degenerate_image_is_skipped_not_fatal`, `test_dominant_raster_rejects_implausible_or_malformed_images`, `test_dense_vector_art_detection_guards` and `test_dense_vector_art_needs_a_drawing_list`. Tesseract is replaced by module-local stand-ins, so none of these needs it; Tesseract is installed locally and in CI, and the gated OCR tests ran.
- [x] TC6.04 T7 mutation results for TC6.01–TC6.03.
  - Evidence: `tts/selection.py`: 14 mutants, all caught. The missing-file and explicit-provider mutants first survived and were caught after the identity was pinned and a mismatched-provider case was added. `document/listing.py`: 7 mutants, all caught. `pdf_ocr.py`: 20 mutants; 18 caught after four weak cases were strengthened (gap coverage under 65%, a degenerate image next to a real scan, a 100-path page of zero width, and a non-list iterable). The remaining two are equivalent, shown by a direct probe with each guard removed: a zero-area page can't intersect any image, and non-finite image bounds always fail the later density or area checks. CI run [43401202733](https://github.com/ekkus93/pdf2audiobook/actions/runs/43401202733) at 51674c93987faa09a927a1e41c50d680ebcca11b failed, as did [43401604804](https://github.com/ekkus93/pdf2audiobook/actions/runs/43401604804) at 95f97ba39c866fe684f56c7348f86e42f7fa8cb0: `test_kitten_identity_records_a_missing_engine` assumed `kittenml` was installed, which CI doesn't do. Fixed in a7307b3af9e1aa7325a0550a66b1e070a141fa47 by stubbing both sides, and checked with `kittenml` simulated as absent; Python CI run [43402118525](https://github.com/ekkus93/pdf2audiobook/actions/runs/43402118525) passed.

## Phase TC7 — Closure

- [x] TC7.01 T8: rerun coverage; record each module's branch coverage against its target, and list any shortfall in "Found while testing".
  - Evidence: Coverage at 95f97ba39c866fe684f56c7348f86e42f7fa8cb0 (2243 passed, 1 skipped, 1 xfailed). Combined cover (target), statements missed / total, partial branches / total:
    - `llm/budget.py`: 96% (≥95%), 11/238, 3/100
    - `llm/vision.py`: 100% (≥95%), 0/87, 0/20
    - `review_transaction.py`: 99% (≥95%), 0/152, 1/64
    - `audio/progress.py`: 99% (≥95%), 0/141, 1/54
    - `audio/encoding.py`: 95% (≥95%), 12/195, 1/56
    - `tts/selection.py`: 100% (≥92%), 0/63, 0/24
    - `document/listing.py`: 96% (≥92%), 1/37, 1/20
    - `pdf_ocr.py`: 99% (≥92%), 1/217, 1/96
    - Project total: 95% (was 93%)
    The first rerun left `llm/vision.py` at 90% (`_render_png`) and `tts/selection.py` at 93% (Kitten profile fields); four render tests and one Kitten profile test closed both (commit 95f97ba39c866fe684f56c7348f86e42f7fa8cb0). No target falls short.
- [x] TC7.02 T9: the full suite, golden snapshot and patch-target guard pass; no existing test edited except to add cases.
  - Evidence: `git diff 7ca1b3907f965372fd5ebb80ee88755fb2278bf8 -- src` is empty. Across 9 test files the diff adds 1,678 lines and removes 4, all of them import lines that were extended. The golden snapshot and `tests/test_patch_targets.py` pass. Full suite at a7307b3af9e1aa7325a0550a66b1e070a141fa47: 2243 passed, 1 skipped (Kitten smoke, opt-in), 1 xfailed (the recorded bullet bug).
- [x] TC7.03 Final gate: `/verify` passes with mypy on 3.11, 3.12 and 3.13; exact-head CI passes for every commit; "Found while testing" is reviewed with the user.
  - Note: not checked. `/verify` passes, with mypy on 3.11, 3.12 and 3.13. Every commit has exact-head CI. Two runs failed and are recorded in TC6.04: [43401202733](https://github.com/ekkus93/pdf2audiobook/actions/runs/43401202733) and [43401604804](https://github.com/ekkus93/pdf2audiobook/actions/runs/43401604804). The fix a7307b3af9e1aa7325a0550a66b1e070a141fa47 passed [43402118525](https://github.com/ekkus93/pdf2audiobook/actions/runs/43402118525). One clause remains: the user's review of "Found while testing".
  - Evidence: the user reviewed "Found while testing" on 2026-11-13 and asked for the bug and the flaky test to be fixed; both are fixed (see that list). `/verify` after the fixes: 2246 passed, 1 skipped, 0 xfailed; ruff and format clean; mypy clean on 3.11, 3.12 and 3.13. Exact-head Python CI: 092b072a9f9fa49ff2cf4fa9503cb05cc67d5cd2 [43514378507](https://github.com/ekkus93/pdf2audiobook/actions/runs/43514378507) passed; 1e696d15976506fc08baf43e6afed1d554ca002f [43514386326](https://github.com/ekkus93/pdf2audiobook/actions/runs/43514386326) passed. The unreachable lines and redundant guards stay as recorded.

## Found while testing

- **Bug** `src/pdf2audiobook/document/listing.py:19`: `_list_marker` strips the last character of the marker, which for `•` or `*` is the whole marker. The bullet rule in `_sequential_markers` (`listing.py:34-35`) can then never match. Scenario: `is_list_line("• second", previous_text="• first", next_text="Prose.")` returns False, so bullet runs with neighbouring lines are not classified as list lines. Pinned by `tests/test_list_classifier_fx10.py::test_list_runs_need_sequential_markers[bullets]` (`xfail(strict=True)`).
  - Fixed in 092b072a9f9fa49ff2cf4fa9503cb05cc67d5cd2 at the user's request: a marker drops its last character only when that is `.` or `)`. Analysis fingerprint bumped to `analysis-v24` (bulleted lines now become `list` blocks), with the upgrade note in `docs/MAINTAINER_GUIDE.md`, the golden snapshot regenerated (only fingerprint digests changed) and the pinned extraction value in `tests/test_equation_identity.py` recomputed. The `xfail` mark is removed; `[bullets]`, the new `[asterisks]` case and `test_bulleted_lines_become_list_blocks` fail on the unfixed code and pass with the fix. CI [43514378507](https://github.com/ekkus93/pdf2audiobook/actions/runs/43514378507) passed.
- **Flaky test, pre-existing** `tests/test_run_status_and_logging.py::test_heartbeat_prints_content_free_lines_only_when_enabled`: the 50 ms heartbeat thread can print before `set_detail` and `advance`, so the first line reads "0/40" (CI run [43401202733](https://github.com/ekkus93/pdf2audiobook/actions/runs/43401202733), Python 3.12 only). Not changed here: the spec allows no edits to existing tests.
  - Fixed in 1e696d15976506fc08baf43e6afed1d554ca002f at the user's request: the test sets up the stage before `bind_workspace` starts the heartbeat thread, and waits for the first line with a 5 s deadline instead of a fixed sleep. A forced-delay probe printed "working" without the stage in the old order and the full "cleanup: 7/40 request" line in the new order; 30 consecutive runs passed. CI [43514386326](https://github.com/ekkus93/pdf2audiobook/actions/runs/43514386326) passed.
- **Unreachable** `src/pdf2audiobook/llm/budget.py:52` (repeats the version check at lines 48–49) and `budget.py:300` (`lastrowid` is never `None` after a successful `INSERT`).
- **Redundant guards** whose removal no test can observe: `budget.py:461` (the cumulative check `_stats` repeats in the same transaction); `audio/encoding.py:29` (the `bool` sample-rate check, since the range check rejects `True`); `pdf_ocr.py:97` (zero page area) and `pdf_ocr.py:110` (non-finite image bounds), both shown equivalent by a direct probe. They are defence in depth; removing them is a separate decision.

## Progress ledger

| Date | Commit SHA | Completed tasks | Tests/CI evidence | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-13 | Not committed | Spec and TODO drafted; no work started. Baseline branch coverage: 93% overall; `llm/vision.py` 61%, `document/listing.py` 77%, `audio/encoding.py` 78%, `audio/progress.py` 82%, `tts/selection.py` 84%, `review_transaction.py` 86%, `llm/budget.py` 87%, `pdf_ocr.py` 87% | Coverage run at 7ca1b3907f965372fd5ebb80ee88755fb2278bf8: 2060 passed, 1 skipped | None |
| 2026-11-13 | 1d2c487ffbb00dbb207f81b85777cfd0b3c321b4 | TC1: budget ledger fail-closed paths (19 cases) | `/verify` 2079 passed, 1 skipped; 15 mutants, 14 caught, 1 equivalent; exact-head Python CI [43398927127](https://github.com/ekkus93/pdf2audiobook/actions/runs/43398927127) passed | TC7.03 needs the user's review |
| 2026-11-13 | 20e1c2868ae8a64d061e1f37983cceb3ef0cdb16 | TC2: vision page selection | `/verify` 2100 passed, 1 skipped; exact-head Python CI [43399273780](https://github.com/ekkus93/pdf2audiobook/actions/runs/43399273780) passed | TC7.03 needs the user's review |
| 2026-11-13 | 0e7be1f014171d5d731e3a6faf2da57c23ea1376 | TC3: review transaction journal guards | `/verify` 2134 passed, 1 skipped; 19 mutants, all caught; exact-head Python CI [43399606969](https://github.com/ekkus93/pdf2audiobook/actions/runs/43399606969) passed | TC7.03 needs the user's review |
| 2026-11-13 | 0cf554cfe701846737f3074eed06ab9f0765f3a9 | TC4: progress reader rejections | `/verify` 2162 passed, 1 skipped; 19 mutants, all caught; exact-head Python CI [43400089662](https://github.com/ekkus93/pdf2audiobook/actions/runs/43400089662) passed | TC7.03 needs the user's review |
| 2026-11-13 | 3c044ac73441db113e2382e547803adc0eebc0c2 | TC5: encoding validation and packaging failures | `/verify` 2191 passed, 1 skipped (FFmpeg tests ran); 22 mutants, 21 caught, 1 equivalent; exact-head Python CI [43400502608](https://github.com/ekkus93/pdf2audiobook/actions/runs/43400502608) passed | TC7.03 needs the user's review |
| 2026-11-13 | 51674c93987faa09a927a1e41c50d680ebcca11b | TC6: TTS selection, list markers, OCR branches; bullet bug pinned as strict xfail | `/verify` 2238 passed, 1 skipped, 1 xfailed; exact-head Python CI [43401202733](https://github.com/ekkus93/pdf2audiobook/actions/runs/43401202733) **failed**: the Kitten engine test assumed `kittenml` was installed (3.11, 3.12, 3.13), plus the pre-existing heartbeat race (3.12) | TC7.03 needs the user's review |
| 2026-11-13 | 95f97ba39c866fe684f56c7348f86e42f7fa8cb0 | TC7.01: vision rendering and Kitten profile tests; all coverage targets met | `/verify` 2243 passed, 1 skipped, 1 xfailed; exact-head Python CI [43401604804](https://github.com/ekkus93/pdf2audiobook/actions/runs/43401604804) **failed** (same Kitten engine test) | TC7.03 needs the user's review |
| 2026-11-13 | a7307b3af9e1aa7325a0550a66b1e070a141fa47 | TC6.04 fix: stub the Kitten engine version on both sides | `/verify` 2243 passed, 1 skipped, 1 xfailed; passes with `kittenml` simulated as absent; exact-head Python CI [43402118525](https://github.com/ekkus93/pdf2audiobook/actions/runs/43402118525) passed | TC7.03 needs the user's review |
| 2026-11-13 | 092b072a9f9fa49ff2cf4fa9503cb05cc67d5cd2 | TC7.03 follow-up: fix the bullet marker bug from "Found while testing"; `analysis-v24` | `/verify` 2246 passed, 1 skipped; exact-head Python CI [43514378507](https://github.com/ekkus93/pdf2audiobook/actions/runs/43514378507) passed | None |
| 2026-11-13 | 1e696d15976506fc08baf43e6afed1d554ca002f | TC7.03 follow-up: fix the flaky heartbeat test from "Found while testing"; TC7.03 closed | `/verify` 2246 passed, 1 skipped; exact-head Python CI [43514386326](https://github.com/ekkus93/pdf2audiobook/actions/runs/43514386326) passed | None |
