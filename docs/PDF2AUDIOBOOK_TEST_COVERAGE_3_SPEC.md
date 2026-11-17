# Test Coverage Specification, Round 3

**Status:** Proposed. Adds tests for the code paths a coverage run found untested at the current head. It changes no behavior and, unless a test exposes a defect, no code under `src/`.
**Date:** 2026-11-17
**Baseline:** master head 5bbe03e (branch `tauri`). Coverage measured with `pytest --cov=pdf2audiobook --cov-report=term-missing` plus `pytest-cov`: 10,201 statements, 483 missed, 95% overall.
**Companion:** `docs/PDF2AUDIOBOOK_TEST_COVERAGE_3_TODO.md`. Earlier rounds: `PDF2AUDIOBOOK_TEST_COVERAGE_SPEC.md` and `..._2_SPEC.md`.

## 1. Goals

Cover the untested branches where a mistake would change what the user hears, what book text is sent to an LLM, what the CLI reports, or whether existing audio survives a failure. Get the most risk-reducing tests in the fewest lines. Keep every test deterministic and offline: no network, no model downloads, no real Kitten or ASR weights.

## 2. Scope and targets

The gaps, by statements missed at the baseline (only statement coverage was measured, not branches):

| Module | Missed / total | Uncovered lines | Why it matters |
|---|---|---|---|
| `verification/backends.py` | 73 / 196 (63%) | 136, 156–157, 161–166, 181, 184, 188–193, 208–218, 245–261, 264–286, 295–301, 304–321, 332–333 | Model loading, transcription and the time offsets of every recognizer. Only opt-in smoke tests reach it. |
| `llm/__init__.py` | 7 / 182 | 343–352, 479–489 | Narration proposals the LLM returns unchanged, and classifications below the confidence threshold: both are recorded as decisions. |
| `audio/commit.py` | 7 / 96 | 48–49, 119–120, 138–139, 146 | The failure and cleanup paths of the atomic chapter-audio commit, which protects existing audio. |
| `conversion.py` | 20 / 311 | 475–478 | A TTS provider that cannot be created must leave the chapter's previous audio in place. |
| `cli/verify.py` | 17 / 157 | 96, 127–136, 163, 165, 183, 293, 306, 308, 310 | The verification command's refusals and report output. |
| `cli/batch.py` | 11 / 92 | 63, 70, 85, 91, 126–129, 136, 143, 159 | Batch conversion's option refusals and per-book failures. |
| `cli/repair.py` | 7 / 44 | 45, 58, 61, 63, 90, 93, 95 | `regenerate-chapter` and `recover` refusals. |
| `cli/asr.py` | 8 / 48 | 28–33, 69, 71 | Speech-recognizer setup: the unknown-model and download-refusal paths. |

**Out of scope:**
- `llm/cache_base.py` (79%): its uncovered lines are `NotImplementedError` declaration stubs, which tests must not reach by mocking.
- Branch coverage: only statements were measured. Adding branch measurement is a separate change to the coverage command.
- Real-model accuracy and the opt-in smoke tests: unchanged.

## 3. Requirements

**R1. Recognizer backends, offline.** Each backend's `transcribe` and `_load` run against a stand-in for its library, installed as a module in `sys.modules` for the test. The stand-in returns fixed output, so the tests check:
- the time offset of each window: a word at position *t* in the window starting at offset *o* is reported at *o + t*, for every window after the first;
- Wav2Vec2's frame-to-second conversion (`inputs_to_logits_ratio / RATE`);
- Vosk's word timestamps and its stop check between blocks;
- device selection (`auto` picks CUDA only when torch reports it), thread limits, and `close()` releasing the model;
- a model that fails to load raises the documented failure, with no path or library text in the message.

**R2. LLM decision branches.** For a narration proposal whose text equals the source (the `no_change` branch) and for a classification below 0.75 confidence (the `low_confidence` branch):
- the proposal is not applied, and the block's text is unchanged;
- the decision is recorded with the stated status and reason code, and the warning names the block, not its text;
- a book-text string placed in the mock response never appears in the warnings or the decision records.

**R3. Commit recovery.** Each of the four uncovered commit paths is exercised with a real filesystem fault (a read-only folder, or a file removed mid-commit): the previous MP3 and sidecar remain as they were, the error holds no path, and a recovery run finishes or removes what the fault left behind.

**R4. Conversion with a failing TTS provider.** When creating the provider raises `AudioError`, the chapter is marked failed, its previous audio and sidecar are unchanged, and no staged file is left behind.

**R5. CLI refusals.** For each uncovered line in `cli/verify.py`, `cli/batch.py`, `cli/repair.py` and `cli/asr.py`, a test runs the command with input that reaches it and asserts:
- the exit code the code path sets;
- the JSON error on stderr (under `--json`) or the human message, with the fixed wording;
- that no path, file name, book title or OS error text appears in either.

**R6. Evidence of value.** Each new test must fail when the behavior it covers is broken. For R1–R4 this is checked by a recorded mutation: a one-line change to the covered source (for example, drop the window offset, invert the confidence comparison, skip the cleanup) is made in a scratch copy, the test fails, and the mutation is reverted. The mutation and its result are recorded as Evidence.

**R7. Measurement.** After the work, the coverage command in §2 is run again. Each target's new numbers, and the overall figure, are recorded in the TODO. A target with uncovered lines still left is recorded with the reason.

## 4. Conventions

- Tests only, unless a test exposes a defect. A test that exposes one is marked `xfail(strict=True)` and the defect is recorded in the TODO's "Found while testing" list. No source change is made without a separate decision.
- Stand-ins live in `tests/`, not in `src/`, and are installed with `monkeypatch` or `sys.modules` for the duration of one test.
- Error-path tests assert the fixed message and check that book text, paths and OS error text do not leak.
- One area per commit, `test(<scope>): cover <area>`, no body and no `Co-Authored-By` trailer.
- Each commit passes `ruff check`, `ruff format --check`, mypy on 3.11, 3.12 and 3.13, and the full pytest suite.

## 5. Acceptance

The round is complete when:
1. Every line listed in §2 is covered, or is listed in the TODO with the reason it is not.
2. Every new test passes on the head and has a recorded mutation result under R6 (for R1–R4).
3. The coverage numbers in R7 are recorded.
4. The full Python suite passes, with the same skips as before (the opt-in smoke tests only).
5. CI passes on the final commit, and the ledgers record the commit and run IDs.
