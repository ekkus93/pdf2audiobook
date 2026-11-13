# PDF2Audiobook — Inspect Conversion Status Size TODO

**Status:** Open; R1–R2 are not implemented
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
  - [ ] FX11.01b `--json` mode: keep the existing
    `test_inspect_rejects_oversized_conversion_status_file` unchanged. Add a
    test asserting stderr is exactly one JSON value with no path, file
    content, or errno text.
  - [ ] FX11.01c Exact limit: a valid JSON object padded with whitespace to
    exactly 1,048,576 bytes is included in the CLI output.
  - [ ] FX11.01d Cover valid normal-sized status inclusion, missing-file
    behavior, and malformed/over-depth input without mislabeling it as too
    large.
  - [ ] FX11.01e Unreadable file: a `PermissionError` at the open/read
    boundary omits the status and `inspect` exits 0, not 1 with "A
    filesystem operation failed".
  - [ ] FX11.01f Race: monkeypatch `Path.stat` (or the open boundary) so the
    initial size observation looks small while the file read is over the
    limit. Assert the fixed size error. No sleeps or timing races.
  - [ ] FX11.01g Confirm that the race test (FX11.01f) and the
    unreadable-file test (FX11.01e) fail against the parent revision. Record
    the node IDs and failure modes (status silently omitted; exit 1).

### Implementation

- [ ] FX11.02 Make the size decision from the bounded read of one open handle.
  - [ ] FX11.02a In `jsonio.py`, factor the open-and-read-`limit + 1` step
    into a private helper shared with `load_bounded_json()`. Leave
    `load_bounded_json()`'s signature and behavior unchanged.
  - [ ] FX11.02b Add a public bounded loader that raises a dedicated
    too-large exception (for example `JSONTooLargeError`) when more than the
    limit is read, and otherwise matches `load_bounded_json()`.
  - [ ] FX11.02c In `inspect`, catch that exception and raise
    `InputError("Conversion status file exceeds safe size limit")` (exit 3).
  - [ ] FX11.02d Define the 1 MiB limit once as a named constant and use it
    for the read bound and in the boundary tests.
  - [ ] FX11.02e Preserve missing-file, malformed JSON, over-depth,
    non-object, and unreadable behavior (all omitted). Keep paths and OS
    details out of user-facing errors.
  - [ ] FX11.02f Remove the separate `stat()`-then-read decision. Make sure
    handles close on success and failure.

### Documentation

- [ ] FX11.03 Record the known FIFO limitation (spec §5) in
  `docs/MAINTAINER_GUIDE.md`: a non-regular status file can make `inspect`
  block, before and after this change.

### Verification and closure

- [ ] FX11.04 Verify and record evidence.
  - [ ] FX11.04a Run the focused `inspect` tests and confirm the boundary,
    unreadable and race cases.
  - [ ] FX11.04b Run `/verify`, including Ruff, format, mypy, and the full
    offline pytest suite.
  - [ ] FX11.04c Confirm any environment-gated tests are reported accurately;
    do not claim they ran when skipped.
  - [ ] FX11.04d Append the local and CI results, the full fix SHA, and real
    run IDs to the ledger; check FX11 only when all acceptance criteria pass.

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

## Progress ledger

| Date | Commit SHA | Completed tasks | Tests/CI evidence | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-13 | Not committed | Spec and TODO drafted; implementation not started. | Not run | FX11.01 regression tests |
