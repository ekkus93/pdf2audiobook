# PDF2Audiobook Follow-up Fixes and Progress Specification

**Status:** Proposed
**Date:** 2026-10-27
**Companion:** `docs/PDF2AUDIOBOOK_FOLLOWUP_FIXES_TODO.md`
**Baseline:** master at 5a4f96e (`fix(workspace): preserve reviewed narration and recover updates`) plus the uncommitted module split in the working tree
**Supplements:** `docs/PDF2AUDIOBOOK_SPEC.md`, `docs/PDF2AUDIOBOOK_REVIEW_FOLLOWUP_SPEC.md`

## 1. Purpose and scope

The code review of the review-follow-up work (2026-10-27) found that read-only manifest access now takes the workspace lock, two review-save outcomes are misreported, an edited chapter can become permanently stuck, recovery failures do not say which file blocked them, legacy workspaces with a non-`warn` footnote policy are refused with a misleading message, every render writes a journal even when nothing changed, and some acceptance tests and documentation are missing. R1–R9 fix those findings. R10 adds a configurable LLM request timeout (Ollama default 5 minutes). R11 adds progress bars and an estimated time remaining, using `tqdm`.

All existing invariants still hold: errors and logs stay content-free, `--json` output stays parseable, PDF and LLM text are untrusted data, user edits are never silently overwritten, the budget ledger fails closed, and CI stays offline.

## 2. Precedence

If this spec conflicts with `docs/PDF2AUDIOBOOK_REVIEW_FOLLOWUP_SPEC.md`, this spec wins. Amend the older spec in the same commit as the fix that supersedes it.

## 3. Requirements: review findings

### R1: Read-only manifest access does not lock, create files or recover

`read_manifest` (`workspace.py`) currently takes the workspace lock in non-blocking mode. While a conversion is running, read-only callers therefore fail with "Another conversion is already running". This affects the review page's `GET /api/manifest` and inspecting a `manifest.json`. Calling it on a nonexistent path creates the directory and a `.convert.lock` file. A read-only command can also run recovery, which writes files.

- `read_manifest` must not acquire the lock, create directories or files, or run recovery.
- A lock-free read must refuse to use a manifest while a transaction is pending. Check for the journal (`.review-transaction.json`) before and after reading. If it is present either time, raise a content-free `PendingRecoveryError` saying a workspace update is pending and that running `pdf2audiobook recover` (R5) or any writing command completes it.
- Every command that reads and then mutates, or that consumes chapter text for synthesis or packaging, must keep taking the lock, with recovery happening there as today. Currently that is analysis, conversion, dry-run, review save, `pack-m4b` and the new `regenerate-chapter`/`recover` commands. Any read those commands make while holding the lock must be done under the lock.
- `workspace_lock` must not create the workspace directory unless the caller is a writer. Add a `create: bool` parameter. Read paths that need the lock on a missing workspace fail with the existing content-free manifest error instead of creating directories.

**Acceptance:**
- While another process holds the lock, `read_manifest` and `GET /api/manifest` succeed.
- Calling `read_manifest` on a nonexistent path leaves no new directory or file.
- A pending journal makes `read_manifest` raise `PendingRecoveryError` without modifying any file.
- Conversion and `pack-m4b` still recover before use.
- New privacy tests for both error paths.

### R2: Truthful outcome when an earlier transaction blocks a save

`save_chapter_updates` takes the lock, and the lock runs recovery of an earlier transaction. If that recovery fails, the new request receives HTTP 503 "Review update was committed but needs recovery", even though nothing from the new request was saved.

- Recovery failures raised during lock acquisition must use `PendingRecoveryError` ("A previous workspace update needs recovery; this update was not saved"). This is distinct from `ReviewRecoveryRequired`, which stays reserved for a failure after this operation's own commit point.
- HTTP: both outcomes use 503 but carry different messages, and the JSON body carries a stable `"outcome"` field: `"not_saved_pending_recovery"` or `"committed_needs_recovery"`. Lock contention stays 409.
- The browser shows the message plus the next action, which is to run `pdf2audiobook recover <manifest>`. It must never say "Saved" for either outcome.
- CLI commands map `PendingRecoveryError` to the existing workspace exit code with the same message.

**Acceptance:**
- With an unrecoverable leftover journal, a direct save raises `PendingRecoveryError`. The HTTP response is 503 with `outcome=not_saved_pending_recovery`, and the manifest is byte-identical to before.
- The existing committed-recovery tests still return `committed_needs_recovery`.
- Browser script tests cover both messages.

### R3: Review conflicts are shown to the user

Every `ExtractionError` from a save becomes the generic "Review update was invalid; no changes were saved". The chapter-numbered conflict message and its recovery action are lost.

- Add `ChapterConflictError(ExtractionError)` carrying only the chapter number. `chapter_artifacts._conflict` must raise it.
- HTTP returns 422 `{"error": <conflict message>, "outcome": "not_saved_conflict", "chapter": N}`. The message is the existing content-free text, updated to name `regenerate-chapter` (R4).
- Other validation errors keep the generic 400 message. Do not forward arbitrary exception text to the browser: only `ChapterConflictError` and `PendingRecoveryError` messages are forwarded.

**Acceptance:**
- A boundary change on an edited chapter returns 422 naming that chapter, the browser shows it, and all files are unchanged.
- A privacy test confirms no book text or path is in the response.

### R4: Explicit per-chapter regeneration

The README says to "restore the original generated file", but nothing produces that file. If a user deletes an observed edited file instead, they get a permanent conflict because the file is missing with a known edited state (`chapter_artifacts.py:156`). The only ways out are deleting `chapter-artifacts.json`, which is undocumented, or starting a fresh workspace, which loses review approvals.

Add `pdf2audiobook regenerate-chapter MANIFEST --chapter N [--json]`. Repeating `--chapter` or passing `--all-conflicts` handles several chapters at once. Under the workspace lock it must:

1. Recover any pending transaction (R5 rules).
2. For each selected chapter, plan its generated text from the *committed* manifest and the recorded footnote policy.
3. If the current file exists and differs from the generated text, copy it to `chapter-backups/NNN-<UTC timestamp>.txt`. Create the file exclusively (`O_EXCL`) and never overwrite an existing backup. Then fsync the backup and the directory.
4. Publish the generated file and an artifact record with `edited=false` through the existing transaction journal, in one commit. Backups are written before the commit point and are never deleted by the tool.
5. Report the backed-up chapter numbers (never paths or contents in JSON or logs). In human output, the backup file name is relative to the workspace.

This command does not change approvals, review reasons or the manifest. The planner ignores the `chapter-backups/` directory. `--all-conflicts` selects every chapter that the planner would currently reject: one that is edited with a changed identity, edited but missing, or an occupant conflict. Deleting `chapter-artifacts.json` remains unsupported. Document `regenerate-chapter` as the recovery path, and update the conflict message and README to name it.

**Acceptance:**
- An edited, observed, then deleted chapter is regenerated, and conversion then proceeds.
- An edited chapter is backed up byte for byte and regenerated.
- A second run while the file is unchanged makes no new backup.
- An existing backup name is never overwritten.
- `--json` output is parseable and content-free.
- Lock contention returns the lock error.
- Interrupted publication recovers.

### R5: Recovery names the blocking target and offers a safe completion path

`_recover` raises "Review recovery found changed workspace files; restore them from backup" without saying which file changed. The README's advice to restore that chapter can't be followed.

- Recovery errors name each blocking target by a safe label only: `chapter N`, `manifest`, `coverage report` or `chapter metadata`. Never use paths or digests.
- Add `pdf2audiobook recover MANIFEST [--back-up-changed] [--json]`:
  - Without the flag, it runs recovery and reports either "nothing pending", "recovered", or the blocking labels.
  - With `--back-up-changed`, a target whose current content matches neither the planned old state nor the planned new state is first copied to `chapter-backups/`. Non-chapter targets go to `workspace-backups/<name>-<timestamp>`, using the R4 exclusive-create rules. Recovery then completes the transaction.
  - It never discards the journal without completing it.
- An invalid or oversized journal stays a hard stop, with a message to restore the workspace from backup. `--back-up-changed` does not bypass journal validation.

**Acceptance:**
- An external edit after commit produces an error naming `chapter N`.
- `recover --back-up-changed` preserves that edit in a backup and completes the transaction, and a repeat run reports "nothing pending".
- An invalid journal is refused with no writes.
- Privacy tests cover each new message.

### R6: Legacy workspaces with a non-`warn` policy

A review save with no `chapter-artifacts.json` uses `warn`. A workspace analyzed with `inline`, `end` or `omit` is then refused with a chapter-conflict message that tells the user to back up files they never edited.

When no artifact state exists, resolve the policy as follows (`chapter_artifacts.resolve_footnote_policy`; it writes nothing):

- If the manifest holds the deterministic footnote-omit edits, the policy is `omit`. That policy is applied through its accepted edits, so rendering cannot distinguish it.
- Otherwise the candidates are `warn`, `inline` and `end`. If the manifest holds footnote-anchor edits (created only by `inline`, `end` or `omit`), `warn` is removed.
- A chapter file is *recognizable* when it matches the rendering of at least one candidate. Hand-edited or foreign files are never recognizable and never decide the policy; the planner still protects them.
- If no candidate policy renders any chapter differently (the footnote policy does not affect the text), or no chapter file exists, and `warn` is still a candidate, use `warn`.
- Otherwise, if at least one file is recognizable and exactly one candidate matches all recognizable files, establish it.
- Otherwise refuse with a content-free `FootnotePolicyUnknownError`: "This workspace has no recorded footnote policy that can be determined from its chapter files; run analyze with the original pdf.footnotes setting, or pass --footnotes to regenerate-chapter". Write nothing.

`regenerate-chapter` takes an optional `--footnotes {warn,inline,end,omit}` for the refused case, so a legacy workspace whose only affected chapter file was edited is not left without a way out. It may not contradict a recorded policy ("A footnote policy is already recorded for this workspace; change it by running analyze with the new pdf.footnotes setting"). Review save, chapter selection (including `pack-m4b`) and `regenerate-chapter` all use this resolver; conversion and analysis keep using the configured policy and record it.

Analysis keeps its current behavior and records the configured policy. Document the resolution in the README upgrade notes.

**Acceptance:**
- A legacy workspace rendered with each of `inline`, `end` and `omit` saves a review and records that policy.
- A workspace with ambiguous candidates, or whose only policy-affected file was edited, is refused with the new message and files unchanged.
- A footnote-free workspace adopts `warn`.
- An edited policy-neutral file does not prevent the policy from being resolved from another chapter.
- `regenerate-chapter --footnotes` resolves the refused case and cannot contradict a recorded policy.

### R7: Skip publication when nothing changes

`commit_artifacts` writes and fsyncs a journal that carries base64 copies of every chapter write, even when every target already holds its planned content.

- If every payload's planned digest equals the current digest and there are no deletes, return without writing a journal or any file.
- Guarded checks (`metadata_observed`, `expected_manifest`, observed chapter digests) still run first, so a concurrent change is still detected.

**Acceptance:**
- An analysis resume on an up-to-date workspace leaves the modification times of `manifest.json`, `coverage.json`, `chapter-artifacts.json` and every chapter file unchanged, and creates no journal.
- A test spies on `atomic_write` to confirm zero calls.

### R8: Missing acceptance coverage

Add the tests the previous follow-up claimed but did not include:

- **Dry-run:** after a voice marker and a correction are added to an approved chapter, `convert --dry-run --json` reports selection and speakability from the edited text, writes no audio, and leaves the chapter bytes unchanged.
- **Legacy end-to-end:** a workspace whose `chapter-artifacts.json` is removed (simulating a pre-follow-up workspace) goes through analyze resume, review save and convert with a fake TTS provider. A matching file is adopted. A differing file is preserved and reported as a conflict, and `regenerate-chapter` resolves it.
- **No mixed consumption:** with a committed but unpublished journal, conversion recovers before selecting chapters and synthesizes the new text, never the old.

### R9: Documentation and record keeping

- `docs/PDF2AUDIOBOOK_REVIEW_FOLLOWUP_TODO.md`:
  - Remove the stale §2 "Progress" paragraph that says cases "remain open".
  - Correct §5's evidence (mypy module count).
  - Note that the further module split is tracked by this TODO.
- Commit the working-tree module split (`analysis_state.py`, `audio/encoding.py`, `audio/progress.py`, `chapter_selection.py`, `conversion.py`, `document/coverage.py`, `document/listing.py`, `document/narration.py`, `document/pagination.py`, `llm/advisory_common.py`, `llm/provider.py`, `llm/structure.py`, `tts/selection.py`) as one or more `refactor` commits. Each must pass the full suite with no test inputs or expectations changed; only monkeypatch targets may move.
- Record the new module responsibilities in `docs/MAINTAINER_GUIDE.md`.
- Add `src/pdf2audiobook/narration.py` to `[tool.mypy].files`. It is currently missing and is a different file from `document/narration.py`.
- README: document `regenerate-chapter`, `recover`, the backup directories, the R6 policy resolution, the timeout setting (R10) and progress output (R11).

## 4. Requirements: new features

### R10: Configurable LLM request timeout

The HTTP client timeout is hard-coded at 60 s (`llm/provider.py`, `timeout: float = 60.0`) and never comes from settings. Local Ollama models on modest hardware often need longer per request.

- Add `timeout_seconds: float` to `RemoteLLM` (`config.py`), validated `> 0` and `<= 3600`. Defaults:
  - `llm.ollama.timeout_seconds = 300` (5 minutes);
  - `llm.openai.timeout_seconds = 60` and `llm.llama_server.timeout_seconds = 60`, preserving current behavior.
- Environment override: `PDF2AUDIOBOOK_LLM_TIMEOUT_SECONDS`, mapped to the selected provider (`("llm", "@selected", "timeout_seconds")`), like `PDF2AUDIOBOOK_LLM_URL`.
- The provider factory passes the selected provider's value. The value is the read/write/pool timeout. The connect timeout is `min(10, timeout_seconds)`, so an unreachable server fails fast.
- The Ollama served-context lookup (`/api/ps`) keeps its own short timeout of 10 s and must not inherit the long request timeout.
- A timeout is a retryable transport failure under the existing `max_retries` policy. Budget attempt accounting settles it as it does other transport failures today (fail closed). The final error is content-free, keeps the existing "<provider> LLM transport failure" wording that other code and tests match on, and names the setting: "<provider> LLM transport failure: request timed out after N s; increase llm.<provider>.timeout_seconds". A connect timeout stays an unbilled "transport failure" without that suffix, because raising the request timeout would not help. The README notes that the worst-case wall time per request is `timeout_seconds × (max_retries + 1)`.
- The timeout must not appear in analysis fingerprints or LLM cache keys, because it does not change results.
- `config show` (text and `--json`) and `doctor --json` report the effective value.

**Acceptance:**
- The default Ollama setting is 300.
- Config-file and env overrides reach `httpx.Client`; a test inspects the client timeout.
- Out-of-range values are rejected.
- A mock transport raising `httpx.ReadTimeout` retries and then produces the content-free message.
- `/api/ps` uses 10 s.
- Changing the timeout leaves the analysis fingerprint unchanged.
- `config show --json` includes the field.

### R11: Progress display with estimated time remaining

Users currently see no indication of what a long analysis or conversion is doing, or how long remains.

**Dependency and module**
- Add the runtime dependency `tqdm>=4.66,<5` and the dev dependency `types-tqdm`. Update `uv.lock`; the packaging smoke must still pass in a clean venv.
- Add `src/pdf2audiobook/progress_display.py` and register it in `[tool.mypy].files`. It defines a small `ProgressReporter` protocol: `stage(name, total, unit, initial=0)` returning a handle with `advance(n)`, `set_detail(text)` and `close()`. It provides a `NullReporter` and a `TqdmReporter`. Pipeline code depends only on the protocol, never on `tqdm` directly. Reporters are passed in the way `tts_provider` and `encoder` are today.

**When it is shown**
- New root option `--progress/--no-progress` plus `general.progress: "auto" | "always" | "never"` (default `auto`) and env `PDF2AUDIOBOOK_PROGRESS`.
- `auto` shows progress only when stderr is a TTY.
- Progress is always disabled under `--json` and `--quiet`, overriding `always`. Progress goes only to stderr, so stdout stays parseable.
- Log events printed while a bar is active go through `tqdm.write` (or the bar is cleared first), so lines don't interleave with the bar.

**Stages and units**

| Stage | Unit | Total and initial | Detail |
| --- | --- | --- | --- |
| Extraction | page | page count; OCR'd pages advance as they finish | — |
| Analysis | request | planned LLM requests per enabled stage (structure, cleanup, classification, narration, contents, vision); cache hits advance immediately | stage name, e.g. "cleanup" |
| Synthesis | character | narration characters of the selected chapters; already-valid cached chapters and resumed chunks count toward `initial` | `chapter i/n` |
| Encoding and `pack-m4b` | chapter | chapter count | — |

- If the analysis request total isn't known in advance, show an indeterminate counter with elapsed time instead of an ETA.
- The single ffmpeg M4B encode is indeterminate: elapsed time only.
- Counting synthesis in characters makes the ETA track text length rather than chunk count.

**ETA**
- Use tqdm's smoothed rate.
- Show "estimating…" until at least one unit of real (non-cached) work completes, so cached work doesn't make the estimate wildly optimistic. The reporter excludes `initial` from the rate.
- On completion, in non-quiet, non-JSON mode, print a single content-free summary line per command, e.g. "Converted 12 chapters in 41m 07s".

**Privacy**
- Bar descriptions and details contain only stage names, counts and chapter numbers. Never chapter titles, book text, voice IDs from the book, model output or paths.
- Third-party stdout silencing (PyMuPDF, kittenml) is unchanged.

**Acceptance:**
- A recording reporter receives the correct stage totals, initial values and advances for:
  - a fake-provider conversion;
  - a resumed conversion with one cached chapter;
  - an analysis with cache hits.
- A `TqdmReporter` writing to a fake TTY `StringIO` shows the stage name, a count and an ETA field, and the output contains no fixture book text or temp path.
- `--json` and `--quiet` runs produce no progress output and parseable stdout.
- Non-TTY `auto` produces none.
- `--progress` with `--json` still produces none.
- CLI smoke and the packaging smoke pass with the new dependency.

## 5. Identity and schema changes

- R4 and R5 add no manifest fields. The artifact-state and journal formats are unchanged (version 1), and backups live outside managed names. The planner must ignore `chapter-backups/` and `workspace-backups/`.
- R10 and R11 change no fingerprints or schemas.
- `general.progress` and `timeout_seconds` are new config keys: document them in the config reference and the default config output.

## 6. Validation

For each requirement, add focused deterministic tests, then run `/verify`. Run mypy on 3.12 and 3.13 as well. Report skipped external-tool checks (ffmpeg, tesseract, node) as limitations. No test may require a live model or network access.
