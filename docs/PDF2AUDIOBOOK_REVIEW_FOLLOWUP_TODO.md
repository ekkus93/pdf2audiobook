# PDF2Audiobook Review Follow-up TODO

**Status:** Complete, with follow-up fixes tracked in `docs/PDF2AUDIOBOOK_FOLLOWUP_FIXES_TODO.md`; optional Kitten synthesis smoke test passed
**Date:** 2026-10-27
**Specification:** `docs/PDF2AUDIOBOOK_REVIEW_FOLLOWUP_SPEC.md`

Work in dependency order. Check an item only after its implementation and acceptance checks are complete. Keep fixes and behavior-preserving refactors reviewable; record actual results and any skipped checks.

## 1. Establish the contract

- [x] Map every reader and writer of chapter text, manifests, coverage, audio fingerprints and packaging freshness, including CLI dry-run and review paths (R1–R3). Evidence: current artifact and dependency map in the companion spec; inspected `pipeline.py`, `cli.py`, `review_ui.py`, `document/structure.py` and `workspace.py`.
- [x] Add deterministic regression tests that reproduce loss of a manual correction and voice marker, the misleading review failure, and review rendering with a non-default footnote policy. Confirm the tests exercise the public workflows. Evidence: `uv run pytest -q tests/test_review_followup_regressions.py` produced three expected failures on the unchanged implementation; the tests call analysis and review save entry points.
- [x] Design the artifact baseline, policy storage and recoverable transaction format together. Document commit and recovery states, compatibility with existing workspaces, conflict messages and the explicit recovery procedure in the spec before implementation. Evidence: design decisions in the companion spec.

## 2. Protect edited narration

Progress: the renderer plans guarded chapter updates and publishes them through the transaction journal. Review uses the recorded policy. Selection and packaging inspect effective chapter text. An offline fake-provider test covers a correction and voice marker through conversion and packaging, including stale audio after another edit. The dry-run, legacy end-to-end and no-mixed-consumption acceptance cases were found missing in the 2026-10-27 review and are tracked by `docs/PDF2AUDIOBOOK_FOLLOWUP_FIXES_TODO.md` §6.

The older streamed-resume and packaging tests were updated to exercise preservation and to create a known generated baseline; an additional packaging test now asserts edited text invalidates older audio. The full `uv run pytest -q -ra` run passed 1546 tests and skipped the optional Kitten smoke test (extra unavailable). After the final directory-sync adjustment, 43 focused recovery, artifact and locking tests passed, including failure while syncing the committed transaction record.

Subsequent validation with the Kitten extra installed: the offline suite passed 1547 tests and skipped its opt-in Kitten case; `PDF2AUDIOBOOK_KITTEN_SMOKE=1 uv run --locked --extra kitten --extra dev pytest -q -ra tests/test_kitten_real_smoke.py` passed that case separately. Ruff, Ruff format, mypy and `uv lock --check` passed.

- [x] Track chapter identity, last generated digest and relevant rendering inputs durably; validate metadata and update it under the workspace lock (R1). Evidence: `chapter_artifacts.py`, transaction-backed rendering, and `tests/test_chapter_artifact_plan.py`.
- [x] Adopt matching legacy files safely; preserve differing or untracked files and give a content-free conflict and recovery action. Evidence: planner tests and README recovery guidance; further integration cases remain under the acceptance item below.
- [x] Regenerate proven unmodified files, preserve compatible edited files, and reject ambiguous changes before any destructive publication. Handle missing, removed, remapped and renumbered chapters safely. Evidence: guarded planner and tests for source changes, missing observed edits, removed or untracked chapters and boundary conflicts.
- [x] Route review, analysis, conversion, dry-run, empty-chapter checks and packaging through the same effective chapter text. Ensure edits and voice markers affect audio and packaging freshness without changing approval rules. Evidence: fake-provider conversion and packaging regression, edited empty-chapter test and existing review-gate tests.
- [x] Add the R1 acceptance cases, including fake-provider conversion, legacy files, boundary and cleanup changes, deletion, stale audio, privacy and lock behavior. Evidence: `tests/test_chapter_artifact_plan.py` and `tests/test_review_followup_regressions.py` cover those cases, including renumbering and changes after planning; existing workspace-locking tests cover lock contention.

## 3. Make review saves recoverable

Evidence: review and artifact publication record a committed transaction containing guarded target contents; workspace-locked reads recover interrupted publication. The regression module covers the commit-record sync, manifest, coverage, metadata, both chapter files, cleanup, edited targets during recovery, fresh-process recovery and HTTP committed status.

- [x] Validate updates and conflicts before publishing; stage all affected artifacts and implement the documented durable commit and recovery protocol (R2). Evidence: `review_transaction.py` and precommit conflict tests.
- [x] Recover interrupted transactions before workspace operations expose or consume mixed state. Ensure recovery is idempotent and protects user edits. Evidence: workspace-lock recovery, fresh-process and external-edit tests.
- [x] Return distinct, truthful outcomes for rejected saves and committed saves needing recovery; update browser messages and retain lock-conflict behavior. Evidence: HTTP committed-recovery test and existing review-server and workspace-locking tests.
- [x] Add fault-injection tests at each commit and recovery boundary, including restart, repeated recovery, HTTP responses and preservation of existing files. Evidence: regression tests inject journal staging, all changed artifact writes, journal cleanup and recovery conflicts, including a fresh subprocess and HTTP 503; existing review tests cover rejected requests and HTTP 409.

## 4. Persist the rendering policy

- [x] Resolve and validate the workspace footnote policy for analysis, review, conversion, dry-run and packaging (R3). Evidence: stored artifact policy and policy-specific analysis/review/conversion tests.
- [x] Handle explicit policy changes and legacy workspaces according to R1; include the policy in relevant generation and audio freshness identities. Evidence: policy identity, sidecar validation and edited-policy conflict test.
- [x] Add end-to-end coverage for all four policies, restart, policy changes, edited text conflicts, legacy workspaces and packaging freshness. Evidence: `test_footnote_policy_survives_analyze_review_and_convert` checks all four through packaging, `test_footnote_policy_change_rejects_edited_chapter` covers policy conflicts, and planner and restart tests cover legacy and recovery paths.

## 5. Improve module boundaries

- [x] Document the responsibilities and dependency map of the pipeline, document structure, audio and LLM modules (R4). Evidence: the companion spec's current artifact and dependency map.
- [x] Extract cohesive chapter artifact and review transaction components, then split other responsibilities where the map supports it. Preserve interfaces or update and document callers deliberately. Evidence: `chapter_artifacts.py`, `review_transaction.py`, and `audio/freshness.py`; the pipeline retains the sidecar validator import.
- [x] Add new runtime modules to mypy configuration and run existing and new tests after each behavior-preserving extraction. Evidence: mypy passed 27 modules at that commit (41 after the later module split and the addition of `narration.py`, tracked in `docs/PDF2AUDIOBOOK_FOLLOWUP_FIXES_TODO.md` §0); `uv run pytest -q tests/test_cache_depth_reaches_check.py tests/test_mp3_resume_id3_integrity.py tests/test_pack_m4b_safety.py tests/test_pack_m4b_manifest_text.py` passed 21 tests after moving sidecar validation, followed by the full suite.

## 6. Finish and verify

- [x] Update README and maintainer guidance for chapter editing, voice markers, conflicts, recovery, footnote settings and legacy workspaces.
- [x] Run focused regression tests, `uv run pytest -q -ra`, `uv run ruff check .`, and `uv run mypy`; run `uv lock --check` if dependencies changed. Evidence: 1546 passed and 1 optional Kitten smoke skipped; Ruff and mypy (27 modules) passed. Dependency declarations did not change.
- [x] Review the final diff against every acceptance criterion and record unresolved limitations without marking incomplete work done. Limitations: unobserved edits deleted between operations cannot be recovered; the journal has a 512 MiB size limit; POSIX process locking and directory fsync are unavailable on Windows. These are documented in the README and maintainer guide.
