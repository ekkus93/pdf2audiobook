# PDF2Audiobook — Long Function Split TODO

**Status:** Open; LF0.01, LF0.02a and LF0.03 done locally; LF0.02b (CI) and all splits open
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
- [ ] LF0.02 Add the golden analysis snapshot (S11).
  - [x] LF0.02a Add a characterization test that runs `analyze` with the LLM off on the synthetic fixtures (generated PDFs, `tests/fixtures/outlined_text.pdf` and the synthetic EPUB). It compares normalized `manifest.json`, chapter texts, `coverage.json`, warnings and review reasons with a committed snapshot.
    - Evidence: `tests/test_golden_analysis_snapshot.py` against `tests/fixtures/golden/analysis_snapshot.json` (7.5 KB). The generated fixtures aren't byte-deterministic (zip and PDF timestamps), so `tests/fixtures/golden/golden_book.pdf` (9 KB) and `novel.epub` (6 KB, from `tests/epub_book.py`) were generated once and committed. The snapshot records per-file digests, manifest-section digests (fingerprints included) and a readable summary. Commit dd5f149926dd187e6c83dfe50e2abf92f513c32e.
    - Note: `outlined_text.pdf` is pinned on `--ocr never`, which fails with `ExtractionError` "No text found in PDF; no chapters can be created". With OCR its text would depend on the Tesseract version: 4.1.1 here, and CI's may differ.
  - [ ] LF0.02b Confirm it passes at the baseline and is deterministic across two runs and across Python 3.11, 3.12 and 3.13 (CI).
    - Evidence (local): passed on two consecutive runs; passed on Python 3.12 and 3.13 in offline venvs (`uv run --offline --python 3.12/3.13`).
    - Note: not checked. The CI half needs these commits pushed, which hasn't been authorized in this run.
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

- [ ] LF1.01 Split `pagination_cleanup` (S1).
  - [ ] LF1.01a Extract the steps in spec §3 S1, including a named predicate for each fail-closed rule. The orchestrator and every step are at most 100 lines.
  - [ ] LF1.01b Remove it from the length allowlist. The full suite, the golden snapshot and the characterization tests pass unchanged.
- [ ] LF1.02 Split `propose_chapters` (S2).
  - [ ] LF1.02a Extract the steps in spec §3 S2. The orchestrator and every step are at most 100 lines.
  - [ ] LF1.02b Remove it from the length allowlist. The full suite, the golden snapshot and the characterization tests pass unchanged.

## Phase LF2 — Pipeline orchestrators

- [ ] LF2.01 Split `_analyze_book_locked` (S3).
  - [ ] LF2.01a Extract the steps in spec §3 S3 inside `pipeline.py`, passing shared state through a private run dataclass. Turn the nested `queue_change` and `map_boundary` into named functions.
  - [ ] LF2.01b Confirm that every `pipeline.*` name tests patch still takes effect. Grep the tests' `monkeypatch.setattr` targets for `pipeline`, and record that the targeted tests pass unchanged.
  - [ ] LF2.01c Remove it from the length allowlist. The full suite, the golden snapshot and the characterization tests pass unchanged.
- [ ] LF2.02 Split `_convert_analyzed_book` (S4).
  - [ ] LF2.02a Extract the steps in spec §3 S4. Keep the keyword parameters, and gather them into a private run dataclass inside `conversion.py`. Keep calling dependencies through `ConversionServices`.
  - [ ] LF2.02b Remove it from the length allowlist. The full suite (including the FFmpeg-gated conversion tests) and the characterization tests pass unchanged.

## Phase LF3 — Audio and LLM

- [ ] LF3.01 Split `synthesize_chunks` (S5). Keep validation that today runs before any engine call or cache replay in that position. Remove it from the allowlist; the suite passes unchanged.
- [ ] LF3.02 Split `_complete_json_call` (S6). The fail-closed order is unchanged: no reservation before the bounds check, and no cache hit that skips the oversized-request rejection. Remove it from the allowlist; the budget and cache tests pass unchanged.
- [ ] LF3.03 Split `_complete_json_request` (S7). Turn the nested settle closures into named functions or methods with an explicit attempt context, and the loop into a dispatcher over typed outcomes. Remove it from the allowlist; the provider matrix and budget tests pass unchanged.

## Phase LF4 — Extraction and CLI

- [ ] LF4.01 Split `extract_pdf` (S8). Every `pdf.*` name tests patch (`_open`, `_ocr_page_lines`, `_cached_ocr_lines`) still takes effect. Remove it from the allowlist; the suite passes unchanged, including the Tesseract-gated tests.
- [ ] LF4.02 Split the `convert` CLI command body (S9) into a `_run_convert` helper and a dry-run helper. Error handling stays in the command. Remove it from the allowlist; CLI and JSON error tests pass unchanged.

## Phase LF5 — Documentation and closure

- [ ] LF5.01 Update `docs/MAINTAINER_GUIDE.md` (S12): the analysis and conversion orchestrators and their steps, and how to use the length-guard allowlist.
- [ ] LF5.02 Confirm with `git diff 18681585b45a02b0e697b64c03ac38c513a28247 -- src` that no fingerprint, schema, cache-identity or sidecar constant changed. Record the check in the ledger.
- [ ] LF5.03 Final gate:
  - `/verify` passes, with mypy on 3.11, 3.12 and 3.13;
  - exact-head CI passes for every refactor commit;
  - the allowlist holds only out-of-scope functions, each with its reason;
  - the "Found during split" list is reviewed with the user.

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
- `src/pdf2audiobook/pipeline.py:640`: the merge's own range guard can't be reached through a saved manifest, because `read_manifest` rejects the range first.

## Progress ledger

| Date | Commit SHA | Completed tasks | Tests/CI evidence | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-13 | Not committed | Spec and TODO drafted; no work started. Baseline line counts: `_analyze_book_locked` 553, `propose_chapters` 448, `pagination_cleanup` 437, `_convert_analyzed_book` 421, `synthesize_chunks` 308, `_complete_json_call` 264, `_complete_json_request` 262, `extract_pdf` 225, `convert` 205 (140-line body) | Not run | LF0 safety net |
| 2026-11-13 | f64e335a9820724c6c4afefb0b92f4dbba0e7b95 | LF0.01 (length guard), LF0.02a (golden snapshot), LF0.03 (coverage and 21 characterization tests). LF0.02b open (CI) | Guard e83a8c00e34ae41cde9974f4915aea3810577b29: fails on growth (438) and on a new 102-line function. Snapshot dd5f149926dd187e6c83dfe50e2abf92f513c32e: passes twice locally and on 3.12/3.13 offline. Local `/verify` at f64e335: ruff, format (367 files), mypy (46 files, also 3.12 and 3.13), pytest 2036 passed and 1 skipped (Kitten smoke, opt-in), CLI smoke. CI not run (not pushed) | LF0.02b CI and the checkpoint need a push; scope question for `propose_llm_contents_boundaries` |
