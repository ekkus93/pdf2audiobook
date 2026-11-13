# PDF2Audiobook — Long Function Split TODO

**Status:** Open; LF0–LF4, LF5.01 and LF5.02 done with exact-head CI; LF5.03 waits on the user (the scope of `propose_llm_contents_boundaries` and a review of the "Found during split" list)
**Date:** 2026-11-13
**Baseline:** master at 18681585b45a02b0e697b64c03ac38c513a28247
**Specification:** `docs/PDF2AUDIOBOOK_LONG_FUNCTION_SPLIT_SPEC.md` (S1–S12)

## Working rules

- Work in the order below. Use `[x]` only when the implementation exists and its named tests pass. Check a parent only when all of its subitems are checked.
- Every task here is a **refactor**: it proves there is no behaviour change. The full suite, the golden snapshot (LF0.02) and the characterization tests pass unchanged before and after.
- Never change an existing test's inputs, expected results or monkeypatch targets. Never bump a fingerprint, schema, cache-identity or sidecar constant. If a split changes an output, the split is wrong.
- Names that tests patch on a module (for example `pipeline.propose_chapters` or `pdf._ocr_page_lines`) must still take effect. Extracted code that calls them stays in that module or looks them up through it at call time (spec §2).
- Keep every facade re-export, exception type, fixed message, exit code and `from None`. Add any new `src/` module to `[tool.mypy].files`.
- One function per commit: `refactor(<scope>): split <function> into named steps`. Commits have no body; the repo's commit hook rejects `Co-Authored-By` trailers. Run `/verify` and mypy on 3.12 and 3.13 before each commit.
- After CI finishes for a pushed refactor commit, add a ledger row in a separate `docs:` commit. Use the full 40-character SHA and the real run ID, and give the function's line count before and after. The ledger is append-only.
- Bugs found while reading go in the "Found during split" list below (spec §5), never into a refactor commit.

## Phase LF0 — Safety net

- [x] LF0.01 Add the length guard (S10).
  - [x] LF0.01a Add `tests/test_function_length.py`: parse every `src/pdf2audiobook/**/*.py` with `ast` and fail if any function or method is over 100 lines, with nested functions included. Measure Typer commands from their first body statement.
    - Evidence: `tests/test_function_length.py` (`function_lengths`, `MAX_FUNCTION_LINES = 100`). It measures methods and nested functions by qualified name, and Typer commands from their first body statement. Commit e83a8c00e34ae41cde9974f4915aea3810577b29.
  - [x] LF0.01b Allowlist every function over the limit at the baseline, each with its current line count as a ceiling. That covers at least the nine in spec §1, and the guard lists any others it finds. The test fails if a listed function grows past its ceiling.
    - Evidence: the allowlist holds all 23 functions over 100 lines at the baseline, each at its baseline count: the 9 in spec §1 plus 14 others. `test_allowlist_names_only_existing_functions_still_over_the_limit` fails on stale entries.
    - Note: one of the 14 others, `llm/structure.py::propose_llm_contents_boundaries` (234 lines), is over the spec's 200-line out-of-scope threshold but isn't in spec §1. The spec doesn't say whether it is in scope; that's for the user to decide.
  - [x] LF0.01c Show the guard fails when a listed function grows by one line, and when a new function goes over 100 lines, using a scratch worktree. Record both in the ledger.
    - Evidence: in a scratch worktree, adding one line to `pagination_cleanup` failed with `{'pdf2audiobook/document/pagination.py::pagination_cleanup': 438}`, and adding a 102-line function to `jsonio.py` failed with `{'pdf2audiobook/jsonio.py::_new_long_function': 102}`. Each time the other test still passed.
- [x] LF0.02 Add the golden analysis snapshot (S11).
  - [x] LF0.02a Add a characterization test that runs `analyze` with the LLM off on the synthetic fixtures (generated PDFs, `tests/fixtures/outlined_text.pdf` and the synthetic EPUB). It compares normalized `manifest.json`, chapter texts, `coverage.json`, warnings and review reasons with a committed snapshot.
    - Evidence: `tests/test_golden_analysis_snapshot.py` against `tests/fixtures/golden/analysis_snapshot.json` (7.5 KB). The generated fixtures aren't byte-deterministic (zip and PDF timestamps), so `tests/fixtures/golden/golden_book.pdf` (9 KB) and `novel.epub` (6 KB, from `tests/epub_book.py`) were generated once and committed. The snapshot records per-file digests, manifest-section digests (fingerprints included) and a readable summary. Commit dd5f149926dd187e6c83dfe50e2abf92f513c32e.
    - Note: `outlined_text.pdf` is pinned on `--ocr never`, which fails with `ExtractionError` "No text found in PDF; no chapters can be created". With OCR its text would depend on the Tesseract version: 4.1.1 here, and CI's may differ.
  - [x] LF0.02b Confirm it passes at the baseline and is deterministic across two runs and across Python 3.11, 3.12 and 3.13 (CI).
    - Evidence (local): passed on two consecutive runs; passed on Python 3.12 and 3.13 in offline venvs (`uv run --offline --python 3.12/3.13`).
    - Note: resolved. The user approved pushing on 2026-11-13.
    - Evidence (CI): Python CI run 43371140000 at 27d950a04e38f312033792036ab5d59c125c398b passed. Its jobs `tests (3.11)`, `tests (3.12)` and `tests (3.13)` each ran the snapshot test.
- [x] LF0.03 Measure branch coverage of each S1–S9 function with `uv run --with coverage` (the lockfile stays unchanged). For every branch named in spec §3 with no covering test, add a characterization test that passes at the baseline. Record the coverage before and after for each function.
  - Evidence: coverage with `uv run --with coverage` (`uv.lock` unchanged). Lines and branches before → after:
      - `pagination_cleanup` 98%/93% → 99%/95%
      - `propose_chapters` 99%/95% → 99%/95% (no named step uncovered)
      - `_analyze_book_locked` 89%/81% → 94%/87%
      - `_convert_analyzed_book` 90%/96% → 91%/96%
      - `synthesize_chunks` 93%/90% → 93%/92%
      - `_complete_json_call` 91%/86% → 91%/86%
      - `_complete_json_request` 95%/94% → 95%/94% (no named step uncovered)
      - `extract_pdf` 95%/87% → 96%/89%
      - `convert` 89%/82% → 94%/89%
    - Evidence: new tests in commit f64e335a9820724c6c4afefb0b92f4dbba0e7b95:
      - `tests/test_hand_edit_merge_characterization.py` (11): the merge's owner, both-edited, unmatched, skipped, shared-boundary, out-of-range, end-of-document, renamed-block and neighbour branches;
      - `tests/test_split_characterization.py` (10): the S1 tie within one band, the S4 corrupt MP3 behind a valid v3 sidecar, the S5 retry-count validation (5 cases), the S6 cost budget without prices, the S8 empty document and the S9 override routing.
      All pass at the baseline code; the full suite gave 2036 passed, 1 skipped.
    - Note: three targeted lines stay uncovered because no test can reach them:
      - `pipeline.py:640`: manifest validation rejects the range first, and a test pins that;
      - `llm/cache.py:376`: an earlier check raises the same message;
      - `llm/cache.py:384-402`: the no-ledger branch can't run, because any budget creates a temporary ledger.
      These are listed under "Found during split".

**Checkpoint:** the guard, the golden snapshot and the characterization tests are committed, and CI is green, before any split.

## Phase LF1 — Pure functions

- [x] LF1.01 Split `pagination_cleanup` (S1).
  - [x] LF1.01a Extract the steps in spec §3 S1, including a named predicate for each fail-closed rule. The orchestrator and every step are at most 100 lines.
    - Evidence: commit 4b761474e0c1c0bff4a30f8ca843c9a8e1b9e9ea. The orchestrator is 62 lines (was 437) and the longest step, `_find_sequences`, is 61. The steps, in order:
      - page geometry: `_page_geometry`, which builds `_PageGeometry` with `valid_page`, `positions` and `label_matches`;
      - running heads: `_running_heads`;
      - candidates: `_collect_candidates` and `_record_candidate`, with one named predicate per fail-closed rule (`_continuous_with_body`, `_protected_kind`, `_quoted_or_dialogue`, `_speaker_label_or_reference`, `_body_phrase`, `_extended_prose`, `_list_label`, `_unconfirmed_numeral`);
      - ranking and ties: `_rank_band_numerals`, `_find_sequences` and `_select_sequences`;
      - the label check: `_labels_disagree`;
      - edits, warnings and reasons: `_flag_ambiguity` and `_removal_reason`, with `_confirmed_number` and `_repeated_in_margin`.
    - Evidence: a differential run of the old and new functions on 7,000 generated inputs found no mismatch in edits, warnings or review reasons. 1,823 inputs produced edits and 1,499 produced warnings, covering all three removal reasons.
  - [x] LF1.01b Remove it from the length allowlist. The full suite, the golden snapshot and the characterization tests pass unchanged.
    - Evidence: allowlist entry removed in 4b761474e0c1c0bff4a30f8ca843c9a8e1b9e9ea. `/verify` passed: 2036 passed, 1 skipped (Kitten smoke, opt-in), with mypy on 3.11, 3.12 and 3.13. Python CI run 43371719157 passed.
- [x] LF1.02 Split `propose_chapters` (S2).
  - [x] LF1.02a Extract the steps in spec §3 S2. The orchestrator and every step are at most 100 lines.
    - Evidence: commit b0beee3b161fe8a25d256493698aa956f603c0eb. The orchestrator is 46 lines (was 448) and the longest step, `_heading_name_confidence_evidence`, is 55. State is shared through the private `_HeadingEvidence` dataclass. The steps, in order:
      - typography: `_typical_body_size` and `_is_typographic_heading`;
      - contents pages: `_listing_pages`, including the single-page gap fill;
      - numbered and Roman candidates: `_text_headings`;
      - bookmarks: `_valid_bookmarks`, `_inferred_bookmark_offset`, `_bookmark_match` and `_anchor_bookmarks`;
      - ordering, merging and confidence: `_drop_crowded_typography`, `_corroborate_numerals`, `_drop_listed_labels`, `_drop_weak_candidates`, `_drop_subtitles`, `_chapter_starts`, `_heading_name_confidence_evidence` and `_build_chapters`.
    - Evidence: a pytest plugin compared the old and new functions on all 255 `propose_chapters` calls the suite makes. Chapters, warnings, review reasons and exceptions matched on every call.
  - [x] LF1.02b Remove it from the length allowlist. The full suite, the golden snapshot and the characterization tests pass unchanged.
    - Evidence: allowlist entry removed in b0beee3b161fe8a25d256493698aa956f603c0eb. `/verify` passed (2036 passed, 1 skipped; mypy on 3.11, 3.12 and 3.13), and Python CI run 43372183567 passed.

## Phase LF2 — Pipeline orchestrators

- [x] LF2.01 Split `_analyze_book_locked` (S3).
  - [x] LF2.01a Extract the steps in spec §3 S3 inside `pipeline.py`, passing shared state through a private run dataclass. Turn the nested `queue_change` and `map_boundary` into named functions.
    - Evidence: commit 64125110cb030b02abee26117a05ff670ae582d4. The orchestrator is 31 lines (was 553) and the longest step, `_run_llm_tasks`, is 90. Run state lives in `_AnalysisRun`, step output in `_AnalysisState`, and the merge in `_HandEditMerge`. Every step stays in `pipeline.py`. The steps, in order:
      - load, validate and resume: `_start_analysis`, then `_reuse_existing_analysis` with `_switch_footnote_policy`;
      - extraction: `_extract`;
      - deterministic cleanup: `_deterministic_cleanup`;
      - LLM proposals: `_llm_proposals`, with `_llm_analysis_requested`, `_cached_llm_worker`, `_run_llm_tasks` and `_deterministic_fallback`;
      - `propose_chapters`, called from the orchestrator;
      - the hand-edit merge: `_merge_hand_edits`, with `_match_old_chapters`, `_queue_hand_edits`, `_queue_moved_boundary`, `_apply_hand_edits`, and `_queue_change` and `_map_boundary` (the former nested `queue_change` and `map_boundary`);
      - warnings and review reasons: `_chapter_review`;
      - writing: `_write_analysis`.
  - [x] LF2.01b Confirm that every `pipeline.*` name tests patch still takes effect. Grep the tests' `monkeypatch.setattr` targets for `pipeline`, and record that the targeted tests pass unchanged.
    - Evidence: the grep found 21 patched names. The analysis steps look these up as `pipeline` module globals at call time: `read_manifest`, `render_chapter_texts`, `create_provider`, `propose_chapters`, `extract_pdf`, `pagination_cleanup`, `write_json`, `propose_llm_cleanup`, `digest_file`, `_analysis_stage_fingerprints` and `CachedLLMProvider`. All 46 test files that patch `pipeline` passed unchanged: 263 tests.
  - [x] LF2.01c Remove it from the length allowlist. The full suite, the golden snapshot and the characterization tests pass unchanged.
    - Evidence: allowlist entry removed in 64125110cb030b02abee26117a05ff670ae582d4. `/verify` passed (2036 passed, 1 skipped; mypy on 3.11, 3.12 and 3.13), including all 11 hand-edit merge characterization tests. Python CI run 43372579420 passed.
- [x] LF2.02 Split `_convert_analyzed_book` (S4).
  - [x] LF2.02a Extract the steps in spec §3 S4. Keep the keyword parameters, and gather them into a private run dataclass inside `conversion.py`. Keep calling dependencies through `ConversionServices`.
    - Evidence: commit d28c9b99ff5664c53fdb9bb30b96eff723f06cb2. The signature is unchanged. The orchestrator is 86 lines (was 421), and the parameters are gathered into the private `_ConversionRun` dataclass. Every dependency is still called through `run.services`. The steps, in order:
      - loading the manifest and applying review acknowledgements: after `_remove_stale_temporary_audio`, the orchestrator calls `services.read_manifest`, `services.prepare_chapter_selection(..., acknowledge=accept_review)` and `services.render_chapter_texts`;
      - chapter selection and the voice-marker preflight: `_read_voice_markers`, `_preflight_voice_markers` and `_initial_status`;
      - audio identities and reuse, with the MP3 tag check: `_plan_synthesis`, `_chapter_identity`, `_cache_files_ready` and `_reusable_audio`;
      - synthesizing one chapter: `_convert_chapter`, `_synthesize_and_encode` and `_fail_chapter`;
      - publishing and cleanup: `_publish_chapter` and `_remove_obsolete_audio`;
      - status: `_write_conversion_status`.
    - Note: two closures stay nested inside `_convert_chapter`: the progress callback `on_chunk` and `settle`. They bind per-chapter progress state, and the task names only the spec §3 steps. The model and voice lookups (`_tts_model_identity`, `tts_selection`) still run outside the synthesis `try`, as they did before, so an `AudioError` from them is still not a chapter failure.
  - [x] LF2.02b Remove it from the length allowlist. The full suite (including the FFmpeg-gated conversion tests) and the characterization tests pass unchanged.
    - Evidence: allowlist entry removed in d28c9b99ff5664c53fdb9bb30b96eff723f06cb2. FFmpeg, Tesseract and Node are installed, so the only skip is the opt-in Kitten smoke. `/verify` passed (2036 passed, 1 skipped; mypy on 3.11, 3.12 and 3.13), and Python CI run 43372876736 passed.

## Phase LF3 — Audio and LLM

- [x] LF3.01 Split `synthesize_chunks` (S5). Keep validation that today runs before any engine call or cache replay in that position. Remove it from the allowlist; the suite passes unchanged.
  - Evidence: commit ea53f56a8bf5115d8c9d24bda3ef8faa87f6d59d. The function is 95 lines (was 308). The steps, in order:
    - validation: `_validate_synthesis_inputs`, still first, before any engine call or cache replay;
    - the chunk plan and cache keys: `_chunk_plan`, `_chunk_voices` and `_chunk_identities`;
    - the progress ledger: `_initial_progress`;
    - per chunk: `_replay_cached_chunk`, or `_synthesize_new_chunk` (`_generate_with_retries`, `_store_generated_chunk`), then `_record_chunk_failure` or `_record_chunk_completion`;
    - output: `_emit_silence`, streaming or collecting;
    - finishing: `_finish_progress`.
  - Evidence: 1,500 differential trials compared the old and new functions with fake engines, including transient and permanent failures, warm and corrupted caches, streaming and voice markers. Results, engine calls, `on_chunk` calls, cache files and progress files were identical in every trial (846 succeeded, 654 raised). The callback order is unchanged: `on_chunk` runs before the progress stream is updated. Allowlist entry removed. `/verify` passed (2036 passed, 1 skipped; mypy on 3.11, 3.12 and 3.13). Python CI run 43373362904 passed.
- [x] LF3.02 Split `_complete_json_call` (S6). The fail-closed order is unchanged: no reservation before the bounds check, and no cache hit that skips the oversized-request rejection. Remove it from the allowlist; the budget and cache tests pass unchanged.
  - Evidence: commit 55603b1bac28145f1b393ad0635af19e0b71134e. The function is 35 lines (was 264). The steps, in order:
    - request bounds: `_resolve_served_identity`, `_check_request_bounds`, then `_request_key`;
    - cache lookup: `_cached_response`;
    - server-side limits, on a miss: `_request_upper_bounds`, then `_check_served_capacity`;
    - reservation: `_reserve_budget`, with `_check_remaining_budget`, `_reserve_ledger_call` and `_install_attempt_accounting`, which holds the former `start_attempt` and `settle_attempt`;
    - the request: `_prepare_provider` and `_send_request`;
    - verified usage: `_check_verified_usage`.
  - Note: before the split, neither fail-closed order had a test. Both of these mutants passed the whole suite (2036 passed): moving `_check_request_bounds` after the cache lookup, and moving `_check_served_capacity` after `_reserve_budget`. Commit 876dbe2cb0db67b996a51a153d7ff729fa96863e adds two characterization tests to `tests/test_split_characterization.py`: `test_oversized_request_is_rejected_even_when_its_reply_is_cached` and `test_served_capacity_is_checked_before_the_budget_is_reserved`. They pass at the pre-split code and after the split, and each fails against its mutant. That commit was pushed together with 55603b1, so it has no CI run of its own.
  - Evidence: allowlist entry removed. The 426 budget, cache and LLM tests pass unchanged. `/verify` passed (2038 passed, 1 skipped; mypy on 3.11, 3.12 and 3.13). Python CI run 43374161163 passed.
- [x] LF3.03 Split `_complete_json_request` (S7). Turn the nested settle closures into named functions or methods with an explicit attempt context, and the loop into a dispatcher over typed outcomes. Remove it from the allowlist; the provider matrix and budget tests pass unchanged.
  - Evidence: commit 819d364a055f3fa7c8666fe0fa2aecfea146e9d5. The function is 56 lines (was 262). Each attempt is an explicit `_Attempt`, settled at most once by `_finish_attempt`. The 9 closures became these methods:
    - `_finish_attempt`, `_prepare_usage` and `_aggregate_usage`;
    - `_settle_error_usage`, shared by the JSON-mode fallback and final client errors;
    - `_settle_non_retryable`, `_fall_back_from_json_mode`, `_drop_rejected_parameter` and `_back_off`;
    - `_accept_response` and `_handle_transport_error`.
    The loop dispatches on the typed `_ResponseAction` that `_classify_response` returns: `json_mode_fallback`, `rejected_parameter`, `retry` or `final`. Retry state lives in `_RequestState`. Payload building is in `_build_payload`, and the remote-upload warning in `_warn_remote_upload`.
  - Evidence: 4,000 differential trials over random response sequences compared the old and new providers. The sequences covered success, malformed JSON, JSON-mode rejection, parameter rejection, retryable and final statuses, connect, timeout and read errors, missing choices, vision, and usage present or invalid, with and without attempt accounting. Results, settle calls (ids, usage and outcome), sent payloads, `last_usage`, `total_usage`, unsupported parameters, the JSON-mode flag, `request_count` and stderr were identical in every trial (732 succeeded, 3,268 raised). Allowlist entry removed. `/verify` passed (2038 passed, 1 skipped; mypy on 3.11, 3.12 and 3.13). Python CI run 43374666980 passed.

## Phase LF4 — Extraction and CLI

- [x] LF4.01 Split `extract_pdf` (S8). Every `pdf.*` name tests patch (`_open`, `_ocr_page_lines`, `_cached_ocr_lines`) still takes effect. Remove it from the allowlist; the suite passes unchanged, including the Tesseract-gated tests.
  - Evidence: commit f9a8c3a0f2bae2b48afccaa17c13b0d670b30973. The function is 41 lines (was 225). Every step stays in `pdf.py`, so the patched names are still module globals looked up at call time: `_open`, `_lines`, `_ocr_page_lines`, `_cached_ocr_lines` and `_ocr_engine_version`. The steps, in order:
    - opening and validation: `_start_extraction`, which fills `_ExtractionRun`;
    - per page: `_extract_page`, which calls `_load_page`, `_page_size`, `_page_text_lines` (the strategy, the OCR fallback and `_no_text_reason`), `_annotate_page` (tables, artwork, special material, reading order, captions, notes and equations, giving `_PageAnnotations`), `_page_label` and `_build_page_blocks`.
  - Evidence: on every fixture and generated document, old and new returned identical `ExtractedDocument`s, with `--ocr never` and with `auto` (real Tesseract). Tesseract is installed, so the Tesseract-gated tests ran. Allowlist entry removed. `/verify` passed (2038 passed, 1 skipped; mypy on 3.11, 3.12 and 3.13). Python CI run 43374927081 passed.
- [x] LF4.02 Split the `convert` CLI command body (S9) into a `_run_convert` helper and a dry-run helper. Error handling stays in the command. Remove it from the allowlist; CLI and JSON error tests pass unchanged.
  - Evidence: commit f2a90664866141238481ecffdbe1137cf490947b. The body is 67 lines (was 140), and the steps are:
    - `_convert_overrides` (85 lines): builds the overrides;
    - `_check_accept_review`;
    - `_dry_run_convert` (45 lines);
    - `_run_convert` (33 lines).
    The `KeyboardInterrupt`, `typer.Exit`/`ClickExit` re-raise and `fail()` handling stay in `convert`. Lazy imports still resolve at call time, so patching `pdf2audiobook.pipeline.convert_book` and `pdf2audiobook.audio.read_cover_image` still works.
  - Evidence: `convert --help` is byte-identical. 600 differential runs through `CliRunner` used random option combinations and configs (openai, llama-server, piper, none). Exit code, stdout, stderr and the settings passed to `convert_book` were identical in every run (377 exited 0, 223 exited 2). Allowlist entry removed. `/verify` passed (2038 passed, 1 skipped; mypy on 3.11, 3.12 and 3.13). Python CI run 43375191668 passed.

## Phase LF5 — Documentation and closure

- [x] LF5.01 Update `docs/MAINTAINER_GUIDE.md` (S12): the analysis and conversion orchestrators and their steps, and how to use the length-guard allowlist.
  - Evidence: commit 2cb1f1f42b585fb4782d4659f9ec57ff597b80c8. "Architecture and extension points" gains an "Orchestrators and their steps" paragraph. It lists the analysis and conversion steps in order and the lower-level orchestrators. "Development, CI and troubleshooting" explains the length guard and its shrink-only `ALLOWLIST`. The same commit gives each remaining allowlist entry its reason. No upgrade note was added: nothing persisted changed. Python CI run 43375326880 passed.
- [x] LF5.02 Confirm with `git diff 18681585b45a02b0e697b64c03ac38c513a28247 -- src` that no fingerprint, schema, cache-identity or sidecar constant changed. Record the check in the ledger.
  - Evidence: the diff to 2cb1f1f42b585fb4782d4659f9ec57ff597b80c8 covers 9 files, +3326/−2016 lines. Inside it, the version-like literals on removed lines and on added lines are the same multiset (11 each: `llm-json-cache-v1`, `llm-json-image-cache-v1`, `tts-wav-v3`, `visual-review-v1`, `sidecar_version: 3` and six `schema_version: 1`), so they only moved. Across the whole `src` tree, all 44 such literals are identical at the baseline and at HEAD (identical md5 of the sorted inventory). These include the `*-vN` fingerprint tags, `schema_version`, `sidecar_version` and every `*VERSION*` constant.
- [ ] LF5.03 Final gate:
  - `/verify` passes, with mypy on 3.11, 3.12 and 3.13;
  - exact-head CI passes for every refactor commit;
  - the allowlist holds only out-of-scope functions, each with its reason;
  - the "Found during split" list is reviewed with the user.
  - Note: not checked. `/verify` passes, with mypy on 3.11, 3.12 and 3.13, and every refactor commit has passing exact-head CI. Two clauses need the user:
    - The allowlist holds the 13 out-of-scope functions under 200 lines, each with its reason, plus `llm/structure.py::propose_llm_contents_boundaries` (234 lines). That one is over the 200-line threshold but isn't in spec §1, and the user hasn't decided its scope.
    - The "Found during split" list hasn't been reviewed with the user yet.

## Acceptance gate

- Every function in spec §1, and every step extracted from it, is at most 100 lines, or is allowlisted with a recorded reason.
- The length guard passes, and it is shown to fail when a listed function grows.
- The golden snapshot and the characterization tests were committed before LF1, and pass unchanged at every commit.
- No existing test was edited, and no persisted-format constant changed.
- `/verify` and exact-head CI pass for every refactor commit.

## Found during split

Bugs or questionable behaviour noticed while reading, for a separate fix round (spec §5). Record each with `file:line` and a concrete scenario.

- `src/pdf2audiobook/pipeline.py:582-604` (hand-edit merge): a title-only edit on chapter 2 fails with "Edited boundaries conflict for chapter(s) 2" when reanalysis drops the unedited chapter 1. A title-only edit shouldn't produce a boundary conflict. Pinned by `tests/test_hand_edit_merge_characterization.py::test_unedited_chapter_without_a_match_is_skipped`.
- `tests/fixtures/golden/novel.epub` (the synthetic EPUB from `tests/epub_book.py`): analysis yields three one-block chapters titled "Chapter 4", "Chapter 5" and "Chapter 6" before the real chapters 1–6. Those look like contents entries opening chapters. Pinned by the golden snapshot.
- `src/pdf2audiobook/llm/cache.py:384-402`: dead code. The no-ledger budget checks can't run, because any budget creates a temporary ledger (`cache.py:52-57`).
- `src/pdf2audiobook/llm/cache.py:376`: shadowed. An earlier check raises "A bounded output token cap is required under an LLM budget" first.
- `src/pdf2audiobook/pipeline.py:640`: the merge's own range guard can't be reached through a saved manifest, because `read_manifest` rejects the range first. After the split it is in `_queue_hand_edits`.
- `src/pdf2audiobook/llm/cache.py` (`_complete_json_call`): neither fail-closed order had a test (see LF3.02). This is a coverage gap, not a bug; characterization tests now pin both orders (876dbe2cb0db67b996a51a153d7ff729fa96863e).
- `docs/MAINTAINER_GUIDE.md` ("Architecture and extension points"): it says `PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT` is in `document/structure.py`. The tie-break that uses it is in `document/pagination.py`, which defines its own copy of the constant; `structure.py` has a second, unused copy.

## Progress ledger

| Date | Commit SHA | Completed tasks | Tests/CI evidence | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-13 | Not committed | Spec and TODO drafted; no work started. Baseline line counts: `_analyze_book_locked` 553, `propose_chapters` 448, `pagination_cleanup` 437, `_convert_analyzed_book` 421, `synthesize_chunks` 308, `_complete_json_call` 264, `_complete_json_request` 262, `extract_pdf` 225, `convert` 205 (140-line body) | Not run | LF0 safety net |
| 2026-11-13 | f64e335a9820724c6c4afefb0b92f4dbba0e7b95 | LF0.01 (length guard), LF0.02a (golden snapshot), LF0.03 (coverage and 21 characterization tests). LF0.02b open (CI) | Guard e83a8c00e34ae41cde9974f4915aea3810577b29: fails on growth (438) and on a new 102-line function. Snapshot dd5f149926dd187e6c83dfe50e2abf92f513c32e: passes twice locally and on 3.12/3.13 offline. Local `/verify` at f64e335: ruff, format (367 files), mypy (46 files, also 3.12 and 3.13), pytest 2036 passed and 1 skipped (Kitten smoke, opt-in), CLI smoke. CI not run (not pushed) | LF0.02b CI and the checkpoint need a push; scope question for `propose_llm_contents_boundaries` |
| 2026-11-13 | 27d950a04e38f312033792036ab5d59c125c398b | LF0.02b: golden snapshot and characterization tests confirmed in CI on 3.11, 3.12 and 3.13; checkpoint met | Exact-head Python CI [43371140000](https://github.com/ekkus93/pdf2audiobook/actions/runs/43371140000) passed (tests 3.11, 3.12, 3.13) | None |
| 2026-11-13 | 4b761474e0c1c0bff4a30f8ca843c9a8e1b9e9ea | LF1.01: `pagination_cleanup` 437 → 62 lines (longest step 61) | `/verify` 2036 passed, 1 skipped (Kitten smoke, opt-in); mypy on 3.11, 3.12 and 3.13; old and new matched on 7,000 generated inputs; exact-head Python CI [43371719157](https://github.com/ekkus93/pdf2audiobook/actions/runs/43371719157) passed | None |
| 2026-11-13 | b0beee3b161fe8a25d256493698aa956f603c0eb | LF1.02: `propose_chapters` 448 → 46 lines (longest step 55) | `/verify` 2036 passed, 1 skipped; mypy on 3.11, 3.12 and 3.13; old and new matched on all 255 calls the suite makes; exact-head Python CI [43372183567](https://github.com/ekkus93/pdf2audiobook/actions/runs/43372183567) passed | None |
| 2026-11-13 | 64125110cb030b02abee26117a05ff670ae582d4 | LF2.01: `_analyze_book_locked` 553 → 31 lines (longest step 90); the 21 patched `pipeline` names still take effect | `/verify` 2036 passed, 1 skipped; mypy on 3.11, 3.12 and 3.13; the 46 test files that patch `pipeline` pass (263 tests); exact-head Python CI [43372579420](https://github.com/ekkus93/pdf2audiobook/actions/runs/43372579420) passed | None |
| 2026-11-13 | d28c9b99ff5664c53fdb9bb30b96eff723f06cb2 | LF2.02: `conversion._convert_analyzed_book` 421 → 86 lines | `/verify` 2036 passed, 1 skipped (FFmpeg-gated tests ran); mypy on 3.11, 3.12 and 3.13; exact-head Python CI [43372876736](https://github.com/ekkus93/pdf2audiobook/actions/runs/43372876736) passed | None |
| 2026-11-13 | ea53f56a8bf5115d8c9d24bda3ef8faa87f6d59d | LF3.01: `synthesize_chunks` 308 → 95 lines | `/verify` 2036 passed, 1 skipped; mypy on 3.11, 3.12 and 3.13; 1,500 differential trials matched; exact-head Python CI [43373362904](https://github.com/ekkus93/pdf2audiobook/actions/runs/43373362904) passed | LF5.03 needs the user |
| 2026-11-13 | 55603b1bac28145f1b393ad0635af19e0b71134e | LF3.02: `_complete_json_call` 264 → 35 lines; plus 876dbe2cb0db67b996a51a153d7ff729fa96863e, 2 characterization tests of the fail-closed order (pushed with it, no run of its own) | `/verify` 2038 passed, 1 skipped; each new test fails against its mutant; exact-head Python CI [43374161163](https://github.com/ekkus93/pdf2audiobook/actions/runs/43374161163) passed | LF5.03 needs the user |
| 2026-11-13 | 819d364a055f3fa7c8666fe0fa2aecfea146e9d5 | LF3.03: `_complete_json_request` 262 → 56 lines; explicit `_Attempt`, typed dispatcher | `/verify` 2038 passed, 1 skipped; 4,000 differential trials matched; exact-head Python CI [43374666980](https://github.com/ekkus93/pdf2audiobook/actions/runs/43374666980) passed | LF5.03 needs the user |
| 2026-11-13 | f9a8c3a0f2bae2b48afccaa17c13b0d670b30973 | LF4.01: `extract_pdf` 225 → 41 lines | `/verify` 2038 passed, 1 skipped (Tesseract tests ran); old and new matched on every fixture and generated document; exact-head Python CI [43374927081](https://github.com/ekkus93/pdf2audiobook/actions/runs/43374927081) passed | LF5.03 needs the user |
| 2026-11-13 | f2a90664866141238481ecffdbe1137cf490947b | LF4.02: `convert` body 140 → 67 lines | `/verify` 2038 passed, 1 skipped; `--help` identical; 600 differential CLI runs matched; exact-head Python CI [43375191668](https://github.com/ekkus93/pdf2audiobook/actions/runs/43375191668) passed | LF5.03 needs the user |
| 2026-11-13 | 2cb1f1f42b585fb4782d4659f9ec57ff597b80c8 | LF5.01: MAINTAINER_GUIDE orchestrators and length guard; allowlist reasons. LF5.02: all 44 version, schema and sidecar literals unchanged since the baseline | Docs and test comment only; exact-head Python CI [43375326880](https://github.com/ekkus93/pdf2audiobook/actions/runs/43375326880) passed | LF5.03 needs the user |
