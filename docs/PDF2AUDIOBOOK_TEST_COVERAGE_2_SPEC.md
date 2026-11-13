# PDF2Audiobook — Test Coverage Specification, Round 2

**Status:** Draft; U1–U10 not implemented
**Date:** 2026-11-13
**Baseline:** master at 59e64c71fd076f295973474eafbc98cb781f1316
**Parent specification:** `docs/PDF2AUDIOBOOK_SPEC.md` (§12 engineering principles)
**Previous round:** `docs/PDF2AUDIOBOOK_TEST_COVERAGE_SPEC.md` (T1–T9, complete)
**Companion:** `docs/PDF2AUDIOBOOK_TEST_COVERAGE_2_TODO.md`

## 1. Purpose and scope

After the first round, branch coverage is 95% overall (2246 passed, 1 skipped). The remaining gaps that matter most are in code that guards the user or their files: the review web server, protection of hand-edited chapter files, the Piper TTS adapter, checking of LLM contents answers, and the footnote setting against approved edits. Two small utility modules, `jsonio.py` and `audio/wav.py`, also have untested refusal paths.

This work adds tests for those paths. **It is tests only: no source change.** If a test shows that the code is wrong, record it (§5) for a separate fix and mark the test `xfail(strict=True)` with the recorded reason.

| ID | Module | Coverage at baseline | What is untested |
| --- | --- | --- | --- |
| U1 | `src/pdf2audiobook/review_ui.py` | 91% | Review server refusals: auth encoding, unknown API routes, bad `Content-Length`, manifest race, chapter identity, voice ID, host forms |
| U2 | `src/pdf2audiobook/chapter_artifacts.py` | 90% | Hand-edit conflicts, unsafe chapter files, invalid metadata, planning guards |
| U3 | `src/pdf2audiobook/tts/__init__.py` | 88% | `PiperTTS` construction, input and output checks |
| U4 | `src/pdf2audiobook/llm/structure.py` | 90% | Rejections of LLM contents entries, boundaries and windows |
| U5 | `src/pdf2audiobook/analysis_state.py` | 90% | Footnote setting against approved edits; stage and chapter matching edges |
| U6 | `src/pdf2audiobook/jsonio.py` | 93% | Escaped quotes in the depth scan, unbalanced closers, invalid bounds |
| U7 | `src/pdf2audiobook/audio/wav.py` | 86% | WAV creation failure, invalid sample chunks, silence size limit |

Coverage is the combined statement and branch figure from `coverage report`. U8–U10 are cross-cutting (§4).

**Out of scope:** changing any source file; `chapter_selection.py`, `special_material.py`, `logging.py`, `audio/freshness.py` and `cli.py` (lower risk; a later round can take them); adding `coverage` or `pytest-cov` as a dependency; a coverage threshold in CI; tests that need the network, a live LLM, a real Piper install or the real Kitten model.

## 2. Ground rules

- **Tests only.** No file under `src/` changes. Bugs found go to §5.
- **Assert behaviour, not lines.** Each test asserts the observable outcome: the exception type and its fixed message, the HTTP status and body, the returned value, the review decision, or the files left on disk. Executing a line is not enough.
- **Privacy.** Every new error-path test also asserts that the message or response holds no path, file name, book text or OS error text.
- **Offline and deterministic.** No fixed sleeps or timing races. The review server tests use `port=0` and a daemon thread, as `tests/test_review_ui.py` does, and always shut the server down. Piper is replaced by a stand-in for `shutil.which` and `subprocess.run` (the pattern in `tests/test_piper_provider.py`); no real `piper` runs. LLM answers come from a fake provider.
- **Unreachable code is shown, not mocked.** If a branch can't be reached through real inputs, record why in §5. Don't reach it by mocking the standard library.
- **Extend before adding.** Put tests in the existing file for that module (§3). New files follow `tests/test_<area>_<topic>.py`.
- **One area per commit:** `test(<scope>): cover <area>`. Each commit passes `/verify` and mypy on 3.11, 3.12 and 3.13.

Line numbers below are at the baseline.

## 3. Requirements

### U1 — Review server (`review_ui.py`)

Existing tests: `tests/test_review_ui.py`, `tests/test_review_save_outcomes.py`, `tests/test_cli_review_shutdown_and_secrets.py`.

- **U1.a Authorization encoding** (lines 245–246): `_authorized` refuses an `Authorization` value that can't be encoded as Latin-1. The existing test sends `\xff`, which encodes and fails the comparison instead. `http.server` decodes headers as Latin-1, so this branch may be unreachable over HTTP; show a request that reaches it or record it in §5.
- **U1.b Unknown API route** (line 301): an unauthenticated GET to an `/api/` path other than the manifest returns 401 with `{"error": "Unauthorized"}`, and an authenticated one returns 404. Neither body holds book text.
- **U1.c Bad `Content-Length`** (lines 316–317): a POST whose `Content-Length` isn't an integer returns 413 with the fixed message, and the manifest is unchanged.
- **U1.d Save guards** (lines 163, 168, 191): `save_chapter_updates` refuses, with its fixed `ExtractionError` and the manifest unchanged:
  - a manifest that changes between the two digest reads ("Manifest changed during review; retry");
  - an update whose entry isn't an object or whose `id` doesn't match the chapter in that position;
  - a voice ID that isn't a string or is longer than 128 characters.
- **U1.e Host forms** (lines 218–225): `create_review_server` accepts `LOCALHOST` (any case), refuses a host name that isn't an IP address or `localhost` with the loopback message, and refuses `::1` with the IPv6 message.

### U2 — Hand-edit protection (`chapter_artifacts.py`)

Existing tests: `tests/test_chapter_artifact_plan.py`, `tests/test_legacy_footnote_policy.py`, `tests/test_noop_publication.py`.

- **U2.a Unsafe chapter file** (lines 44–49): a chapter path that is a symlink or a directory raises "Cannot inspect chapter text; check workspace files", and nothing outside the workspace is read or written.
- **U2.b Invalid metadata** (lines 86, 103): a chapter metadata file whose top level is malformed, and one whose chapter record has a wrong type or missing field, each raise "Chapter artifact metadata is invalid; restore it from a backup" with files unchanged. Parametrize over the fields checked at lines 90–103.
- **U2.c Planning guards** (lines 188, 196, 199): an unknown footnote policy, metadata that changes during planning, and duplicate chapter IDs each raise their fixed error before anything is written.
- **U2.d Conflicts** (lines 127, 207, 233–243, 270): each case below is reported as a conflict for its chapter number, and the user's file is not overwritten or deleted:
  - a chapter moved to a number whose file belongs to another chapter that was hand edited;
  - a new chapter number whose existing file differs from the generated text;
  - a hand-edited chapter whose file was deleted;
  - a stale numbered file left over from a removed chapter, when that file was edited.

  Also cover a chapter named in `force` being skipped by the edit check, and the footnote-policy resolution that drops `warn` when anchor edits exist (line 127).

### U3 — Piper adapter (`tts/__init__.py`)

Existing tests: `tests/test_piper_provider.py`, `tests/test_convert_robustness_fx9.py`.

- **U3.a Construction** (lines 192, 194, 200, 203–204): a missing model file, a missing executable, a voice config over 1 MiB, and a config without a valid sample rate each raise their fixed `AudioError`. The `bool`, non-integer and out-of-range rate cases at line 203 are covered with one parametrized test, unless an existing test already covers them.
- **U3.b Input checks** (lines 210, 213, 216, 220): empty, whitespace-only and over-long text; a speed that is `bool`, non-finite, zero or above 3; and a speaker ID that isn't decimal or is longer than 10 characters. Each raises its fixed `AudioError` before the subprocess runs; assert the subprocess stand-in was not called.
- **U3.c Output checks** (lines 247, 254, 257, 260, 263): the stand-in writes a WAV that is missing, too large, has the wrong rate, channel count or sample width, has zero frames, or is truncated. Each raises its fixed `AudioError`, and the temporary directory is removed.
- **U3.d** `list_models`, `list_voices` and `health` return the documented values with and without the model and executable.

### U4 — LLM contents review (`llm/structure.py`)

Existing tests: `tests/test_llm_contents_boundaries.py`, `tests/test_llm_bounded_windows.py`.

- **U4.a Entry rejections** (lines 167, 238–251): in `_check_contents_entry`, a contents entry whose source line has no trailing page number is recorded as `rejected` with `contents_title_mismatch` (because `_parse_contents_line` returns `None`); one whose page reference doesn't match the line, as `contents_page_reference_mismatch` with its fixed warning; and one with confidence below 0.75, as `low_confidence`. None of them becomes a verified entry.
- **U4.b Boundary rejection** (lines 309–316): a boundary below 0.75 confidence is recorded as `low_confidence` and does not add boundary evidence.
- **U4.c Window rejections** (lines 337–343, 358–365): a window that is empty because its block is oversized, and a provider answer that fails the response schema, are each recorded against `window:<start>` with their fixed warnings, and analysis continues with the next window.
- **U4.d Low-confidence heading** (line 146): in `detect_llm_headings`, a heading that names its source line but has confidence below 0.75 is not approved and is recorded as `rejected` with `low_confidence`.

### U5 — Analysis state (`analysis_state.py`)

Existing tests: `tests/test_legacy_footnote_policy.py`, `tests/test_pipeline_footnote_warning_preservation.py`, `tests/test_review_followup_regressions.py`.

- **U5.a Footnote setting vs approved edits** (lines 89, 101): changing the footnote setting to `omit` when an omit edit would hit a block with an accepted cleanup edit raises "Footnote policy conflicts with an approved cleanup edit; use a new output directory". A manifest whose footnote edits don't match what the previous setting generates raises "Footnote policy conflicts with protected cleanup decisions; use a new output directory". In both cases the manifest on disk is unchanged.
- **U5.b** Line 127: switching to `end` adds the warning that names how many footnotes moved.
- **U5.c** Line 61 and branch 38→47: a missing or malformed `reports/analysis_fingerprints.json` reports every stage as changed (`["analysis"]`); the rejected-edit preservation skips edits as the branch at line 38 describes.
- **U5.d** Line 153: a hand-edited chapter whose generated start block is missing or beyond the previous manifest's blocks is not matched (`None`), and the hand-edit conflict path then reports it.

### U6 — Bounded JSON (`jsonio.py`)

Existing tests: `tests/test_jsonio.py`, `tests/test_cache_depth_reaches_check.py`.

- **U6.a Escaped quotes** (lines 30–32): strings containing `\"`, `\\` and `\"]` or `\"}` don't change the counted depth. A document at exactly the depth limit loads, and one past it is a miss.
- **U6.b Unbalanced closer** (line 45): a payload with a closing bracket before any opener is a miss, not an error.
- **U6.c Invalid bounds** (line 76): `load_bounded_json` and `load_size_checked_json` raise "JSON bounds must be non-negative integers" for a `bool`, non-integer or negative `max_depth`, and for a `bool`, non-integer or zero `max_bytes`.

### U7 — Chapter WAV writer (`audio/wav.py`)

Existing tests: `tests/test_long_chapter_wav_streaming.py`.

- **U7.a** (lines 36–37): `_open_streaming_wav` raises "Could not create temporary chapter WAV" when the folder can't be created or the file can't be opened. Simulate it with a file in place of the parent folder, not by mocking `wave`.
- **U7.b** (lines 43–46): `_write_pcm_chunk` raises "TTS returned invalid audio sample data" for samples that can't be converted, and "TTS returned invalid mono audio samples" for a 2-D, empty or non-finite buffer. Nothing is written in either case.
- **U7.c** (line 57): `_write_silence` raises the RIFF size-limit error when the silence would exceed the limit, without writing. Set `bytes_written` near the limit instead of writing 4 GiB.

## 4. Cross-cutting requirements

- **U8 Mutation proof.** For every requirement, break the code it covers in place (one deliberate change, such as removing a check, inverting a condition or changing a message), run the new tests with `PYTHONDONTWRITEBYTECODE=1`, confirm at least one fails for the expected reason, and restore the file byte for byte (`cmp`). Record each break and its result in the TODO. A mutant no test can catch is either a weak test (strengthen it) or an equivalent change (record it in §5 with the reason).
- **U9 Coverage evidence.** Measure before and after with `COVERAGE_FILE=<scratchpad>/.coverage uv run --extra dev --with coverage coverage run --branch --source=src/pdf2audiobook -m pytest -q` and `coverage report`. Record each module's coverage. Target: every U1–U7 module at least 95%, except lines §5 records as unreachable.
- **U10 No regressions.** The full suite, the golden snapshot and the patch-target guard pass unchanged; no existing test is edited except to add cases.

## 5. Found while testing

Record each bug, unreachable line or equivalent mutant with `file:line`, a concrete scenario and the test (if any) marked `xfail(strict=True)`. Fixes are a separate round.

## 6. Acceptance criteria

- Every requirement in §3 has a named test and a recorded mutation result (U8).
- The coverage target in U9 is met, or each shortfall is listed in §5.
- `/verify` and exact-head CI pass for every commit.
