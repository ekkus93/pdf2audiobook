# PDF2Audiobook — Test Coverage TODO, Round 2

**Status:** Open; nothing started
**Date:** 2026-11-13
**Baseline:** master at 59e64c71fd076f295973474eafbc98cb781f1316
**Specification:** `docs/PDF2AUDIOBOOK_TEST_COVERAGE_2_SPEC.md` (U1–U10)

## Working rules

- Work in the order below. Use `[x]` only when the tests exist, pass, and have a recorded mutation result (spec U8). Check a parent only when all its subitems are checked.
- Tests only: no file under `src/` changes. A test that exposes a bug is marked `xfail(strict=True)` and the bug goes in "Found while testing".
- Every error-path test asserts the fixed message (or HTTP status and body) and that no path, file name, book text or OS error text leaks.
- Unreachable branches are shown with real inputs or recorded in "Found while testing"; never reached by mocking the standard library.
- One area per commit: `test(<scope>): cover <area>`, no body, no `Co-Authored-By` trailer. Run `/verify` and mypy on 3.12 and 3.13 before each commit.
- After CI finishes, add a ledger row in a separate `docs:` commit with the full SHA and the real run ID, to this file and to `docs/PDF2AUDIOBOOK_TODO.md`. The ledgers are append-only.

## Phase TU0 — Baseline

- [ ] TU0.01 Run the U9 coverage command at the baseline and record each target module's statements missed / total, partial branches / total and combined coverage.

## Phase TU1 — Review server (U1)

- [ ] TU1.01 U1.a: show whether `_authorized` (`review_ui.py:245-246`) can receive a header that isn't Latin-1 encodable over HTTP; test it if so, otherwise record it as unreachable in "Found while testing".
- [ ] TU1.02 U1.b: unknown `/api/` route returns 401 without a token and 404 with one; no book text in either body.
- [ ] TU1.03 U1.c: a non-integer `Content-Length` returns 413 with the fixed message; the manifest is unchanged.
- [ ] TU1.04 U1.d: `save_chapter_updates` refuses a manifest changed between digests, a non-object or mismatched-ID entry, and an invalid voice ID; the manifest is unchanged.
- [ ] TU1.05 U1.e: `create_review_server` accepts `LOCALHOST`, refuses a non-IP host name and refuses `::1`, each with its fixed message.
- [ ] TU1.06 U8 mutation results for TU1.01–TU1.05.

## Phase TU2 — Hand-edit protection (U2)

- [ ] TU2.01 U2.a: a symlinked or directory chapter path raises the fixed "Cannot inspect chapter text" error; nothing outside the workspace is touched.
- [ ] TU2.02 U2.b: malformed metadata top level, and each malformed chapter record field (parametrized), raise the fixed metadata error with files unchanged.
- [ ] TU2.03 U2.c: unknown footnote policy, metadata changed during planning and duplicate chapter IDs raise their fixed errors before anything is written.
- [ ] TU2.04 U2.d: renumbered chapter onto an edited occupant, new number with a differing file, deleted edited file, and edited stale file are each a conflict and the user's file survives; `force` skips the edit check; policy resolution drops `warn` when anchor edits exist.
- [ ] TU2.05 U8 mutation results for TU2.01–TU2.04.

## Phase TU3 — Piper adapter (U3)

- [ ] TU3.01 U3.a: missing model, missing executable, oversized config, config without a valid rate, and invalid rate values each raise their fixed `AudioError`.
- [ ] TU3.02 U3.b: invalid text, speed and speaker ID each raise their fixed `AudioError`, and the subprocess stand-in is never called.
- [ ] TU3.03 U3.c: missing, oversized, wrong-format, empty and truncated output WAVs each raise their fixed `AudioError`; the temporary directory is removed.
- [ ] TU3.04 U3.d: `list_models`, `list_voices` and `health` with and without the model and executable.
- [ ] TU3.05 U8 mutation results for TU3.01–TU3.04.

## Phase TU4 — LLM contents review (U4)

- [ ] TU4.01 U4.a: a source line without a page number (`contents_title_mismatch`), a page-reference mismatch (with its warning) and a low-confidence entry are rejected and not verified.
- [ ] TU4.02 U4.b: a low-confidence boundary is rejected and adds no boundary evidence.
- [ ] TU4.03 U4.c: an oversized-block window and a schema-invalid answer are recorded against `window:<start>` with their warnings, and the next window still runs.
- [ ] TU4.04 U4.d: a low-confidence heading in `detect_llm_headings` is rejected with `low_confidence` and not approved.
- [ ] TU4.05 U8 mutation results for TU4.01–TU4.04.

## Phase TU5 — Analysis state (U5)

- [ ] TU5.01 U5.a: both footnote-policy conflict errors, with the manifest on disk unchanged.
- [ ] TU5.02 U5.b: switching to `end` adds the moved-footnotes warning with the right count.
- [ ] TU5.03 U5.c: missing or malformed fingerprint report means every stage changed; the rejected-edit branch at line 38.
- [ ] TU5.04 U5.d: a hand-edited chapter with a missing or out-of-range generated start is unmatched and reported as a hand-edit conflict.
- [ ] TU5.05 U8 mutation results for TU5.01–TU5.04.

## Phase TU6 — Bounded JSON and WAV writer (U6, U7)

- [ ] TU6.01 U6.a: escaped quotes and backslashes don't change the counted depth; exactly at the limit loads, one past it is a miss.
- [ ] TU6.02 U6.b: a closing bracket before any opener is a miss.
- [ ] TU6.03 U6.c: invalid `max_bytes` and `max_depth` values raise the fixed bounds error from both loaders.
- [ ] TU6.04 U7.a–U7.c: WAV creation failure, invalid sample chunks and the silence size limit each raise their fixed `AudioError` without writing.
- [ ] TU6.05 U8 mutation results for TU6.01–TU6.04.

## Phase TU7 — Closure

- [ ] TU7.01 U9: rerun coverage; record each module's coverage against the 95% target, and list any shortfall in "Found while testing".
- [ ] TU7.02 U10: the full suite, golden snapshot and patch-target guard pass; `git diff` of `src/` against the baseline is empty; no existing test edited except to add cases.
- [ ] TU7.03 Final gate: `/verify` passes with mypy on 3.11, 3.12 and 3.13; exact-head CI passes for every commit; "Found while testing" is reviewed with the user.

## Found while testing

None yet.

## Progress ledger

| Date | Commit SHA | Completed tasks | Tests/CI evidence | Blockers |
| --- | --- | --- | --- | --- |
