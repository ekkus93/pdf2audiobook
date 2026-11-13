# PDF2Audiobook — Inspect Conversion Status Size TODO

**Status:** R1–R2 implemented in 19dc01b and verified by CI run 43350264347; reopened by the post-implementation review (spec §7): FX11.01a, FX11.01 and FX11.05 (R3–R5) are open
**Date:** 2026-11-13
**Specification:** `docs/PDF2AUDIOBOOK_INSPECT_STATUS_SIZE_SPEC.md` (R1–R2)
**Review source:** Fourth-review audit of `docs/PDF2AUDIOBOOK_FOURTH_REVIEW_TODO.md`, finding FX10.27b's remaining `inspect` size-check race.

## Working rules

- Work in dependency order. Check a parent only when all subtasks are complete.
- Add the deterministic regression tests first and demonstrate that they fail
  on the parent revision. Record the test node IDs and failing behavior in
  the ledger.
- Keep the fix focused on conversion status loading in `inspect`. Do not
  change `load_bounded_json()` or its cache callers' malformed-file behavior.
- Extend `tests/test_inspect_conversion_status.py` rather than duplicating
  it; keep its existing tests' inputs and assertions unchanged.
- Run the relevant tests after the fix, then run the repository `/verify`
  workflow. Keep CI offline and include any gated skip reasons in the evidence.
- Use one focused Conventional Commit per fix. Record full 40-character
  commit SHAs and actual CI run IDs in append-only ledger entries; include
  failed CI attempts.

## Phase FX11 — Inspect status size race

### Regression tests

- [ ] FX11.01 Add deterministic coverage for R1 and R2 (spec §4).
  - [ ] FX11.01a Human mode: an oversized status file gives the fixed
    message with exit 3.
    - Evidence: `tests/test_inspect_conversion_status.py::test_oversized_conversion_status_in_human_mode_is_a_fixed_error` (exit 3, stderr starts with "Error:", content-free).
    - Note: reopened by the post-implementation review. Spec §4.1 asks for a file one byte above 1 MiB, but `_OVERSIZED_STATUS` (tests/test_inspect_conversion_status.py:67) is 1 MiB plus two bytes; limit+1 is tested only in tests/test_jsonio.py. Closed by FX11.05b (spec R4).
  - [x] FX11.01b `--json` mode: keep the existing
    `test_inspect_rejects_oversized_conversion_status_file` unchanged. Add a
    test asserting stderr is exactly one JSON value with no path, file
    content, or errno text.
    - Evidence: Existing test unchanged; added `tests/test_inspect_conversion_status.py::test_oversized_conversion_status_json_error_is_one_content_free_value` (`json.loads(stderr)`, empty stdout, no path/filename/errno).
  - [x] FX11.01c Exact limit: a valid JSON object padded with whitespace to
    exactly 1,048,576 bytes is included in the CLI output.
    - Evidence: `tests/test_inspect_conversion_status.py::test_conversion_status_of_exactly_the_limit_is_included` (asserts the file is exactly `CONVERSION_STATUS_MAX_BYTES` bytes).
  - [x] FX11.01d Cover valid normal-sized status inclusion, missing-file
    behavior, and malformed/over-depth input without mislabeling it as too
    large.
    - Evidence: Normal size: existing `tests/test_inspect_conversion_status.py::test_inspect_json_includes_failed_chapter_report`. Missing, malformed, non-object and over-depth (list and object): `tests/test_inspect_conversion_status.py::test_missing_malformed_and_over_depth_status_is_omitted_not_oversized` (5 cases; exit 0, no `conversion_status`, no size message).
  - [x] FX11.01e Unreadable file: a `PermissionError` at the open/read
    boundary omits the status and `inspect` exits 0, not 1 with "A
    filesystem operation failed".
    - Evidence: `tests/test_inspect_conversion_status.py::test_unreadable_conversion_status_is_omitted` (`PermissionError` from both `Path.stat` and `Path.open` for the status file, as for an unreadable `reports/` directory).
  - [x] FX11.01f Race: monkeypatch `Path.stat` (or the open boundary) so the
    initial size observation looks small while the file read is over the
    limit. Assert the fixed size error. No sleeps or timing races.
    - Evidence: `tests/test_inspect_conversion_status.py::test_status_that_grows_after_a_size_observation_is_reported_oversized` (monkeypatched `Path.stat` reports 2 bytes while the file is over the limit; no sleeps).
    - Note: met as written, but the post-implementation review found it only catches a `Path.stat`-based check. A version that pre-checks with `os.stat` and silently omits an oversized read passes every test in the file. Strengthened by FX11.05a (spec R3).
  - [x] FX11.01g Confirm that the race test (FX11.01f) and the
    unreadable-file test (FX11.01e) fail against the parent revision. Record
    the node IDs and failure modes (status silently omitted; exit 1).
    - Evidence: Run against the fix's parent d4c0aae (also before rebasing onto origin/master): `test_status_that_grows_after_a_size_observation_is_reported_oversized` failed with `assert 0 == 3` (status silently omitted); `test_unreadable_conversion_status_is_omitted` failed with exit 1, "A filesystem operation failed". The other 11 tests in the file passed.

### Implementation

- [x] FX11.02 Make the size decision from the bounded read of one open handle.
  - [x] FX11.02a In `jsonio.py`, factor the open-and-read-`limit + 1` step
    into a private helper shared with `load_bounded_json()`. Leave
    `load_bounded_json()`'s signature and behavior unchanged.
    - Evidence: `jsonio._read_at_most` and `_decode_bounded`, shared by `load_bounded_json` (signature unchanged); fix commit 19dc01be16ee10a479434fe407733cb8c2167ca6.
  - [x] FX11.02b Add a public bounded loader that raises a dedicated
    too-large exception (for example `JSONTooLargeError`) when more than the
    limit is read, and otherwise matches `load_bounded_json()`.
    - Evidence: `jsonio.load_size_checked_json` raises `JSONTooLargeError`; `tests/test_jsonio.py::test_size_checked_json_raises_only_when_the_read_exceeds_the_limit` (also asserts `load_bounded_json` still returns `None` for the same over-limit file).
  - [x] FX11.02c In `inspect`, catch that exception and raise
    `InputError("Conversion status file exceeds safe size limit")` (exit 3).
    - Evidence: `cli.py` `inspect` maps `JSONTooLargeError` to the fixed `InputError` (`from None`); FX11.01a, FX11.01b and FX11.01f tests.
  - [x] FX11.02d Define the 1 MiB limit once as a named constant and use it
    for the read bound and in the boundary tests.
    - Evidence: `cli.CONVERSION_STATUS_MAX_BYTES`; the inspect tests import it for their boundary payloads.
  - [x] FX11.02e Preserve missing-file, malformed JSON, over-depth,
    non-object, and unreadable behavior (all omitted). Keep paths and OS
    details out of user-facing errors.
    - Evidence: FX11.01d and FX11.01e tests pass; `_assert_content_free` checks the error output.
  - [x] FX11.02f Remove the separate `stat()`-then-read decision. Make sure
    handles close on success and failure.
    - Evidence: The `stat()` call is gone from `inspect`; `tests/test_jsonio.py::test_size_checked_json_closes_its_handle_on_every_path` checks the read handle is closed after a success, an over-limit read and a malformed read.

### Documentation

- [x] FX11.03 Record the known FIFO limitation (spec §5) in
  `docs/MAINTAINER_GUIDE.md`: a non-regular status file can make `inspect`
  block, before and after this change.
  - Evidence: MAINTAINER_GUIDE.md, "Workspace, review and cache contracts": the read rule, the exit code, the omitted cases and the FIFO limitation; fix commit 19dc01be16ee10a479434fe407733cb8c2167ca6.

### Verification and closure

- [x] FX11.04 Verify and record evidence.
  - [x] FX11.04a Run the focused `inspect` tests and confirm the boundary,
    unreadable and race cases.
    - Evidence: `uv run --extra dev pytest -q tests/test_inspect_conversion_status.py tests/test_jsonio.py`: 17 passed.
  - [x] FX11.04b Run `/verify`, including Ruff, format, mypy, and the full
    offline pytest suite.
    - Evidence: `/verify` at 19dc01be16ee10a479434fe407733cb8c2167ca6: lock check, sync, ruff, format (361 files), mypy (46 files; also clean with `--python-version 3.12` and `3.13`), pytest 1995 passed and 12 skipped, CLI smoke (`--help`, `config show --json`, `doctor --json`) all pass.
  - [x] FX11.04c Confirm any environment-gated tests are reported accurately;
    do not claim they ran when skipped.
    - Evidence: The 12 skips are 11 Tesseract tests (Tesseract not installed locally) and 1 Kitten smoke (extra not installed); none exercise `inspect`. FFmpeg is installed locally and its tests ran.
  - [x] FX11.04d Append the local and CI results, the full fix SHA, and real
    run IDs to the ledger; check FX11 only when all acceptance criteria pass.
    - Evidence: Python CI [43350264347](https://github.com/ekkus93/pdf2audiobook/actions/runs/43350264347) on head 16e98a56bf85a4c0f9f50da9b3792970b2909624 (the fix plus a TODO-only docs commit; no separate run exists for 19dc01b because the three commits were pushed together) passed on Python 3.11, 3.12 and 3.13: 2006 passed and 1 skipped (the opt-in Kitten smoke) on each, so the Tesseract-gated tests that skip locally ran in CI; Ruff, format, mypy, CLI smoke and wheel/sdist clean-environment smoke passed. Ledger rows for 19dc01be16ee10a479434fe407733cb8c2167ca6 (local) and the CI run.

### Review follow-up (spec §7)

- [ ] FX11.05 Close the post-implementation review findings (R3–R5). Test and docs changes only; no runtime behaviour change.
  - [x] FX11.05a R3: add a CLI test that starts with a small valid status file and wraps `Path.open` (filtered to the status file name) so the file grows past `CONVERSION_STATUS_MAX_BYTES` just before the handle is returned. Assert exit 3, the fixed message and content-free `--json` output. Keep the existing race test unchanged. No sleeps.
    - Evidence: `tests/test_inspect_conversion_status.py::test_status_that_grows_before_it_is_read_is_reported_oversized`: the file starts as `{"chapters": []}`, and a `Path.open` wrapper (status file only, read modes only) rewrites it to `_OVERSIZED_STATUS` just before the real open. Asserts exit 3, the fixed message and content-free JSON. The existing race test is unchanged. Commit 5581cb4c61ea26229a97f078ec7fe0b3ba020d53.
  - [x] FX11.05b R4: add a human-mode CLI test with a status file of exactly `CONVERSION_STATUS_MAX_BYTES + 1` bytes, asserting that length, exit 3 and the fixed message. Keep `_OVERSIZED_STATUS` and the existing tests unchanged.
    - Evidence: `tests/test_inspect_conversion_status.py::test_status_one_byte_over_the_limit_is_a_fixed_error_in_human_mode` asserts `len(status) == _STATUS_LIMIT + 1`, exit 3, "Error:" and the fixed message. `_OVERSIZED_STATUS` is unchanged. Commit 5581cb4c61ea26229a97f078ec7fe0b3ba020d53.
  - [x] FX11.05c Show the FX11.05a test fails against the reviewer's mutant in a scratch worktree, and at d4c0aae. The mutant pre-checks with `os.stat(status_path).st_size` (catching `OSError`) and uses `except JSONTooLargeError: conversion_status = None`. Record both failures in the ledger.
    - Evidence: Ran in scratch worktrees. Against the reviewer's mutant (HEAD plus an `os.stat` pre-check catching `OSError`, and `except JSONTooLargeError: conversion_status = None`), only `test_status_that_grows_before_it_is_read_is_reported_oversized` failed (1 failed, 14 passed); the old race test passed there. At d4c0aae it failed with `assert 0 == 3` (status silently omitted), alongside the two FX11.01 regressions (3 failed, 12 passed). The limit+1 test passes at d4c0aae too, because that boundary was already handled.
  - [x] FX11.05d R5: in `docs/MAINTAINER_GUIDE.md`, reword "even if the file grew after an earlier size check" (around line 347) to say the decision comes from the bytes read. Add "non-object" to the list of cases where the status is left out (around line 349).
    - Evidence: `docs/MAINTAINER_GUIDE.md`: "The decision is made from the bytes read, so a file that grows or is replaced before it is read is still reported", and "non-object" added to the cases left out. Commit 5581cb4c61ea26229a97f078ec7fe0b3ba020d53.
  - [ ] FX11.05e Run `/verify`, push, and record exact-head CI for the follow-up commit. Then re-check FX11.01a and FX11.01, citing FX11.05b, and set both status lines (this TODO and the spec) to complete.

## Acceptance gate

- `inspect` detects oversize from the bytes read from its open file handle,
  including a deterministic replacement/growth case.
- A file over 1 MiB produces the fixed error with exit 3 in human and JSON
  modes.
- A file of exactly 1 MiB holding a valid object is included.
- Valid, missing, malformed, over-depth, and unreadable file behavior matches
  the spec; an unreadable file no longer fails with "A filesystem operation
  failed".
- `load_bounded_json()` is unchanged for existing callers.
- Relevant tests and `/verify` pass; the ledger records actual evidence.

Review follow-up gate (spec §7):

- the R3 test fails against the reviewer's mutant and at d4c0aae, and passes at HEAD;
- the R4 test asserts a file of exactly `CONVERSION_STATUS_MAX_BYTES + 1` bytes;
- existing tests are unchanged;
- `/verify` and exact-head CI pass.

## Progress ledger

| Date | Commit SHA | Completed tasks | Tests/CI evidence | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-13 | Not committed | Spec and TODO drafted; implementation not started. | Not run | FX11.01 regression tests |
| 2026-11-13 | 19dc01be16ee10a479434fe407733cb8c2167ca6 | FX11.01–FX11.03, FX11.04a–c: `inspect` decides oversize from one bounded read (`jsonio.load_size_checked_json`); unreadable status omitted; FIFO limitation documented | Failed at the fix's parent d4c0aae: `test_status_that_grows_after_a_size_observation_is_reported_oversized` (status omitted, exit 0), `test_unreadable_conversion_status_is_omitted` (exit 1). After: `/verify` green on the rebased tree, 1995 passed and 12 skipped (11 Tesseract, 1 Kitten); mypy clean on 3.11–3.13. CI not run (not pushed) | FX11.04d: CI evidence needs a push |
| 2026-11-13 | 16e98a56bf85a4c0f9f50da9b3792970b2909624 | FX11.04d: CI evidence for the FX11 fix (19dc01be16ee10a479434fe407733cb8c2167ca6) | Python CI [43350264347](https://github.com/ekkus93/pdf2audiobook/actions/runs/43350264347) on head 16e98a56bf85a4c0f9f50da9b3792970b2909624 (the fix plus a TODO-only docs commit; no separate run exists for 19dc01b because the three commits were pushed together) passed on Python 3.11, 3.12 and 3.13: 2006 passed and 1 skipped (the opt-in Kitten smoke) on each, so the Tesseract-gated tests that skip locally ran in CI; Ruff, format, mypy, CLI smoke and wheel/sdist clean-environment smoke passed | None |
| 2026-11-13 | 904f4c04a73bf4b1378e2e50daaa2c3c63315552 | Post-implementation review of 19dc01be16ee10a479434fe407733cb8c2167ca6 (spec §7). The fix is correct, and `load_bounded_json()` matched the old version on 15 edge cases. Reopened FX11.01a and FX11.01 (CLI boundary is limit+2, not limit+1). Added FX11.05 (R3 race-test strength, R4 limit+1 CLI test, R5 docs wording) | Reviewer reran the 17 inspect/jsonio tests at HEAD (all passed) and the new tests at d4c0aae (the race and unreadable tests failed as recorded). A racy mutant using `os.stat` passed all 13 inspect tests. CI run 43350723813 on 904f4c0 succeeded | FX11.05 |
| 2026-11-13 | 5581cb4c61ea26229a97f078ec7fe0b3ba020d53 | FX11.05a–d: open-boundary growth race test, exact limit+1 CLI test, MAINTAINER_GUIDE wording (spec R3–R5) | The new race test fails against the reviewer's `os.stat` mutant (the only failure there) and at d4c0aae (`assert 0 == 3`). Local `/verify`: ruff, format (361 files), mypy (46 files, also 3.12 and 3.13), pytest 1997 passed and 12 skipped (11 Tesseract, 1 Kitten), CLI smoke. CI not yet run | FX11.05e: push and exact-head CI |
