# PDF2Audiobook — Long Function Split Specification

**Status:** Draft; S1–S12 not implemented
**Date:** 2026-11-13
**Baseline:** master at 18681585b45a02b0e697b64c03ac38c513a28247
**Parent specification:** `docs/PDF2AUDIOBOOK_SPEC.md` (§12 engineering principles)
**Companion:** `docs/PDF2AUDIOBOOK_LONG_FUNCTION_SPLIT_TODO.md`

## 1. Purpose and scope

The code is split into many modules, but a few functions have grown to 200–550 lines. Their behaviour depends on statement order across hundreds of lines, and the fourth review found most of its high- and medium-severity bugs inside them:

- hand-edit protection and review gating in `_analyze_book_locked`;
- chapter selection and packaging in `_convert_analyzed_book`;
- page-number ambiguity in `pagination_cleanup`.

This work splits those functions into named steps. **It is a pure refactor: no behaviour changes.** Every output must stay byte-identical:

- manifests, chapter texts, reports, warnings and review reasons;
- audio files and their sidecars;
- ledger rows and cache entries;
- CLI output and exit codes.

Measured at the baseline with Python's `ast` module (lines include nested functions):

| ID | Function | Location | Lines | Notes |
| --- | --- | --- | --- | --- |
| S1 | `pagination_cleanup` | `src/pdf2audiobook/document/pagination.py:178` | 437 | Pure function; 3 nested helpers; 69 branches |
| S2 | `propose_chapters` | `src/pdf2audiobook/document/structure.py:386` | 448 | Pure function; 72 top-level statements |
| S3 | `_analyze_book_locked` | `src/pdf2audiobook/pipeline.py:248` | 553 | Whole analysis; `pipeline.py` imports 21 project modules |
| S4 | `_convert_analyzed_book` | `src/pdf2audiobook/conversion.py:49` | 421 | 12 parameters; 2 nested callbacks |
| S5 | `synthesize_chunks` | `src/pdf2audiobook/audio/__init__.py:480` | 308 | 14 parameters |
| S6 | `_complete_json_call` | `src/pdf2audiobook/llm/cache.py:265` | 264 | Budget reservation, caching and settlement in one body |
| S7 | `_complete_json_request` | `src/pdf2audiobook/llm/provider.py:354` | 262 | 9 nested settle closures |
| S8 | `extract_pdf` | `src/pdf2audiobook/pdf.py:1127` | 225 | Page loop with inline OCR fallback |
| S9 | `convert` (CLI command) | `src/pdf2audiobook/cli.py:692` | 205 (140-line body) | 31 Typer options; the declarations are not counted |

S10–S12 are the cross-cutting requirements: the length guard (S10), behaviour-preservation evidence (S11) and documentation (S12).

**Out of scope:**
- changing what any function computes;
- fixing bugs found along the way (record them for a separate fix, §5);
- renaming public functions;
- splitting `cli.py` into one module per command group;
- functions under 200 lines.

## 2. Ground rules

Everything in parent spec §12 and CLAUDE.md applies. In addition:

- **No behaviour change.**
  - Don't change any fingerprint, schema version, cache-identity or sidecar version constant.
  - If a split changes an output, the split is wrong; never bump a version to hide it.
- **Existing tests are unchanged.** Don't edit any existing test's inputs, expected results or monkeypatch targets. New characterization tests (S11) may be added.
- **Monkeypatch compatibility.**
  - Tests patch names on module objects, for example `pipeline.propose_chapters`, `pipeline.render_chapter_texts`, `pipeline.read_manifest`, `pipeline.KittenProvider`, `pdf._ocr_page_lines` and `audio.time.sleep`.
  - Every patched name must still take effect after the split. Extracted code that calls a patched name either stays in the same module, or looks the name up through the module at call time.
  - The conversion code already does the latter through `ConversionServices`, and must keep doing so.
- **Facades stay.** `pipeline`, `document.structure`, `audio` and `llm/__init__` are re-export facades (CLAUDE.md). Keep every name they export today.
- **Privacy and errors are unchanged.**
  - Keep every exception type, fixed message, exit code and `from None`.
  - Don't move a `try` so it starts catching more, or less, than it does today.
- **Typed new modules.** Add any new module under `src/` to `[tool.mypy].files`.
- **One function per commit:** `refactor(<scope>): split <function> into named steps`. Each commit must pass `/verify` on its own.

## 3. Requirements per function

Each S1–S9 requirement has the same shape:

- The function becomes an orchestrator that calls named steps in the same order as today. Each step is a function with a docstring stating its inputs, outputs and the invariant it protects. The existing comments move with the code they describe.
- **Target:** the orchestrator and every extracted step, including nested functions, are at most **100 lines**. A Typer command's option declarations don't count toward its limit.
- State shared between steps is passed explicitly: as arguments, or as a small private dataclass for the run when more than about five values travel together. Don't use module-level mutable state.
- The boundaries below are proposals, based on the function's existing comments and blocks. Confirm them by reading the code, and record the actual split in the TODO evidence.

**S1 — `pagination_cleanup`.**
- Proposed steps:
  - validate page geometry (today's nested `valid_page`, `positions` and `page_label_matches`);
  - detect running heads, the repeated margin titles;
  - collect page-number candidates per margin band;
  - rank competing sequences and break ties;
  - check page labels and warn on mismatch;
  - build the `CleanupEdit` list, warnings and review reasons.
- The fail-closed rules (continuity with body text, quotations, list markers, headings, dialogue) each become a named predicate.

**S2 — `propose_chapters`.**
- Proposed steps:
  - typography evidence (size contrast and sentence checks);
  - contents-page and contents-run detection, including filling single-page gaps;
  - numbered and Roman heading candidates;
  - combining bookmark (TOC) anchors with text headings;
  - final ordering, merging and confidence.

**S3 — `_analyze_book_locked`.**
- Proposed steps:
  - load and validate the source, and decide on resume;
  - extract;
  - deterministic cleanup: the footnote policy, anchor digits and `pagination_cleanup`;
  - LLM proposals: headings, cleanup, narration, equations, contents and boundaries;
  - chapter proposal;
  - the hand-edit merge (today's `queue_change` and `map_boundary`);
  - warnings and review reasons;
  - write the manifest, chapter texts and reports.
- The steps stay in `pipeline.py`, because tests patch `pipeline.*` names. If any step moves to a new module, it reaches those names through the `pipeline` module at call time.

**S4 — `_convert_analyzed_book`.**
- Proposed steps:
  - load the manifest and apply review acknowledgements;
  - select chapters and preflight voice markers;
  - compute audio identities and decide which MP3s to reuse (including the tag check that guards against a corrupt MP3);
  - synthesize and encode one chapter;
  - publish and clean up obsolete audio;
  - write `conversion_status.json` and the conversion report.
- The 12 parameters stay as they are (callers pass them by keyword), but are gathered into a private run dataclass inside the module.

**S5 — `synthesize_chunks`.**
- Proposed steps:
  - validate arguments and engine metadata;
  - compute the chunk plan and cache keys;
  - replay a cached chunk or synthesize a new one, with retries;
  - stream the chapter WAV;
  - write progress.
- Keep validation that today runs before any engine call or cache replay in that position.

**S6 — `_complete_json_call`.**
- Proposed steps:
  - check the request bounds (the oversized-request rejection that happens before any reservation, and the image bound);
  - look up the cache;
  - check server-side limits, on a miss only;
  - reserve and settle per attempt (today's `start_attempt` and `settle_attempt`);
  - check verified usage.
- The fail-closed order is unchanged: no reservation before the bounds check, and no cache hit that skips the oversized-request rejection.

**S7 — `_complete_json_request`.**
- The 9 nested settle closures become methods, or functions that take an explicit attempt context.
- The retry loop becomes a short dispatcher over typed attempt outcomes.
- Every settle path keeps its exact ledger outcome and usage handling.

**S8 — `extract_pdf`.**
- Proposed steps:
  - open and validate the document;
  - choose each page's strategy and build its blocks, as in FX2.01b;
  - run the OCR fallback;
  - annotate special material (tables, covers, non-prose);
  - diagnose reading order;
  - check page labels.

**S9 — `convert` (CLI).**
- The 140-line body becomes a short handler. It builds the overrides, calls a `_run_convert` helper, and maps the result to output and an exit code.
- The `--dry-run` path becomes its own helper.
- Error handling (`typer.Exit` re-raise, `KeyboardInterrupt`, `fail()`) stays in the command function.

## 4. Cross-cutting requirements

**S10 — Length guard.**
- Add `tests/test_function_length.py`. It parses `src/pdf2audiobook/**/*.py` with `ast` and fails if any function or method is over a named limit.
- Its allowlist names the functions still over the limit, each with its current line count as a ceiling. A listed function may shrink but must never grow.
- Typer command functions are measured from their first body statement.
- After each S1–S9 task, remove that function from the allowlist.
- When all are done, the allowlist holds only functions this spec leaves out of scope, each with a reason.
- Set the limit to 100 lines. If S1–S9 leave a step that can't reasonably meet it, allowlist that step with a recorded reason rather than splitting it artificially.

**S11 — Behaviour-preservation evidence.**
- **Characterization tests first.** Before splitting a function, check that existing tests reach each of its major branches. Measure this with `coverage` run on the function's module, through `uv run --with coverage` so the lockfile is untouched.
  - If a branch named in §3 has no covering test, add a characterization test before the split. Such a test asserts today's output, and must pass at the baseline unchanged.
- **Golden analysis snapshot.** Add one end-to-end characterization test that runs `analyze` on the repository's synthetic fixtures (generated PDFs, `tests/fixtures/outlined_text.pdf` and the synthetic EPUB) with the LLM off. It compares these to a committed snapshot:
  - normalized `manifest.json`, with paths and the source hash normalized;
  - the chapter texts;
  - `coverage.json`;
  - the warnings and review reasons.

  Add it at the baseline, before S1, and never update it during this work.
- **Per split:** the full suite (now 2012 tests locally, with Tesseract and the `kitten` extra installed), mypy on 3.11–3.13, and exact-head CI all pass with no existing test changed. Record each function's line count before and after in the ledger.

**S12 — Documentation.**
- Update `docs/MAINTAINER_GUIDE.md`'s architecture section so it names the orchestrators and their steps for analysis and conversion.
- Add a sentence on the length guard and how to use its allowlist.
- Don't add an upgrade note: nothing persisted changes.

## 5. Bugs found during the work

If reading a function for a split reveals a bug:
- don't fix it inside the refactor commit, and don't change any test to match it;
- record it in the TODO's "Found during split" list, with `file:line` and a concrete scenario, for a separate fix round.

A refactor that would have to change behaviour to stay readable stops, and the decision goes to the user.

## 6. Acceptance criteria

- S1–S9: each function in §1 is at most 100 lines (S9 measured from its body), or is allowlisted by S10 with a recorded reason. So is every step extracted from it.
- S10: the guard test passes and fails if any listed function grows. Show this by temporarily adding lines in a scratch worktree.
- S11: the golden snapshot and all characterization tests are committed before S1 and pass unchanged at every commit. The full suite passes with no existing test edited.
- No fingerprint, schema, cache-identity or sidecar constant changes between the baseline and the final commit. Check this with `git diff` on those constants.
- `/verify` passes, mypy passes on 3.11–3.13, and exact-head CI passes for every refactor commit.
- S12 is merged.
