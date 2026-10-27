# PDF2Audiobook Review Follow-up Specification

**Status:** Implemented
**Date:** 2026-10-27
**Companion:** `docs/PDF2AUDIOBOOK_REVIEW_FOLLOWUP_TODO.md`

## Purpose and scope

Address the review findings about destructive chapter text regeneration, review-save failure reporting, the footnote policy used by the review editor, and the concentration of responsibilities in large modules. This specification supplements the existing project and review specifications. If an existing requirement conflicts with preservation of user-edited chapter text, update the affected documentation and tests to reflect the behavior below.

The observations are based on code inspection; the implementation work must first reproduce the defects with deterministic regression tests. Preserve source provenance, explicit review gates, privacy of book text and paths, and existing workspace locking. Do not require a live model or network for the default tests.

## Current artifact and dependency map

- `pipeline.analyze_book` holds the workspace lock, reads and writes the manifest, and calls `document.structure.render_chapter_texts` on both resume and fresh analysis. That renderer writes numbered chapter files and `coverage.json` and removes stale numbered files.
- Conversion holds the same lock, calls analysis, computes review selection from manifest blocks, renders chapter files again, reads them for voice validation and synthesis, and writes MP3 sidecars containing text hashes and rendering inputs. It rechecks text before synthesis.
- CLI dry-run calls analysis and then selection from the manifest. `pack-m4b` reads the manifest and sidecars, reconstructs chapter text from manifest blocks and the sidecar policy, and compares hashes before encoding. Neither operation currently uses a shared editable-text selection.
- Review GET reads the manifest; POST holds the lock, validates coverage, writes the manifest, then renders chapter files with the renderer's default policy. Other manifest writes include review acknowledgement and empty-chapter refresh. `workspace` provides atomic individual-file writes and locking, not a multi-file transaction.
- `document.structure` owns source coverage and narration rendering; `pipeline` coordinates extraction, analysis, selection and conversion; `audio` owns chunking, synthesis and encoding; `llm` owns provider requests and analysis proposals. The CLI connects these workflows. Artifact state and review transactions should be separate components depending on these existing primitives, without making structure depend on the pipeline.

## Design decisions for implementation

Store versioned chapter artifact metadata in the workspace, keyed by chapter ID with its number, generated digest, source/rendering identity and an observed edited flag. Record the validated footnote policy there. A source/rendering identity covers the relevant source block range and content, accepted edits and policy; titles and voice selection alone do not change the chapter text. Validate metadata before using it and fail closed on malformed state. The observed edited flag records edits when an operation sees them; deletion before any operation observes an edit is inherently indistinguishable from deletion of a generated file and must be documented.

Plan changes entirely in memory and verify current file digests before publication. When baseline metadata is absent, adopt only files matching the applicable rendering; otherwise stop with a chapter-number-only conflict instructing the user to back up the file and restore generated text or use a fresh workspace. Never automatically overwrite the backup. A review opened on a legacy workspace with no policy must safely establish a policy only when its files match that rendering; otherwise it must refuse to rewrite them. Explicit configuration changes are applied through analysis/conversion, subject to the same conflict checks.

For review, stage the new manifest and artifact set and atomically publish a durable committed transaction record containing validated relative targets and old/new digests. Publication of that record is the commit point: before it, discard staged work without touching committed artifacts; after it, recovery must complete the manifest and derived files. Publish each target only if its digest still matches its planned old or new state; otherwise leave the transaction pending and report recovery needed. Recovery runs while holding the workspace lock, is idempotent, and never follows untrusted transaction paths or overwrites changed files. Flush staged data and relevant directories as needed for the claimed durability. Every workspace entry point that can read or mutate committed state must recover or refuse before using it. A post-commit error identifies the committed state and recovery action without disclosing content or paths. This commit point avoids ambiguity when the old and new manifests are byte-identical.

## R1: Preserve chapter text edits

`chapters/NNN.txt` is an editable narration artifact. Users can add paragraph voice markers and make other text corrections. Analyze, resume, convert, review and packaging must never silently replace or delete those edits. Voice markers in a manually approved chapter must reach voice validation, synthesis, audio fingerprinting and packaging freshness checks as part of the actual narration text.

Track, per chapter, a durable identity and the digest of the last generated text, together with the rendering inputs needed to establish that baseline. Store metadata atomically under the workspace lock. Determine whether a file is unmodified by comparing it with that baseline, not by assuming any difference from a newly rendered chapter is disposable. Do not store book text in diagnostics or metadata when a digest suffices.

- If a file still matches its recorded generated baseline, regenerate it when boundaries, accepted cleanup or rendering settings change; update its baseline as part of the same recoverable operation.
- If a file differs from its baseline, preserve it byte for byte. Reuse it when its source boundaries and rendering inputs remain compatible. If a change would make its association or interpretation ambiguous, stop with a content-free conflict identifying the chapter number and a concrete recovery action; do not overwrite or delete the file or commit a conflicting review update. Never merge text automatically.
- Recreate a missing generated file from the manifest. A deleted edited file cannot be reconstructed; documentation must explain backups and recovery. A missing file with a known edited state must produce a conflict rather than fabricate the user's edits.
- When chapters are removed, renumbered or remapped, remove only files proven to be unchanged generated artifacts. Preserve edited or untracked files and report conflicts before changing the corresponding manifest. Ensure one chapter cannot claim another chapter's file.
- Existing workspaces without baseline metadata must be safe: a file that exactly matches the current rendered result can be adopted as generated; otherwise treat it as potentially edited and preserve it. Do not infer that a differing legacy file is disposable. Provide a documented, explicit recovery path that does not destroy the original.

All paths that inspect chapter content, including empty-chapter decisions, dry-run, conversion and M4B packaging, must use the same effective text and compatible rendering policy. Changed effective text must invalidate relevant audio and packaging freshness checks. Existing review approvals and book-wide acknowledgement rules remain in force; editable text does not automatically approve a chapter or waive a review reason.

**Acceptance:** End-to-end offline tests add a voice marker and a separate correction to an approved chapter, resume analysis and convert using a fake TTS provider, and assert exact bytes and spoken voice/text. Cover unmodified regeneration, missing files, changed boundaries and cleanup, removed and renumbered chapters, legacy workspaces, empty text, stale audio, dry-run and packaging. Conflicts must preserve all user files and avoid leaking text or paths. Exercise changes between planning and use under the workspace lock.

## R2: Recoverable review saves and truthful results

A review save changes the manifest, generated chapter files, coverage report and generation metadata. Validate the entire update and all edit conflicts before publishing. Stage the new artifacts, then use a durable transaction record and a defined manifest commit point, or an equivalent recoverable protocol, under the workspace lock. Individual atomic renames alone do not make a multi-file update atomic.

Before the commit point, failure must leave the previous committed review state usable and report that the update was not saved. After the commit point, failure must report that the update was committed but derived files need recovery; it must never claim no changes were saved. On the next workspace operation, detect an interrupted transaction and complete or safely roll it back according to the commit state before exposing files or allowing conversion. Recovery must be idempotent and must not overwrite edited or untracked chapter files. Preserve the current 409 response for lock contention and use content-free diagnostics for other failures.

The browser must distinguish a validation or pre-commit failure from a committed update needing recovery, and tell the user the next action. Successful responses mean the committed manifest and derived artifacts are consistent. Keep explicit acknowledgements separate from chapter approval.

**Acceptance:** Inject failures at staging, transaction recording, manifest publication, each derived-file publication, cleanup and recovery; include interruption followed by a fresh process or server. Assert the reported outcome matches the persisted state, no edits are lost, repeated recovery is safe, and conversion never consumes a mixed transaction. Exercise the HTTP response and browser message as well as direct save calls.

## R3: Consistent footnote policy in review

Review saves must render with the same effective `pdf.footnotes` policy as the workspace's analysis and conversion. Persist or otherwise resolve that policy as a validated workspace rendering input, rather than silently substituting `warn` when review starts without the original configuration. Define how a caller explicitly changes the policy, including conflict handling for edited text under R1. Existing workspaces lacking a recorded policy must use a safe, documented resolution and must not silently rewrite a differing chapter file.

Keep analysis, review, dry-run, conversion and packaging aligned on the resolved policy and effective text. Include policy changes in the appropriate generation and audio freshness identities. Maintain the existing source-block provenance and footnote placement behavior.

**Acceptance:** For `warn`, `inline`, `end` and `omit`, analyze a fixture with a classified footnote, save a review, and assert the chapter bytes and subsequent narration match the selected policy. Cover review after restart, changed policy, edited chapter conflicts, legacy metadata and packaging freshness.

## R4: Reduce concentration of responsibilities

Refactor the large pipeline, document structure, audio and LLM adapter modules in small, behavior-preserving steps. First map their responsibilities and dependencies, then extract cohesive units with clear typed interfaces. Prioritize the chapter artifact and review transaction boundary introduced above; separate unrelated policy, persistence and orchestration where the dependency map supports it. Keep existing public imports and CLI behavior compatible, or document and deliberately update every affected caller. Avoid circular dependencies and add new runtime modules to the configured mypy file list.

This is a maintainability improvement, not a requirement to split files at an arbitrary line count. Do not mix unrelated behavior changes into refactor steps. The existing offline suite and the new regression tests must continue to pass; record the resulting module responsibilities in maintainer documentation.

## Validation and documentation

Use focused deterministic tests for each requirement, followed by `uv run pytest -q -ra`, `uv run ruff check .`, and `uv run mypy`. Run `uv lock --check` if dependencies change. Report unavailable external-tool or optional-model checks as limitations rather than claiming they passed. Update the README and maintainer guide with editing, conflicts, recovery, policy persistence and upgrade behavior. Do not commit real book content, credentials or workspaces.
