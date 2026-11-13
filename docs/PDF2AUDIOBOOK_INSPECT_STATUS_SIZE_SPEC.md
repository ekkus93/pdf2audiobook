# PDF2Audiobook — Inspect Conversion Status Size Specification

**Status:** R1–R2 implemented in 19dc01b and R4–R5 in 5581cb4, both verified by CI; R3 not met; second review follow-up R6–R8 (§8) not implemented
**Date:** 2026-11-13
**Scope:** Close the `inspect` race found in the fourth-review TODO audit.
**Companion:** `docs/PDF2AUDIOBOOK_INSPECT_STATUS_SIZE_TODO.md`

## 1. Problem

`pdf2audiobook inspect WORKSPACE/manifest.json` optionally includes
`reports/conversion_status.json`. In `src/pdf2audiobook/cli.py` (about lines
397–409), `inspect` first checks the path's size with `stat()` and then reads
it through `load_bounded_json()` with a 1 MiB cap. The status file can be
replaced or grow after the size check. If the bounded read sees more than
1 MiB, `load_bounded_json()` returns `None`; `inspect` then silently omits
`conversion_status` instead of reporting that the file is too large.

This hides conversion state precisely when the status artifact is oversized.
It is a time-of-check/time-of-use race. The existing pre-read size check
handles stable oversized files, but does not close the race.

The separate `stat()` call also causes a second defect. `stat()` errors other
than `FileNotFoundError` (for example `PermissionError` on the `reports/`
directory) are not caught. They reach the CLI's `OSError` handler, so
`inspect` fails with "A filesystem operation failed" (exit 1), although an
unreadable status file is optional and should be omitted.

## 2. Requirement

### R1 — Report oversized conversion status consistently

`inspect` must detect an oversized `conversion_status.json` from the same
opened file descriptor used to read it. The read must be bounded to at most
1 MiB plus one byte. If more than 1 MiB is read, stop parsing and report the
fixed user-facing error:

> Conversion status file exceeds safe size limit

The error remains an `InputError`, so the exit code stays **3** in both human
and `--json` modes, as it is today for a stable oversized file.

The result must not depend on whether the file grew or was replaced between
separate path operations. Do not read an unbounded file into memory.

### R2 — Preserve existing behavior for other cases

- A missing status file remains optional and does not make `inspect` fail.
- A valid status object at or below 1 MiB remains included in the manifest
  inspection output.
- Malformed, unreadable, non-object, or over-depth status data follows the
  established bounded-JSON behavior: it is omitted from the output, and it is
  not mistaken for a size violation. "Unreadable" includes any `OSError` when
  opening or reading the file (for example `PermissionError`). With the
  separate `stat()` removed, these cases no longer fail `inspect` with
  "A filesystem operation failed".
- PDF inspection and all other `inspect` behavior remain unchanged.
- Error output continues through the existing CLI text/JSON error handling;
  do not include paths, file contents, or OS diagnostics in the message.

## 3. Design constraints

- **One handle, one decision.** Avoid a `stat()`-then-open size decision. Use
  one open handle and a bounded read of `limit + 1`, then distinguish the
  over-limit case before JSON parsing. Close the handle on every path.
- **Keep the cache contract.** Do not change cache callers that rely on
  `load_bounded_json()` returning `None` for a cache miss.
- **Recommended shape:**
  - In `src/pdf2audiobook/jsonio.py`, factor the open-and-read-`limit + 1`
    step out of `load_bounded_json()` into a private helper that both
    functions use.
  - Add a small public function (for example `load_bounded_json_object()` or
    a status-specific name) that raises a dedicated exception (for example
    `JSONTooLargeError`) when more than the limit is read. It otherwise
    returns the parsed value, or `None` exactly where `load_bounded_json()`
    would.
  - `inspect` catches that exception and raises the fixed `InputError`.
  - `load_bounded_json()`'s signature and behavior stay unchanged.
- **One named limit.** Define the 1 MiB status limit once, as a module-level
  constant (for example `CONVERSION_STATUS_MAX_BYTES`), and use it for both
  the read bound and any test that builds boundary-sized files. Today the
  literal `1024 * 1024` appears twice in `inspect`.
- **Errors.** The over-limit result must map to the fixed error above.
  Ordinary malformed JSON must remain an omission/cache miss, as it is today.
  Do not broaden this change into a general cache-loader redesign.

## 4. Regression coverage

Add deterministic CLI tests that exercise the real `inspect` command. Extend
`tests/test_inspect_conversion_status.py`; don't duplicate it. Its existing
`test_inspect_rejects_oversized_conversion_status_file` already covers a
stable oversized file in `--json` mode (exit 3 and the fixed message). Keep
that test's inputs and assertions unchanged.

1. **Human mode:** a stable status file one byte above 1 MiB produces the
   fixed size-limit error with exit 3.
2. **`--json` mode:** the existing test covers the message and exit code. Add
   a test asserting that stderr is exactly one JSON value and contains no
   path, file content, or errno text.
3. **Exact limit:** a status file of exactly 1 MiB (1,048,576 bytes) holding
   a valid JSON object is accepted and included in the CLI output. Build it as
   a small object padded with trailing whitespace to the exact size.
4. **Normal size:** a valid normal-sized status object is included in
   inspection output.
5. **Other cases:**
   - a missing file remains optional;
   - malformed and over-depth files are omitted and not reported as
     oversized;
   - an unreadable status file (simulate a `PermissionError` at the
     open/read boundary) is omitted, and `inspect` exits 0, not 1 with
     "A filesystem operation failed".
6. **Race:** a deterministic race simulation replaces or expands the file
   after the initial path lookup/size observation that exposed the old
   sequence. For example, monkeypatch `Path.stat` to report a small size
   while the file on disk is over the limit. The new implementation must
   still return the fixed too-large error, because the decision is made using
   the bytes read from the opened handle.

Tests must not rely on timing, sleeps, or nondeterministic concurrent writes.
Inject or monkeypatch the file/open boundary to reproduce the replacement or
growth deterministically. Keep existing tests' inputs and expectations.

## 5. Known limitation (out of scope)

If `reports/conversion_status.json` is a FIFO (named pipe) or another
non-regular file, opening and reading it can block, so `inspect` can hang.
This is true before and after this change. Fixing it (for example opening with
`O_NONBLOCK` and requiring a regular file via `fstat` on the open handle) is
out of scope here. Record it in `docs/MAINTAINER_GUIDE.md` as a known
limitation and leave it for a separate change.

## 6. Acceptance criteria

- R1 and R2 are satisfied.
- The new regression fails against the prior implementation for the
  oversized-after-check case and passes with the fix. The unreadable-file
  test also fails at the prior implementation (exit 1 instead of 0).
- Existing `inspect` tests pass unchanged in both output modes.
- The oversize error exits 3 in both output modes.
- Ruff, formatting, configured mypy checks, and the full offline pytest suite
  pass through the repository's `/verify` workflow.
- No conversion status content, filesystem path, or raw OS error is exposed
  in the fixed size-limit response.
- `load_bounded_json()` behavior is unchanged for all existing callers.
- No unrelated runtime behavior or files are changed, apart from the
  MAINTAINER_GUIDE.md limitation note.

## 7. Post-implementation review (2026-11-13)

An independent review of the fix commit 19dc01be16ee10a479434fe407733cb8c2167ca6, at master 904f4c04a73bf4b1378e2e50daaa2c3c63315552, found the implementation correct:

- R1 and R2 are met, and `load_bounded_json()` behaves identically for all 11 other callers under `src/`. Old and new versions were compared on 15 edge cases, each under two limit settings.
- The race and unreadable-file tests fail at the parent d4c0aae, as recorded.

It found two weaknesses in the tests and some documentation drift. R3–R5 below address them. They change tests and docs only; no runtime behaviour changes.

### R3 — The race test must catch any check-then-read design

*Problem:* `test_status_that_grows_after_a_size_observation_is_reported_oversized` (tests/test_inspect_conversion_status.py:180-201) fakes a small size only for `Path.stat`. The reviewer built a still-racy version of `inspect` that:

- pre-checks the size with `os.stat(status_path).st_size`, catching `OSError`;
- silently omits the status when the read reports oversize (`except JSONTooLargeError: conversion_status = None`).

That version passes all 13 tests in the file, and the 57 tests selected by `-k "inspect or status or jsonio"`. Any size check that doesn't go through `Path.stat` (`os.stat`, `os.path.getsize`, or `fstat` before reading) sees the real large size, so the test can't tell such a check from the fix.

*Required:*

- Add a CLI test that starts with a small status file on disk (a valid JSON object well under the limit). Wrap the open boundary (`Path.open`, filtered to the status file name as the existing tests do) so the file grows past `CONVERSION_STATUS_MAX_BYTES` immediately before the handle is returned.
- Assert exit 3, the fixed message and content-free output in `--json` mode. Assert that `conversion_status` is not silently omitted with exit 0.
- Keep the existing race test unchanged.
- Show the new test fails against the reviewer's mutant described above, applied in a scratch worktree, and record that in the ledger. Also show it fails at d4c0aae.
- No sleeps or timing.

### R4 — Test the exact one-byte-over boundary at the CLI

*Problem:* Spec §4.1 asks for a status file one byte above 1 MiB. `_OVERSIZED_STATUS = b"{}" + b" " * _STATUS_LIMIT` (tests/test_inspect_conversion_status.py:67) is 1 MiB plus **two** bytes. The exact limit+1 boundary is tested only in `tests/test_jsonio.py`, with a 7-byte file and `max_bytes=6`.

*Required:*

- Add a CLI test in human mode with a status file of exactly `CONVERSION_STATUS_MAX_BYTES + 1` bytes. Assert that length in the test.
- Expect exit 3 and the fixed message.
- Keep the existing tests and `_OVERSIZED_STATUS` unchanged.

### R5 — Documentation accuracy

*Problem:*

- `docs/MAINTAINER_GUIDE.md:347` says the error is raised "even if the file grew after an earlier size check". There is no earlier size check any more, so the wording suggests one exists.
- The list of cases where the status is left out (`:349`) misses the non-object case.
- This spec's status line said "Draft; R1–R2 are not implemented" after the TODO was marked complete.

*Required:*

- Reword the guide: the decision is made from the bytes read, so a file that grows or is replaced before it is read is still reported.
- Add "non-object" to the list of cases where the status is left out.
- Keep this spec's status line in step with the TODO.

### Accepted as is

These were also reviewed and need no change:

- If an `OSError` happens partway through reading an oversized file, the status is omitted rather than reported as too large. R2 classes this as an unreadable file.
- The handle-closing test in `tests/test_jsonio.py` can't fail against the old code, which also used `with`. It stays as a guard for future changes.
- `_assert_content_free`'s content check is trivial for the `{}`-and-spaces payload. Assertions on paths and errno still apply.
- CI ran on 16e98a5, not on 19dc01b alone, because the three commits were pushed together. The ledger records this, and the trees differ only in the TODO file.

### Acceptance criteria for §7

- The R3 test fails against the reviewer's mutant and at d4c0aae, and passes at HEAD.
- The R4 test passes and asserts the exact length `CONVERSION_STATUS_MAX_BYTES + 1`.
- Existing tests are unchanged.
- `/verify` passes, and exact-head CI passes for the fix commit.

## 8. Second post-implementation review (2026-11-13)

A second independent review covered the whole FX11 change (`bd7f3be..a998581f0826a9e5badda9bcb16df435eaa5b7c6`), including the R3–R5 follow-up in 5581cb4c61ea26229a97f078ec7fe0b3ba020d53.

**The runtime code is correct.**

- R1, R2, R4 and R5 are met.
- The 19 tests in `tests/test_inspect_conversion_status.py` and `tests/test_jsonio.py` pass on Python 3.11, 3.12 and 3.13.
- The CI runs recorded in the TODO are for the SHAs claimed, and all succeeded.

**R3 is not met.** The review built six mutants (deliberately broken versions of the code). Their results against those 19 tests, re-run independently for A and D:

| Mutant | What it does | Result |
| --- | --- | --- |
| `os.stat` pre-check (recorded in FX11.05c) | `os.stat` size check in `inspect`, then omit on `JSONTooLargeError` | caught only by the R3 test |
| A | `fstat` on the open handle before reading, then return `None` for an over-limit read | **all 19 pass** |
| B | unbounded `stream.read()` instead of `read(max_bytes + 1)` | **all 19 pass** |
| C | read `max_bytes`, then decide from `fstat` instead of the bytes read | **all 19 pass** |
| D | separate `Path.open` + `seek(0, 2)` size pre-check in `inspect`, then omit on `JSONTooLargeError` | **all 19 pass** |
| E | bounded decision on one handle, then parse on a second handle with `load_bounded_json` | caught only incidentally, by the handle-count assertion in `tests/test_jsonio.py::test_size_checked_json_closes_its_handle_on_every_path` |

**Why the R3 test misses them.**

- `test_status_that_grows_before_it_is_read_is_reported_oversized` (tests/test_inspect_conversion_status.py:203-224) grows the file inside the first read-mode `Path.open`.
- A check that goes through `Path.open` (D) therefore already sees the large file.
- Growth between open and read (A) is never simulated.
- Nothing asserts the read is bounded (B), or that the decision comes from the bytes read (C).

The mutant script used is kept in the session scratchpad. Mutants A–E are described above in enough detail to rebuild them.

**Evidence gap.** The new test file can't be collected at d4c0aae: `ImportError` for `CONVERSION_STATUS_MAX_BYTES`, which doesn't exist there. Every run "at d4c0aae" replaced that import with the literal `1024 * 1024` first. The FX11.01g, FX11.05c and ledger evidence don't say so.

R6–R8 below close these gaps. They change tests and records only; no runtime behaviour changes.

### R6 — The race test simulates growth between open and read

*Required:*

- Add a CLI test that starts with a small valid status file. Wrap `Path.open` (filtered to the status file name and read modes) so it returns the real handle wrapped. The file grows past `CONVERSION_STATUS_MAX_BYTES` on that handle's first `read()` call, before delegating, so the read sees the grown file.
- Assert exit 3, the fixed message and content-free `--json` output.
- Assert exactly one read-mode open of the status file, which also rules out mutant E's second handle.
- Keep the existing tests unchanged, including the R3 test.
- The new test must fail against mutants A, D and E and at d4c0aae, and pass at HEAD.
- No sleeps or timing.

### R7 — A unit test enforces the bounded read

*Required:*

- Add a `tests/test_jsonio.py` test that wraps the handle opened by `load_size_checked_json`. Assert that a read requests exactly `max_bytes + 1` bytes, and that no unbounded or larger read is made, for an over-limit file and for a valid one.
- Assert the over-limit decision follows the bytes returned: a wrapped handle that returns `max_bytes + 1` bytes from a file whose `fstat` size is small must still raise `JSONTooLargeError`.
- The test must fail against mutants B and C, and pass at HEAD.

### R8 — Correct the record

*Required:*

- In the TODO, append new `Note:` and `Evidence:` lines; don't edit the existing ones.
  - Under FX11.01g and FX11.05c: the import of `CONVERSION_STATUS_MAX_BYTES` was replaced with a literal to run the tests at d4c0aae.
  - Under FX11.05c: the `os.stat` mutant result is true, but it doesn't show R3 is met (mutants A and D).
- Append a ledger row recording this review's mutant results, and later the R6/R7 results against each mutant.
- Add `_assert_content_free` to `test_status_one_byte_over_the_limit_is_a_fixed_error_in_human_mode`. This is a nit; the R4 assertions are unchanged.
- Re-check R3's TODO items only when R6 is met.

### Accepted as is

- The unreadable-file and race tests depend on the implementation reading through `Path.open`. A correct implementation using `open()` or `os.open` would fail them. That errs on the strict side, never the permissive one. Record it in a comment on those tests if they are touched, but don't change them.

### Acceptance criteria for §8

- The R6 test fails against mutants A, D and E and at d4c0aae.
- The R7 test fails against mutants B and C.
- Both pass at HEAD, and every existing test is unchanged.
- Each result is recorded in the ledger, with the d4c0aae import workaround stated.
- `/verify` passes, and exact-head CI passes for the fix commit.
