# PDF2Audiobook — Inspect Conversion Status Size TODO

**Status:** Complete; FX11.07 third-review test gaps closed (87a8b76, exact-head CI 43388294116); R1–R2 (19dc01b, verified by CI run 43350264347 on 16e98a5, which adds only a TODO change), R4–R5 (5581cb4, exact-head CI 43352750100), R3 and R6–R8 (86faa00, exact-head CI 43355049360; R6 as amended by the spec §8 decision)
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

- [x] FX11.01 Add deterministic coverage for R1 and R2 (spec §4).
  - [x] FX11.01a Human mode: an oversized status file gives the fixed
    message with exit 3.
    - Evidence: `tests/test_inspect_conversion_status.py::test_oversized_conversion_status_in_human_mode_is_a_fixed_error` (exit 3, stderr starts with "Error:", content-free).
    - Note: reopened by the post-implementation review. Spec §4.1 asks for a file one byte above 1 MiB, but `_OVERSIZED_STATUS` (tests/test_inspect_conversion_status.py:67) is 1 MiB plus two bytes; limit+1 is tested only in tests/test_jsonio.py. Closed by FX11.05b (spec R4).
    - Evidence: re-checked after FX11.05b: `tests/test_inspect_conversion_status.py::test_status_one_byte_over_the_limit_is_a_fixed_error_in_human_mode` (exactly limit+1 bytes), commit 5581cb4c61ea26229a97f078ec7fe0b3ba020d53, CI run 43352750100.
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
    - Note: to run the test file at d4c0aae, its `CONVERSION_STATUS_MAX_BYTES` import was replaced with the literal `1024 * 1024`; without that, collection fails with `ImportError` (spec §8).

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

- [x] FX11.05 Close the post-implementation review findings (R3–R5). Test and docs changes only; no runtime behaviour change.
  - [x] FX11.05a R3: add a CLI test that starts with a small valid status file and wraps `Path.open` (filtered to the status file name) so the file grows past `CONVERSION_STATUS_MAX_BYTES` just before the handle is returned. Assert exit 3, the fixed message and content-free `--json` output. Keep the existing race test unchanged. No sleeps.
    - Evidence: `tests/test_inspect_conversion_status.py::test_status_that_grows_before_it_is_read_is_reported_oversized`: the file starts as `{"chapters": []}`, and a `Path.open` wrapper (status file only, read modes only) rewrites it to `_OVERSIZED_STATUS` just before the real open. Asserts exit 3, the fixed message and content-free JSON. The existing race test is unchanged. Commit 5581cb4c61ea26229a97f078ec7fe0b3ba020d53.
    - Note: reopened by the second review (spec §8). The test is as described, but R3 requires catching *any* check-then-read design. Mutant A (`fstat` between open and read, then omit) and mutant D (size pre-check through a separate `Path.open`, then omit) both pass all 19 tests. Closed by FX11.06a (spec R6).
    - Evidence: re-checked after FX11.06a: `tests/test_inspect_conversion_status.py::test_status_that_grows_between_open_and_read_is_reported_oversized` fails against mutants A and D and at d4c0aae, and mutant E is caught by the accepted companion test (spec §8 decision). Commit 86faa002005a897a5b501e0784bf581bd38bf451, CI run 43355049360.
  - [x] FX11.05b R4: add a human-mode CLI test with a status file of exactly `CONVERSION_STATUS_MAX_BYTES + 1` bytes, asserting that length, exit 3 and the fixed message. Keep `_OVERSIZED_STATUS` and the existing tests unchanged.
    - Evidence: `tests/test_inspect_conversion_status.py::test_status_one_byte_over_the_limit_is_a_fixed_error_in_human_mode` asserts `len(status) == _STATUS_LIMIT + 1`, exit 3, "Error:" and the fixed message. `_OVERSIZED_STATUS` is unchanged. Commit 5581cb4c61ea26229a97f078ec7fe0b3ba020d53.
  - [x] FX11.05c Show the FX11.05a test fails against the reviewer's mutant in a scratch worktree, and at d4c0aae. The mutant pre-checks with `os.stat(status_path).st_size` (catching `OSError`) and uses `except JSONTooLargeError: conversion_status = None`. Record both failures in the ledger.
    - Evidence: Ran in scratch worktrees. Against the reviewer's mutant (HEAD plus an `os.stat` pre-check catching `OSError`, and `except JSONTooLargeError: conversion_status = None`), only `test_status_that_grows_before_it_is_read_is_reported_oversized` failed (1 failed, 14 passed); the old race test passed there. At d4c0aae it failed with `assert 0 == 3` (status silently omitted), alongside the two FX11.01 regressions (3 failed, 12 passed). The limit+1 test passes at d4c0aae too, because that boundary was already handled.
    - Note: the recorded `os.stat` mutant result is true, but it doesn't show R3 is met; see the FX11.05a note. The d4c0aae runs replaced the `CONVERSION_STATUS_MAX_BYTES` import with the literal `1024 * 1024`, because the constant doesn't exist there (spec §8).
  - [x] FX11.05d R5: in `docs/MAINTAINER_GUIDE.md`, reword "even if the file grew after an earlier size check" (around line 347) to say the decision comes from the bytes read. Add "non-object" to the list of cases where the status is left out (around line 349).
    - Evidence: `docs/MAINTAINER_GUIDE.md`: "The decision is made from the bytes read, so a file that grows or is replaced before it is read is still reported", and "non-object" added to the cases left out. Commit 5581cb4c61ea26229a97f078ec7fe0b3ba020d53.
  - [x] FX11.05e Run `/verify`, push, and record exact-head CI for the follow-up commit. Then re-check FX11.01a and FX11.01, citing FX11.05b, and set both status lines (this TODO and the spec) to complete.
    - Evidence: Exact-head Python CI [43352750100](https://github.com/ekkus93/pdf2audiobook/actions/runs/43352750100) on 5581cb4c61ea26229a97f078ec7fe0b3ba020d53 passed on Python 3.11, 3.12 and 3.13: 2008 passed and 1 skipped (the opt-in Kitten smoke) on each; Ruff, format, mypy, CLI smoke and wheel/sdist clean-environment smoke passed. FX11.01a and FX11.01 re-checked, citing FX11.05b; both status lines updated.

### Second review follow-up (spec §8)

- [x] FX11.06 Close the second-review findings (R6–R8). Test and record changes only; no runtime behaviour change.
  - [x] FX11.06a R6: add a CLI test that starts with a small valid status file and wraps the handle returned by `Path.open` (status file, read modes) so the file grows past `CONVERSION_STATUS_MAX_BYTES` on the first `read()` before delegating. Assert exit 3, the fixed message, content-free `--json` output, and exactly one read-mode open of the status file. Keep existing tests unchanged. No sleeps.
    - Evidence: `tests/test_inspect_conversion_status.py::test_status_that_grows_between_open_and_read_is_reported_oversized` wraps the handle returned by `Path.open` (status file, read modes). The file grows by `CONVERSION_STATUS_MAX_BYTES + 1` bytes on the first `read()`, before delegating. The test asserts exit 3, the fixed message, content-free JSON and `len(read_opens) == 1`. Existing tests are unchanged. Commit 86faa002005a897a5b501e0784bf581bd38bf451.
  - [x] FX11.06b R7: add a `tests/test_jsonio.py` test asserting that `load_size_checked_json` reads exactly `max_bytes + 1` bytes and nothing unbounded, for an over-limit and a valid file. It must also assert that a handle returning `max_bytes + 1` bytes from a file with a small `fstat` size still raises `JSONTooLargeError`.
    - Evidence: `tests/test_jsonio.py::test_size_checked_json_reads_exactly_one_byte_past_the_limit` asserts reads `== [101, 101]` for a valid and an over-limit file with `max_bytes=100`. `tests/test_jsonio.py::test_size_checked_json_decides_from_the_bytes_read_not_the_file_size` uses a 2-byte file whose handle returns 101 bytes, and asserts `JSONTooLargeError` with reads `== [101]`. Commit 86faa002005a897a5b501e0784bf581bd38bf451.
  - [x] FX11.06c Rebuild mutants A–E (spec §8 table) in scratch worktrees. Show the FX11.06a test fails against A, D and E and at d4c0aae (stating the import workaround), and the FX11.06b test fails against B and C. Record each result in the ledger.
    - Evidence: run in scratch worktrees with the reviewer's mutant script (the same mutants as spec §8). The new tests that fail are:
      - A (`fstat` then omit): the FX11.06a test and both FX11.06b tests;
      - B (unbounded read): both FX11.06b tests;
      - C (decide from `fstat`): both FX11.06b tests;
      - D (`Path.open` seek pre-check): the FX11.06a test;
      - E (two handles): `tests/test_jsonio.py::test_size_checked_json_reads_exactly_one_byte_past_the_limit` (and the existing handle-count test), plus the added `tests/test_inspect_conversion_status.py::test_valid_status_is_read_through_a_single_handle`;
      - d4c0aae, with the `CONVERSION_STATUS_MAX_BYTES` import replaced by the literal `1024 * 1024`: the FX11.06a test failed with exit 0 (status omitted), alongside the three earlier regressions.
    - Note: not checked. FX11.06c and spec R6 require *the FX11.06a test* to fail against mutant E, and that can't happen. E only opens its second handle when the first read is within the limit. The FX11.06a test makes that read go over the limit, so E reports the size error from its first handle and passes. E is caught instead by the R7 read-count test and by the added single-handle CLI test above, which counts read-mode opens for a valid file. The requirement wording is my error from writing R6, and it needs the user's decision: accept the companion test, or change R6/FX11.06c.
    - Evidence: Decision (user, 2026-11-13): the companion `tests/test_inspect_conversion_status.py::test_valid_status_is_read_through_a_single_handle` is accepted in place of the R6 race test failing against mutant E. E opens its second handle only for an in-limit file, so no test that grows the file past the limit can catch it. The R6 race test is still required to fail against mutants A and D and at d4c0aae. Recorded in spec §8 under R6.
  - [x] FX11.06d R8 nit: add `_assert_content_free` to `test_status_one_byte_over_the_limit_is_a_fixed_error_in_human_mode`; its R4 assertions stay unchanged.
    - Evidence: `_assert_content_free(result.stderr, tmp_path)` added to `tests/test_inspect_conversion_status.py::test_status_one_byte_over_the_limit_is_a_fixed_error_in_human_mode`; its R4 assertions are unchanged (the diff removes no lines). Commit 86faa002005a897a5b501e0784bf581bd38bf451.
  - [x] FX11.06e Run `/verify`, push, and record exact-head CI for the fix commit. Then re-check FX11.05a and FX11.05, citing FX11.06a, and update both status lines.
    - Evidence: local `/verify` (with Tesseract and the `kitten` extra now installed): 2012 passed, 1 skipped (Kitten smoke, opt-in); the 11 Tesseract tests ran. Exact-head Python CI [43355049360](https://github.com/ekkus93/pdf2audiobook/actions/runs/43355049360) on 86faa002005a897a5b501e0784bf581bd38bf451 passed on Python 3.11, 3.12 and 3.13: 2012 passed and 1 skipped (the opt-in Kitten smoke) on each; Ruff, format, mypy, CLI smoke and wheel/sdist clean-environment smoke passed. FX11.05a and FX11.05 re-checked, citing FX11.06a; both status lines updated.

### Third review follow-up

- [x] FX11.07 Close the third-review test gaps (user request, 2026-11-13). Tests only; no runtime behaviour change.
  - [x] FX11.07a N5 (medium): every boundary test built its payload from the imported constant, so changing `CONVERSION_STATUS_MAX_BYTES` to `1000 * 1000` or `1024 * 1024 + 1` passed the whole suite. Add a boundary test with literal sizes.
    - Evidence: `tests/test_inspect_conversion_status.py::test_the_status_limit_is_exactly_one_mebibyte` uses the literal 1,048,576: a file of exactly that size is included and one byte more is a fixed error (exit 3). It fails against all three N5 mutants (`1000 * 1000`, `1024 * 1024 + 1`, `1024`). Commit 87a8b764033c16955639b54100cb476df5be07a0.
  - [x] FX11.07b N9 (medium): no test made the bytes read disagree with the file on disk after the read, so an `inspect` that called `load_bounded_json` and then decided oversize from `os.stat` passed. Add both directions.
    - Evidence: `tests/test_inspect_conversion_status.py::test_oversize_is_decided_by_the_bytes_read_not_the_file_on_disk` (the handle returns more than 1 MiB while the file is 2 bytes: exit 3) and `tests/test_inspect_conversion_status.py::test_a_file_replaced_after_a_small_read_is_judged_by_what_was_read` (a small malformed read, then the file is replaced by an oversized one: exit 0, status omitted). Both fail against the N9 mutant. Commit 87a8b764033c16955639b54100cb476df5be07a0.
  - [x] FX11.07c N10 (low): a text-mode read of `max_bytes + 1` characters, re-encoded, passed the inspect and jsonio tests. Assert the status is read through one binary handle.
    - Evidence: `tests/test_inspect_conversion_status.py::test_status_is_read_in_binary_and_bounded_in_bytes` asserts the status file is opened once, in `"rb"`. It fails against the N10 mutant. Commit 87a8b764033c16955639b54100cb476df5be07a0.
  - [x] FX11.07d N16 (low): the depth-16 boundary was never tested, so `max_depth=15` passed. Add a status nested exactly 16 deep.
    - Evidence: `tests/test_inspect_conversion_status.py::test_status_nested_exactly_sixteen_deep_is_included`; it fails against the N16 mutant. The existing 17-deep cases still cover the other side. Commit 87a8b764033c16955639b54100cb476df5be07a0.
  - [x] FX11.07e Nits: the unreadable-file test ran only in `--json` mode, and `_assert_content_free` doesn't check OS message text.
    - Evidence: `tests/test_inspect_conversion_status.py::test_unreadable_conversion_status_is_omitted_in_human_mode` (exit 0) also asserts "Permission denied" is absent from the output. `_assert_content_free` itself is unchanged, because the working rules keep existing tests' assertions as they are.
  - [x] FX11.07f Run `/verify`, push, and record exact-head CI.
    - Evidence: `/verify`: ruff, format, mypy, pytest 2052 passed and 1 skipped (Kitten smoke, opt-in). The six mutants (N5a–c, N9, N10, N16) were rebuilt in place and each fails the inspect and jsonio tests; the files were restored and compared byte for byte. Exact-head Python CI [43388294116](https://github.com/ekkus93/pdf2audiobook/actions/runs/43388294116) on 87a8b764033c16955639b54100cb476df5be07a0 passed.
  - Note: the third review's documentation nits are recorded rather than rewritten. The Specification line above says "(R1–R2)", although the spec now has R1–R8. Commit 904f4c04a73bf4b1378e2e50daaa2c3c63315552 deleted an earlier Note under FX11.04d instead of appending; it said CI evidence was waiting for an authorized push, which FX11.04d's Evidence line now records.

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

Second review follow-up gate (spec §8):

- the R6 test fails against mutants A, D and E and at d4c0aae;
  - Note: amended by the user's decision in spec §8. Mutant E is caught by the companion single-handle test rather than the R6 test.
- the R7 test fails against mutants B and C;
- both pass at HEAD, and existing tests are unchanged;
- results are recorded with the d4c0aae import workaround stated;
- `/verify` and exact-head CI pass.

## Progress ledger

| Date | Commit SHA | Completed tasks | Tests/CI evidence | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-13 | Not committed | Spec and TODO drafted; implementation not started. | Not run | FX11.01 regression tests |
| 2026-11-13 | 19dc01be16ee10a479434fe407733cb8c2167ca6 | FX11.01–FX11.03, FX11.04a–c: `inspect` decides oversize from one bounded read (`jsonio.load_size_checked_json`); unreadable status omitted; FIFO limitation documented | Failed at the fix's parent d4c0aae: `test_status_that_grows_after_a_size_observation_is_reported_oversized` (status omitted, exit 0), `test_unreadable_conversion_status_is_omitted` (exit 1). After: `/verify` green on the rebased tree, 1995 passed and 12 skipped (11 Tesseract, 1 Kitten); mypy clean on 3.11–3.13. CI not run (not pushed) | FX11.04d: CI evidence needs a push |
| 2026-11-13 | 16e98a56bf85a4c0f9f50da9b3792970b2909624 | FX11.04d: CI evidence for the FX11 fix (19dc01be16ee10a479434fe407733cb8c2167ca6) | Python CI [43350264347](https://github.com/ekkus93/pdf2audiobook/actions/runs/43350264347) on head 16e98a56bf85a4c0f9f50da9b3792970b2909624 (the fix plus a TODO-only docs commit; no separate run exists for 19dc01b because the three commits were pushed together) passed on Python 3.11, 3.12 and 3.13: 2006 passed and 1 skipped (the opt-in Kitten smoke) on each, so the Tesseract-gated tests that skip locally ran in CI; Ruff, format, mypy, CLI smoke and wheel/sdist clean-environment smoke passed | None |
| 2026-11-13 | 904f4c04a73bf4b1378e2e50daaa2c3c63315552 | Post-implementation review of 19dc01be16ee10a479434fe407733cb8c2167ca6 (spec §7). The fix is correct, and `load_bounded_json()` matched the old version on 15 edge cases. Reopened FX11.01a and FX11.01 (CLI boundary is limit+2, not limit+1). Added FX11.05 (R3 race-test strength, R4 limit+1 CLI test, R5 docs wording) | Reviewer reran the 17 inspect/jsonio tests at HEAD (all passed) and the new tests at d4c0aae (the race and unreadable tests failed as recorded). A racy mutant using `os.stat` passed all 13 inspect tests. CI run 43350723813 on 904f4c0 succeeded | FX11.05 |
| 2026-11-13 | 5581cb4c61ea26229a97f078ec7fe0b3ba020d53 | FX11.05a–d: open-boundary growth race test, exact limit+1 CLI test, MAINTAINER_GUIDE wording (spec R3–R5) | The new race test fails against the reviewer's `os.stat` mutant (the only failure there) and at d4c0aae (`assert 0 == 3`). Local `/verify`: ruff, format (361 files), mypy (46 files, also 3.12 and 3.13), pytest 1997 passed and 12 skipped (11 Tesseract, 1 Kitten), CLI smoke. CI not yet run | FX11.05e: push and exact-head CI |
| 2026-11-13 | 5581cb4c61ea26229a97f078ec7fe0b3ba020d53 | FX11.05e: CI evidence for the review follow-up; FX11.01a and FX11.01 re-checked | Exact-head Python CI [43352750100](https://github.com/ekkus93/pdf2audiobook/actions/runs/43352750100) on 5581cb4c61ea26229a97f078ec7fe0b3ba020d53 passed on Python 3.11, 3.12 and 3.13: 2008 passed and 1 skipped (the opt-in Kitten smoke) on each; Ruff, format, mypy, CLI smoke and wheel/sdist clean-environment smoke passed | None |
| 2026-11-13 | a998581f0826a9e5badda9bcb16df435eaa5b7c6 | Second post-implementation review of the FX11 change (spec §8). The runtime code is correct and meets R1, R2, R4 and R5. R3 is not met. Reopened FX11.05a and FX11.05, added notes under FX11.01g and FX11.05c, and added FX11.06 (R6–R8) | Mutants against the 19 inspect/jsonio tests: `os.stat` pre-check caught only by the R3 test; A (`fstat` then omit), B (unbounded read), C (decide from `fstat`) and D (`Path.open` seek pre-check) passed all 19; E (two handles) was caught only by the handle-count assertion. A and D were re-run independently. d4c0aae runs used a literal in place of the `CONVERSION_STATUS_MAX_BYTES` import. CI run 43353117840 on a998581 succeeded | FX11.06 |
| 2026-11-13 | 86faa002005a897a5b501e0784bf581bd38bf451 | FX11.06a, FX11.06b, FX11.06d: race test growing the file between open and read, bounded-read unit tests, content-free check; plus a single-handle CLI test for mutant E. FX11.06c open | Mutants: A, B, C, D and E each fail at least one new test; the FX11.06a test itself does not fail against E (see the FX11.06c note). At d4c0aae (literal in place of the constant import) the FX11.06a test fails with exit 0. Local `/verify`: ruff, format (361 files), mypy (46 files, also 3.12 and 3.13), pytest 2001 passed and 12 skipped (11 Tesseract, 1 Kitten), CLI smoke. CI not yet run | FX11.06c: user decision on mutant E; FX11.06e: push and CI |
| 2026-11-13 | 86faa002005a897a5b501e0784bf581bd38bf451 | FX11.06c (user accepted the companion test for mutant E), FX11.06e, FX11.06; FX11.05a and FX11.05 re-checked | Exact-head Python CI [43355049360](https://github.com/ekkus93/pdf2audiobook/actions/runs/43355049360) on 86faa002005a897a5b501e0784bf581bd38bf451 passed on Python 3.11, 3.12 and 3.13: 2012 passed and 1 skipped (the opt-in Kitten smoke) on each; Ruff, format, mypy, CLI smoke and wheel/sdist clean-environment smoke passed. Local run with Tesseract and the `kitten` extra installed: 2012 passed, 1 skipped | None |
| 2026-11-13 | 87a8b764033c16955639b54100cb476df5be07a0 | FX11.07: third-review test gaps (N5 literal 1 MiB boundary, N9 bytes-read decision both ways, N10 binary read, N16 depth 16, human-mode unreadable) | `/verify` 2052 passed, 1 skipped; N5a–c, N9, N10 and N16 mutants each fail the new tests; exact-head Python CI [43388294116](https://github.com/ekkus93/pdf2audiobook/actions/runs/43388294116) passed | None |
