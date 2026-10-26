# PDF2Audiobook — Fourth Review Fixes TODO

**Status:** FX10.00–FX10.32 complete; FX10.33 closure is next.
**Date:** 2026-10-26
**Baseline:** master at 6eedfa4 (`docs: record fx9 completion and ci evidence`)
**Specification:** docs/PDF2AUDIOBOOK_FOURTH_REVIEW_SPEC.md (requirement IDs R80–R112)
**Previous review TODO:** docs/PDF2AUDIOBOOK_REVIEW_FIXES_TODO.md (FX0–FX9)
**Parent TODO:** docs/PDF2AUDIOBOOK_TODO.md

## Working rules

- Work dependency-first, in the order below, including every subtask. Use [x] only when the implementation exists and its named tests pass; otherwise leave [ ]. Check a parent only when all of its subitems are checked.
- Every fix task has three parts unless it says otherwise:
  - (a) add the regression tests, run them against the parent commit, and record the failing test IDs (parametrized case IDs, not counts) in the ledger row;
  - (b) make the fix;
  - (c) run `/verify`.

  A task marked **refactor** instead proves no behaviour change: the full suite passes unchanged.
- One fix per commit, with its tests. Use Conventional Commits with a scope (`fix(review): …`, `fix(cli): …`). Docs-only status changes go in their own `docs:` commits.
- Never change an existing test's inputs or expected results to make a change pass. Delete an obsolete assertion only with a reason in the commit message, and add a truthfully named replacement.
- If the implementation must differ from a requirement's text, amend the requirement in the spec in the same commit (spec §2).
- Make each fingerprint and schema bump in spec §10 once, in the task named below, and add its MAINTAINER_GUIDE upgrade note. Never migrate old manifests; reject them.
- Merge each spec §11 amendment into docs/PDF2AUDIOBOOK_SPEC.md in the same commit as its fix.
- Every new error path gets a `tests/test_*_privacy.py` test. Add every new `src/` module to `[tool.mypy].files`. CI stays offline.
- After CI finishes for a pushed fix, append a ledger row in a separate `docs: record … CI evidence` commit (`/record-ci-evidence`), with the full 40-character SHA of the commit it documents and real run IDs, including failed attempts. The ledger is append-only.
- A gated test (FFmpeg, Tesseract, Node) counts as evidence only when the CI skip summary shows it ran.
- Piper speaker-count validation stays deferred (spec §12).

## Phase FX10 — Fourth-review corrections

### Status and CI first

- [x] FX10.00 Correct the recorded status, in one `docs:` commit with no code changes (R112).
  - [x] FX10.00a In docs/PDF2AUDIOBOOK_REVIEW_FIXES_TODO.md, uncheck the items the fourth review found wrong: FX8.03a, FX8.06b, FX8.12a, FX8.18, FX9.07b, FX9.09b.
  - [x] FX10.00b Uncheck the items it found partial: FX0.03c, FX1.02b, FX1.04b, FX1.05a, FX2.01b, FX2.04a, FX3.01a, FX3.01b, FX3.02a, FX3.04b, FX4.01c, FX4.01d, FX5.01, FX5.05a, FX5.08a, FX5.10, FX6.03, FX7.01, FX7.02a, FX7.02c, FX7.03, FX8.02c, FX8.04a, FX8.04b, FX8.06c, FX8.06d, FX8.08c, FX8.09a, FX8.09b, FX8.12b, FX8.12c, FX8.14a, FX8.14e, FX8.15a, FX8.15b, FX8.15c, FX8.16b, FX9.02c, FX9.05a, FX9.05b, FX9.07c, FX9.09a, FX9.10a, FX9.10b, FX9.11b, FX9.12a, FX9.12b, FX9.14a, FX9.14b, FX9.15c, FX9.16a, FX9.19a, FX9.19b, FX9.19c. Also uncheck every parent of an unchecked item.
  - [x] FX10.00c Reword FX8.18 as "superseded by FX9.18".
  - [x] FX10.00d Append correction rows (don't edit existing rows) saying that:
    - the FX9.00 row labelled `1530a35` was written in 1e73dbe;
    - the FX9.19a row labelled 597ed1c was written in 6eedfa4;
    - CI run 40214615871 for 6eedfa4 succeeded and wasn't recorded;
    - the "N failed at the parent" counts in the FX9 rows include parametrized cases.
  - [x] FX10.00e In docs/PDF2AUDIOBOOK_TODO.md:
    - uncheck P0.03c, P4.01b and F.06's voice-marker subitem, and their parents;
    - name P5.05 and F.01 alongside F.06 in the status line;
    - update the `Date` line;
    - append a ledger row, plus a correction row saying the "worktree after 1664fdd" row's mypy count should be 19.
  - [x] FX10.00f Update both TODOs' status lines to point to this TODO.
- [x] FX10.01 Make CI show what ran (R111).
  - [x] FX10.01a Run `pytest -q -ra` in ci.yml. Install Node explicitly with a pinned major version, or document that the runner provides it.
  - [x] FX10.01b Add an assertion for `-ra` and the Node step to tests/test_ci_uv_pin.py (or a sibling). Update `/verify` and MAINTAINER_GUIDE.md.
  - [x] FX10.01c Record in the ledger the CI log lines showing the Tesseract, FFmpeg and Node tests ran.

**Checkpoint:** the status record matches this review; CI evidence for gated tests can be checked.

### High-severity fixes

- [x] FX10.02 Stop the catch-all swallowing `typer.Exit` (R89). **High.**
  - [x] FX10.02a Regression tests:
    - `batch` with one bad book exits 7, with one JSON value on stderr in `--json` mode;
    - a parametrized test over every command's non-zero `typer.Exit` path.
  - [x] FX10.02b Re-raise `typer.Exit` and `click.exceptions.Exit` before `except Exception` in every command.
- [x] FX10.03 Structured review reasons; empty chapters need per-chapter approval (R88). No manifest schema change.
  - [x] FX10.03a Regression tests:
    - the gate still fires when the damaged-source warning wording changes;
    - `--accept-review empty_chapter` exits 2 with no workspace changes;
    - a v3 manifest with `empty_chapter` in `review_acknowledged` gates its unapproved empty chapter and emits the warning event;
    - approve chapter 2 (empty), then empty chapter 3 by hand: convert refuses chapter 3 and skips chapter 2.
  - [x] FX10.03b Return review reasons as structured data from extraction and structure (no warning-string matching).
  - [x] FX10.03c Remove `empty_chapter` from the codes `--accept-review` accepts. Ignore a stored `empty_chapter` acknowledgement, with a content-free warning event.
  - [x] FX10.03d Document per-chapter approval of empty chapters in README.md and MAINTAINER_GUIDE.md, and merge the spec §11 §5 amendment.
- [x] FX10.04 Clear book-wide review reasons only by explicit acknowledgement (R80). **High.**
  - [x] FX10.04a Regression tests:
    - a title-only review-UI save, then `select_chapters` raises for `damaged_source` and for `ambiguous_page_numbers`;
    - the explicit control and `--accept-review` each unblock it;
    - the page offers a control for `ambiguous_page_numbers`.
  - [x] FX10.04b Chapter approval never waives a book-wide reason. Accept every book-wide code in `save_chapter_updates`, and render a control per present reason.
  - [x] FX10.04c Merge the spec §11 §5 amendment (book-wide reasons).
- [x] FX10.05 Make hand-edit protection survive valid edits (R81). **High.**
  - [x] FX10.05a Regression tests:
    - a coverage-valid two-sided boundary edit survives reanalysis, with its values asserted;
    - a title-only edit survives when the chapter's own start shifts by one block;
    - a title-only edit followed by a neighbour boundary change;
    - an edited chapter that becomes empty is reported;
    - a neighbour moved by an edit isn't reported as edited next time;
    - conflict messages contain the approve-or-revert instruction and no book text.
  - [x] FX10.05b Match old chapters to new chapters before applying edits: an exact generated start, else the unique containing range, else a conflict. Never match by number.
  - [x] FX10.05c Apply edited boundaries as a set, then check contiguous coverage. Keep `generated_*` and `generated_fingerprint` consistent after merges and neighbour moves.
  - [x] FX10.05d Merge the spec §11 §5 amendment (identity matching, approve-or-revert).

**Checkpoint:** a damaged book can't be converted without an explicit acknowledgement; valid hand edits survive reanalysis; `batch` failures exit 7.

### Manifest, review and packaging

- [x] FX10.06 Take the workspace lock before analysis and in review saves (R85).
  - [x] FX10.06a Regression tests:
    - with the lock held, `convert --no-resume` is refused and leaves `manifest.json` and `chapters/*.txt` byte-identical;
    - `analyze` is refused;
    - a review-UI POST gets 409 and the manifest is unchanged.
  - [x] FX10.06b Lock in `convert`, `analyze` and `batch` (per book) before any analysis. Use a non-blocking lock in review saves.
- [x] FX10.07 Share chapter selection between convert and dry-run (R83).
  - [x] FX10.07a Regression tests:
    - a hand-emptied chapter exits 6 in dry-run;
    - an approved empty chapter is listed as skipped;
    - dry-run logs `review_acknowledged` and writes nothing.
  - [x] FX10.07b Extract one function that applies acknowledgements, recomputes reasons and decides converted, skipped and refused chapters. Use it in convert and dry-run.
- [x] FX10.08 Make `pack-m4b` package every chapter convert produces, leaving out the ones it skips (R84, first step). No format change; the recorded rendering inputs and the sidecar bump come in FX10.31.
  - [x] FX10.08a Regression test: a book with an approved empty chapter packages with that chapter left out, and the output names it. Test the selection without FFmpeg; the happy path is FFmpeg-gated.
  - [x] FX10.08b Use the FX10.07 selection function in `pack-m4b`, and report skipped chapters by number.
  - [x] FX10.08c Merge the spec §11 §8 amendment (`pack-m4b` omits skipped chapters).
- [x] FX10.09 Small pipeline fixes (R82, R86, R87).
  - [x] FX10.09a Regression tests:
    - after approval, a `min_boundary_confidence` change is accepted;
    - an LLM-model change with the LLM disabled is accepted;
    - `convert --no-resume` on an approved workspace with unchanged settings succeeds in dry-run;
    - a dangling `audio/x.mp3` symlink survives a successful convert;
    - a rejected page-number removal survives reanalysis.
  - [x] FX10.09b Remove gate-only and disabled-LLM settings from the analysis fingerprint. Keep approved analysis on `--no-resume` with unchanged stages.
  - [x] FX10.09c Skip and warn on MP3 cleanup candidates that can't be inspected.
  - [x] FX10.09d Preserve deterministic edits whose `accepted` differs from the generated default.
  - [x] FX10.09e Merge the spec §11 §5 resume amendment.

### CLI, configuration and logging

- [x] FX10.10 Keep stderr to one JSON value in `--json` mode and "Error:" in human mode (R90).
  - [x] FX10.10a Regression tests:
    - `--quiet --json` failure gives one JSON value on stderr;
    - `--quiet` human failure starts with "Error:";
    - a config warning plus a failure in `--json` mode gives one JSON value containing the warning code;
    - in human mode the same gives `Warning:` and `Error:` lines and no `{`.
  - [x] FX10.10b Buffer events until the output mode is known. Put warnings in the JSON object's `warnings` array; render human `Warning:` lines. `--quiet` never adds output.
  - [x] FX10.10c Amend R72's decision text in the previous review spec. Merge the spec §11 §7 amendment and the §8 `warnings`-array contract. Document the `warnings` array in README.md.
- [x] FX10.11 Use one exit code for workspace failures (R91).
  - [x] FX10.11a Regression test: a parametrized CLI test over `analyze`, `convert`, `convert --dry-run`, `batch`, `review` and `pack-m4b` with an unusable `--output`, in text and JSON modes, asserting the code, the fixed message, and no path or errno text.
  - [x] FX10.11b Raise one typed workspace error; record its code per book in `batch`.
- [x] FX10.12 Configuration robustness (R92).
  - [x] FX10.12a Regression tests:
    - URLs with `#`, `?`, `/` and `@` in the password are fully redacted in `config show` and `--sources`;
    - a nested non-table section, with and without an env override, exits 2;
    - a non-vacuous secret-field redaction test.
  - [x] FX10.12b Redact the whole userinfo before parsing (redact everything if unparseable). Reject non-table values at any depth. Mark real secret fields, or register a test-only one.
- [x] FX10.13 Paired `--resume` and group help examples (R93, R94).
  - [x] FX10.13a Tests:
    - `--resume` and `--no-resume` override TOML on `analyze` and `batch`;
    - `budget --help` and `config --help` contain "Example".
  - [x] FX10.13b Add the options and the examples. Audit every pipeline-read boolean for a missing pair. Merge the spec §11 §8 amendment.
- [x] FX10.14 `budget` CLI edge cases (R95).
  - [x] FX10.14a Regression tests:
    - `budget show` on a v2 ledger works;
    - `resolve` of a missing ID and of a complete row each give their own message and exit 2.
  - [x] FX10.14b Read legacy ledgers read-only in `show`. Decide and implement legacy handling in `resolve`, and record the decision in the spec.

### Extraction and structure

- [x] FX10.15 **Refactor** extraction (R99).
  - [x] FX10.15a Remove `nearer_edge_than_body`, and `chapter_text` if only tests use it. Make `_valid_box` public or move it.
  - [x] FX10.15b Build the Roman-numeral tables once. Move the OCR fallback out of `extract_pdf`. Make `_classify_block_kind` the only kind decision.
  - [x] FX10.15c Compute each page's drawings and image info once, with the shared item cap.
- [x] FX10.16 One list classifier that respects footnotes and initials (R96).
  - [x] FX10.16a Regression tests:
    - numbered small-type footnotes stay `footnote`, and `--footnotes omit` removes them;
    - "A. Smith …" / "B. Jones …" stays one paragraph;
    - the "May / 12." and "page / 42)" wraps join;
    - a list followed by a same-margin body line keeps the paragraph separate.
  - [x] FX10.16b Classify footnotes before lists. Use one list classifier for block kinds and the join check. Apply the spec's list-end rule.
- [x] FX10.17 Decide page-number ambiguity among candidates only (R97).
  - [x] FX10.17a Regression tests:
    - two table-cell numerals at the foot give no warning and no review reason;
    - the sonnet fixture gives no label-mismatch warning;
    - 18pt vs 18.4pt is a tie and warns.
  - [x] FX10.17b Count only candidates. Compare only the chosen sequence with the labels. Add a named tie tolerance (2pt) documented in MAINTAINER_GUIDE.md.
- [x] FX10.18 Keep short valid text out of OCR (R98).
  - [x] FX10.18a Regression tests:
    - a "Part One" page with a 48-path ornament analyzes with Tesseract unavailable and has `embedded` origin;
    - `--ocr never` on an outlined page doesn't say "attempting OCR";
    - the single-rule page's warning wording.
  - [x] FX10.18b Apply the glyph-like-drawings rule only when there is no usable text. Name the actual outcome in each warning.
  - [x] FX10.18c Merge the spec §11 §4.1–§4.2 amendments.

### LLM budget and providers

- [x] FX10.19 **Refactor** the LLM request loop (R104).
  - [x] FX10.19a Split `_complete_json_request` into named settle paths with a `Literal` outcome type.
  - [x] FX10.19b Write the usage-validation predicate once. Build the capability-file path once and write it only on change. Remove or align the no-ledger budget path.
- [x] FX10.20 Settle JSON-mode rejections as `rejected` and remember them (R100).
  - [x] FX10.20a Regression test: three requests against a stub rejecting `response_format` give one `rejected` row and three `complete` rows, and the capability persists across provider instances.
  - [x] FX10.20b Settle the rejection `rejected`; store the fallback in the capability store.
- [x] FX10.21 Reject cumulative overflow at settlement (R101).
  - [x] FX10.21a Regression test: two 2^62-token responses leave `budget show` working, with the second row `unknown` and resolvable.
  - [x] FX10.21b Check cumulative totals inside the settlement transaction; settle with validated usage only.
- [x] FX10.22 Make `reserve` fail closed without a bound under any budget (R102).
  - [x] FX10.22a Regression test: an unbounded `reserve` under a token budget is refused.
  - [x] FX10.22b Refuse unbounded reservations under a token or USD budget. Amend the R70 decision text.
  - [x] FX10.22c Add truthfully named tests for the conditions the mis-named `…_blocks_…`, overspend and exact-exhaustion tests describe. Rename the existing tests to what they assert, with a reason in the commit message.
- [x] FX10.23 Parameter detection and model resolution (R103).
  - [x] FX10.23a Test: a context-length 400 mentioning `max_tokens`. If it shows the misfire, require an explicit unsupported-parameter phrase and never persist a capability from a context-length error. Otherwise record "not reproducible" in the ledger.
  - [x] FX10.23b Make `_model()` use the pipeline resolver. Test `auto` with two served models through the real `resolve_model`.
- [x] FX10.24 Merge the spec §11 §6.3 amendment, and fix parent spec §6.3 line 191.

### Audio and TTS

- [x] FX10.25 Turn every unspeakable paragraph into a pause (R105).
  - [x] FX10.25a Regression tests: `# # #`, `~~~`, `• • •`, `———` and `⁂` each make one pause entry and no TTS call, and coverage passes.
  - [x] FX10.25b Detect pauses from the spoken form (no letters or digits). Count them in `pause_count`.
- [x] FX10.26 Narration rules, remaining cases (R106).
  - [x] FX10.26a Regression tests:
    - `said—Hermione` applies the `hermione` key;
    - `O’Brien said.` applies an `o’brien` key;
    - `Dr.?` reads "Doctor?";
    - `1–<U+200B>2` reads "1 to 2";
    - `"—"` and `(—)` become pauses;
    - a punctuation-only key is rejected at load.
  - [x] FX10.26b Implement each rule. Extend the alignment property test to include pronunciations and chunk sizes from 20 to the default.
- [x] FX10.27 Bound progress bookkeeping (R107).
  - [x] FX10.27a Regression tests:
    - a 500k-character chapter with a no-op TTS keeps the correct `pause_count` within a time budget;
    - an oversized status file makes `inspect` print the fixed "too large" message.
  - [x] FX10.27b Make progress writes linear (append-only records). Warn and mark fields unavailable when a bounded read hits its cap.
- [x] FX10.28 Make voice-listing failures errors (R108).
  - [x] FX10.28a Regression test: a Kitten stub whose voice listing raises fails the marker chapter with `voice_list_unavailable`, exit 7.
  - [x] FX10.28b Raise `TTSError` from `list_voices`; skip validation only for providers that declare no voice list.
- [x] FX10.29 Small audio fixes and code health (R109).
  - [x] FX10.29a Tests:
    - the cover is read once per run;
    - after a size-limit error the progress status is `failed` and the chunk isn't `completed`.
  - [x] FX10.29b Read and hash the cover once. Track WAV bytes without the private `wave` attribute. Rename the two narration constants. Remove the dead check. Extract provider construction and voice/speed selection.

### Tests, fingerprints, documentation and closure

- [x] FX10.30 Close the test gaps behind checked items (R110). Add each test in the spec §8 table, citing the item it backs in the commit message.
  - [x] FX10.30a Manifest, review and CLI gaps: FX0.03c, FX1.02b/FX8.16b, FX3.01b, FX8.06d, FX8.15a, FX8.15b, FX9.07c, FX5.09.
  - [x] FX10.30b Budget gaps: FX4.01d, FX8.08c, FX8.09a, FX8.09b.
  - [x] FX10.30c Extraction gaps: FX8.02c/FX9.16a (folio near body text, failing at 2904f19), FX9.03 (replace "D. H. LAWRENCE"; whitespace one-letter numeral).
  - [x] FX10.30d Audio gaps: FX8.14a (batch validation), FX8.14e (`OSError` injection, chapter size limit), FX9.17 (version constant reaches the fingerprint).
- [x] FX10.31 Bump the fingerprints once (spec §10).
  - [x] FX10.31a Bump the extraction/analysis fingerprint to `analysis-v22` for R82, R96, R97 and R98.
  - [x] FX10.31b In one commit, make the R84 second step together with the chapter audio fingerprint bump for R105 and R106, so users regenerate audio only once:
    - record the rendering inputs (at least the footnote policy) in each MP3 sidecar and set `sidecar_version = 3`;
    - render with the recorded inputs in `pack-m4b`.

    Regression tests:
    - convert with `pdf.footnotes = "omit"`, then `pack-m4b --no-config`, verifies freshness;
    - a v2 sidecar is stale.
  - [x] FX10.31c Add the MAINTAINER_GUIDE upgrade notes, keeping the earlier notes as history. Merge the spec §11 §9 amendment (sidecars record rendering inputs).
- [x] FX10.32 Update the docs (R112).
  - [x] FX10.32a README.md: rewrite the budget section; document the paired `--no-*` forms and the `budget resolve` syntax.
  - [x] FX10.32b Parent spec: R31/R90 logging in §7, R75/R81 matching in §5; confirm every spec §11 amendment is merged.
  - [x] FX10.32c MAINTAINER_GUIDE.md: remove the stale v20 sentence; restore the v19 and mp3-v5 notes as history; document identity matching, the lock scope, the tie tolerance and the CI skip-summary check.
  - [x] FX10.32d Previous review spec: amend R79 for the FX9.16d page-number decision and the FX9.02c decision (superseded by R102).
- [ ] FX10.33 Closure.
  - [x] FX10.33a Re-check each item unchecked in FX10.00 only when the FX10 task that covers it (spec §13) is checked, citing that task's commit SHA. Re-check original-TODO items the same way.
  - [ ] FX10.33b Final gate:
    - `/verify` is green, with mypy on Python 3.11, 3.12 and 3.13;
    - the wheel/sdist smoke passes;
    - exact-head Python CI passes on all three versions;
    - the CI skip summary shows the Tesseract, FFmpeg and Node tests ran.

    Record the SHA and run ID below.

**FX10 gate:**
- a review-UI save never waives a book-wide review reason;
- coverage-valid hand edits and title-only edits survive reanalysis;
- `batch` failures exit 7;
- every command gives the same exit code for an unusable workspace;
- `--json` stderr is one JSON value and human stderr ends with "Error:", including with `--quiet`;
- numbered footnotes stay footnotes, and a table at the page foot doesn't block the book;
- a page with short valid text never needs Tesseract;
- JSON-mode fallbacks and overflowing usage can't deadlock the ledger;
- `pack-m4b` packages every book convert can finish;
- every new regression test is recorded as failing at its parent commit;
- the ledger is append-only and every status change is a git commit.

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
| 2026-10-25 | 6eedfa4c283e5eb54c4e17100e1d16c7be894949 | Fourth review of `0c19845..6eedfa4`: spec R80–R112 and FX10 drafted; no fixes implemented | Local at 6eedfa4: ruff, format, mypy (22 files) clean; 1331 passed, 32 skipped (FFmpeg, Tesseract and the Kitten extra absent locally). CI run 40214615871 succeeded | FX10.00 status correction pending |
| 2026-10-25 | f3cb375c769d38f2a281bb592b539ed059aa104b | FX10.00: corrected previous-review and original TODO statuses; added fourth-review spec and task plan; corrected the historical CI and mypy ledger notes. | Docs-only commit; `git diff --cached --check` passed; no code tests required. | FX10.01 CI skip-summary verification remains |
| 2026-10-25 | d9adb61f3a0b74ba81a98590f10e8a9535bf1427 | FX10.01a–b: CI prints pytest skip reasons and explicitly installs Node.js 22; `/verify`, AGENTS.md and MAINTAINER_GUIDE.md updated. At parent 6eedfa4, `test_ci_prints_pytest_skip_reasons` and `test_ci_installs_a_pinned_node_major_for_script_tests` failed as expected. | Local gates: uv lock check, Ruff, formatting, mypy (22 files), 1333 passed and 32 skipped with `pytest -q -ra`. FFmpeg and Tesseract are unavailable locally. | FX10.01c needs exact-head CI logs showing the FFmpeg, Tesseract and Node tests ran |
| 2026-10-25 | d9adb61f3a0b74ba81a98590f10e8a9535bf1427 | FX10.01a–c (R111): CI runs `pytest -q -ra` and sets up Node.js 22. | Exact-head CI [40236749174](https://github.com/ekkus93/pdf2audiobook/actions/runs/40236749174) passed on Python 3.11–3.13. Each job logged Node v22.23.3 and `1364 passed, 1 skipped`; the sole skip was the optional Kitten smoke, so the FFmpeg-, Tesseract- and Node-gated tests ran. Local `pytest -q -ra` with FFmpeg/Tesseract also passed: 1364 passed, 1 skipped. | None |
| 2026-10-25 | a441f66d273abaa57e1cbceb79a7b69e53175399 | FX10.02a–b (R89): command handlers preserve non-zero Typer/Click exits; partial batch failures use the exit-7 domain error and one JSON stderr diagnostic. | At parent 2f7c094, new regressions failed: `tests/test_cli_exit_propagation.py::test_commands_reraise_nonzero_typer_exit[config-show]`, `tests/test_cli_exit_propagation.py::test_commands_reraise_nonzero_typer_exit[budget-show]`, `tests/test_cli_exit_propagation.py::test_commands_reraise_nonzero_typer_exit[budget-resolve]`, `tests/test_cli_exit_propagation.py::test_commands_reraise_nonzero_typer_exit[doctor]`, `tests/test_cli_exit_propagation.py::test_commands_reraise_nonzero_typer_exit[inspect]`, `tests/test_cli_exit_propagation.py::test_commands_reraise_nonzero_typer_exit[analyze]`, `tests/test_cli_exit_propagation.py::test_commands_reraise_nonzero_typer_exit[convert]`, `tests/test_cli_exit_propagation.py::test_commands_reraise_nonzero_typer_exit[batch]`, `tests/test_cli_exit_propagation.py::test_commands_reraise_nonzero_typer_exit[pack-m4b]`, `tests/test_cli_exit_propagation.py::test_commands_reraise_nonzero_typer_exit[review]`, `tests/test_cli_exit_propagation.py::test_batch_failure_exits_7_with_one_json_stderr_value`, `tests/test_cli_exit_propagation.py::test_batch_reraises_exit_from_book_converter`, and `tests/test_cli_error_privacy.py::test_batch_partial_failure_diagnostic_is_content_free`. Local gates passed (lock check, Ruff, format, mypy 22 files, 1377 passed and 1 optional Kitten skip). Exact-head CI [40237347156](https://github.com/ekkus93/pdf2audiobook/actions/runs/40237347156) passed on Python 3.11–3.13 with 1377 passed and 1 skipped per job. | None |
| 2026-10-25 | 1919dfb115c14038f9fd428e9cba762f8a36bac1 | FX10.03a–d (R88): extraction and structure return review reason codes; empty chapters require chapter approval, legacy empty acknowledgements are ignored with a content-free warning, and README/maintainer/spec text is updated. Implementation commit: 86d44e88c31fafd51a1e4be3f931cc437170cae1; test isolation correction: this SHA. | At parent 5b3d416, these regressions failed as expected: `tests/test_review_gate_current_state.py::test_changed_damaged_source_warning_wording_keeps_structured_gate`, `tests/test_review_gate_current_state.py::test_accept_empty_chapter_exits_2_without_workspace_changes`, `tests/test_review_gate_current_state.py::test_stale_empty_acknowledgement_is_ignored_and_warned`, and `tests/test_review_gate_current_state.py::test_approval_skips_only_that_empty_chapter`. Local `/verify`: lock check, Ruff, formatting, mypy (22 files), 1382 passed, 1 optional Kitten skip. Initial exact-head CI [40239694217](https://github.com/ekkus93/pdf2audiobook/actions/runs/40239694217) failed because the new warning-wording test inherited the default Ollama-enabled setting; `1919dfb` disables LLM in that test. Corrected exact-head CI [40239836539](https://github.com/ekkus93/pdf2audiobook/actions/runs/40239836539) passed on Python 3.11–3.13, each with 1382 passed and 1 optional Kitten skip. | None |
| 2026-10-25 | cdd0e7e108e9a87a4e38f1b40376e07126c643b9 | FX10.04a–c (R80): approved chapters no longer waive book-wide reasons; review saves accept both book-wide codes and show a checkbox for each current reason. Parent spec §5 records the policy. | At parent 9cdd5a4, regressions failed: `test_title_only_review_save_does_not_waive_book_wide_reason[damaged_source-damaged source]`, `test_title_only_review_save_does_not_waive_book_wide_reason[ambiguous_page_numbers-ambiguous page-number]`, `test_explicit_review_ui_acknowledgement_unblocks_book_wide_reason[ambiguous_page_numbers]`, `test_cli_acknowledges_ambiguous_page_numbers_after_chapter_approval`, `test_review_page_offers_acknowledgement_control_for_ambiguous_pagination`, `test_page_script_names_voice_id_in_the_request_it_builds`, and both parametrized `test_book_wide_checkbox_is_shown_and_posted_only_when_ticked` cases. Local `/verify`: lock check, Ruff, formatting, mypy (23 files), 1389 passed, 1 optional Kitten skip. Exact-head CI [40240379096](https://github.com/ekkus93/pdf2audiobook/actions/runs/40240379096) passed Python 3.11–3.13, each with 1389 passed and 1 optional Kitten skip. | None |
| 2026-10-25 | 7a9a27c57c42d749d3e6fc18b8dcbd9c45db0c6d | FX10.05a–d (R81): hand edits are matched to regenerated chapters by generated start or unique containing range; boundaries apply together and coverage is checked; generated baselines stay coherent for moved neighbors; parent spec §5 merged. | At parent a910904, regressions failed as expected: `tests/test_hand_edit_chapter_identity.py::test_edit_whose_chapter_disappeared_is_a_content_free_conflict`, `::test_two_sided_boundary_edit_survives_reanalysis`, `::test_title_edit_matches_when_its_generated_start_moves_back_one_block`, `::test_title_edit_survives_a_later_neighbor_boundary_shift`, `::test_moved_unedited_neighbor_is_not_reported_as_an_edit_next_time`, and `tests/test_chapter_edit_privacy.py::test_unalignable_hand_edit_conflict_is_private_and_gives_next_step`. Local `/verify`: lock check, Ruff, formatting, mypy (23 files), 1395 passed, 1 optional Kitten skip. Exact-head CI [40240987465](https://github.com/ekkus93/pdf2audiobook/actions/runs/40240987465) passed Python 3.11–3.13 with 1395 passed and 1 optional Kitten skip per job; CI installed FFmpeg and Tesseract. | None |
| 2026-10-25 | 9e7b6412bda858307347a46fcba5996606e102b1 | FX10.06a–b (R85): analysis, conversion and review saves share a nonblocking per-workspace lock; the review API returns a fixed 409 while locked; §8 CLI contract updated. | At parent 793d7e2, all required regressions failed: `tests/test_workspace_locking_fx10.py::test_convert_no_resume_refuses_locked_workspace_without_rewriting`, `::test_analyze_refuses_locked_workspace`, and `::test_review_save_returns_409_without_writing_when_workspace_is_locked`. Local `/verify`: lock check, Ruff, formatting, mypy (23 files), 1398 passed, 1 optional Kitten skip. Exact-head CI [40241446543](https://github.com/ekkus93/pdf2audiobook/actions/runs/40241446543) passed Python 3.11–3.13, each with 1398 passed and 1 optional Kitten skip; FFmpeg and Tesseract were installed. | None |
| 2026-10-25 | 03fb1249c4c2a8ff2e7eb4c9215b3ef4340552b3 | FX10.07a–b (R83): convert and dry-run share chapter-gate selection, recompute empty-chapter reasons, report approved empty chapters as skipped, and log acknowledgements without dry-run writes; §8 CLI contract updated. | At parent 4439352, `tests/test_accept_review_flag.py::test_dry_run_reports_an_approved_empty_chapter_as_skipped` and `::test_dry_run_logs_acknowledgement_without_writing` failed; `::test_dry_run_refuses_a_hand_emptied_chapter` already passed. Local `/verify`: lock check, Ruff, formatting, mypy (23 files), 1401 passed, 1 optional Kitten skip. Exact-head CI [40241803578](https://github.com/ekkus93/pdf2audiobook/actions/runs/40241803578) passed Python 3.11–3.13 with 1401 passed and 1 optional Kitten skip per job; FFmpeg and Tesseract were installed. | None |
| 2026-10-25 | 1a4bab99fd9a7c563ffb8d8636055e383ab1fa42 | FX10.08a–c (R84, first step): `pack-m4b` uses shared chapter selection, omits approved empty chapters and reports skipped chapter numbers; no sidecar format change. | At parent b4219aa, `tests/test_pack_m4b_manifest_text.py::test_pack_omits_approved_empty_chapter_and_reports_its_number` failed because the approved empty chapter was treated as missing audio. Local `/verify`: lock check, Ruff, formatting, mypy (23 files), 1402 passed, 1 optional Kitten skip. Exact-head CI [40242048096](https://github.com/ekkus93/pdf2audiobook/actions/runs/40242048096) passed Python 3.11–3.13 with 1402 passed and 1 optional Kitten skip per job; FFmpeg and Tesseract were installed. | None |
| 2026-10-25 | deeef53bc585b46dc8afdc3d8d5606b2f2e5daba | FX10.09a–e (R82, R86, R87): gate-only and disabled-LLM settings no longer invalidate analysis; unchanged approved analysis is retained under `--no-resume`; MP3 cleanup skips uninspectable candidates with a content-free warning; rejected deterministic cleanup decisions are preserved or fail with a chapter-only conflict. Parent spec §5 resume amendment updated. | At parent 782f89a, these regressions failed: `tests/test_analysis_resume_fx10.py::test_approved_analysis_accepts_min_boundary_confidence_change`, `::test_disabled_llm_model_change_does_not_invalidate_approved_analysis`, `::test_no_resume_dry_run_keeps_approved_analysis_when_stages_match`, `::test_rejected_page_number_removal_survives_reanalysis`, `tests/test_convert_robustness_fx9.py::test_dangling_mp3_symlink_survives_successful_conversion`, and `tests/test_analysis_resume_privacy.py::test_unmatched_rejected_page_number_names_chapter_without_source_text`. Local `/verify`: lock check, Ruff, formatting, mypy (23 files), 1408 passed, 1 optional Kitten skip. Exact-head CI [40242577944](https://github.com/ekkus93/pdf2audiobook/actions/runs/40242577944) passed Python 3.11–3.13 with 1408 passed and 1 optional Kitten skip per job; FFmpeg and Tesseract were installed. The obsolete assertion that unchanged approved analysis must fail under `--no-resume` was replaced with the R82 requirement, as stated in the commit body. | None |
| 2026-10-25 | eeb011f0d3d33b7f55e4fc68f1d3cb72329ddafd | FX10.10a–c (R90): CLI buffers startup events until output mode is known; default human warnings use fixed `Warning:` lines, JSON results carry warning codes, and quiet mode leaves only the command error. R72 and parent spec §§7–8 plus README were updated. | At parent 999d66c, all four new regressions failed: `tests/test_cli_logging.py::test_quiet_json_failure_writes_one_error_object`, `::test_quiet_human_failure_starts_with_error`, `::test_json_failure_embeds_configuration_warning_code`, and `::test_human_failure_renders_warning_and_error_without_json`. Local `/verify`: lock check, Ruff, formatting, mypy (23 files), 1412 passed, 1 optional Kitten skip. Exact-head CI [40243089194](https://github.com/ekkus93/pdf2audiobook/actions/runs/40243089194) passed Python 3.11–3.13, each with 1412 passed and 1 optional Kitten skip; FFmpeg and Tesseract were installed. | None |
| 2026-10-25 | 1d2883cd44d750189fdfcc768e33660df7cc84cd | FX10.11a–b (R91): workspace writes and output failures use `WorkspaceError`, exit 4 and the fixed message; `batch` records code 4 per book while retaining aggregate exit 7. Parent spec §8 updated. | At parent 12f16e7, all 12 cases failed: `tests/test_workspace_failures_privacy.py::test_workspace_failure_has_one_fixed_private_diagnostic[human-analyze]`, `[human-convert]`, `[human-convert-dry-run]`, `[human-batch]`, `[human-review]`, `[human-pack-m4b]`, `[json-analyze]`, `[json-convert]`, `[json-convert-dry-run]`, `[json-batch]`, `[json-review]`, and `[json-pack-m4b]`. Local `/verify`: lock check, Ruff, formatting, mypy (23 files), 1424 passed, 1 optional Kitten skip. Exact-head CI [40243509697](https://github.com/ekkus93/pdf2audiobook/actions/runs/40243509697) passed Python 3.11–3.13, each with 1424 passed and 1 optional Kitten skip; FFmpeg and Tesseract were installed. | None |
| 2026-10-25 | abb5f6fc1cf9acfeed2d3712b93e654fb4840c84 | FX10.12a–b (R92): config URL credentials are redacted before URL parsing; malformed URLs redact fully; nested non-table config values fail content-free; test-only secret config path verifies real redaction. Follow-up test stabilization: c7cea51488f2c6df590c4d7cc1b797c4f56d3cbc warms the streaming memory probe before measurement, keeping its existing bound. | At parent 777d92a, failures: `tests/test_config_redaction.py::test_config_show_redacts_reserved_characters_in_url_password[config-only-private#HASH_SECRET-HASH_SECRET]`, `[config-only-private?QUERY_SECRET-QUERY_SECRET]`, `[config-only-private/PATH_SECRET-PATH_SECRET]`, `[with-sources-private#HASH_SECRET-HASH_SECRET]`, `[with-sources-private?QUERY_SECRET-QUERY_SECRET]`, `[with-sources-private/PATH_SECRET-PATH_SECRET]`, `::test_config_redaction_hides_unparseable_url_values`, and `tests/test_config_error_privacy.py::test_nested_non_table_config_section_is_content_free_config_error[with-env]`. Non-vacuous secret-field test passed at parent but exercises the registered test-only field. Local `/verify`: 1437 passed, 1 optional Kitten skip. Earlier exact-head runs 40243797795 (twice) and 40244049032 failed only `tests/test_long_chapter_wav_streaming.py::test_streaming_peak_memory_does_not_grow_with_chapter_length` on Python 3.13; the cold measurement included one-time interpreter/NumPy initialization. Exact-head follow-up CI [40244303490](https://github.com/ekkus93/pdf2audiobook/actions/runs/40244303490) passed Python 3.11–3.13 with 1437 passed and 1 optional Kitten skip per job; FFmpeg and Tesseract were installed. | None |
| 2026-10-25 | 46e46af30cc5fa9c91dc26a64f9f9358ffcbfe50 | FX10.13a–b (R93, R94): `analyze` and `batch` accept paired `--resume/--no-resume`, `budget` and `config` group help include examples, and parent spec §8 records the contract. | At parent f0fa9a3, all six cases failed: four `tests/test_resume_cli_overrides.py::test_resume_flags_override_config` cases (both commands × both settings/flags) and `tests/test_cli_help_examples.py::test_every_command_help_contains_an_example[arguments9]` (`config --help`) plus `[arguments10]` (`budget --help`). Local `/verify`: lock check, Ruff, format, mypy (23 source files), 1443 passed and 1 optional Kitten skip. Exact-head CI [40244570730](https://github.com/ekkus93/pdf2audiobook/actions/runs/40244570730) passed Python 3.11–3.13, including unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract were installed. | None |
| 2026-10-25 | 5f8aa274348f612055434fcae1144916ca6bed42 | FX10.14a–b (R95): `budget show` reads v2 ledgers without migration; `budget resolve` refuses v2 and earlier with the fixed re-create-ledger message; missing and settled IDs have distinct fixed messages and exit 2. The R95 decision is recorded in the fourth-review spec. | All four regressions in `tests/test_budget_cli_fx10.py` failed at parent d470d0d: v2 show was rejected, legacy refusal message was generic, and missing/complete row messages were generic. Local `/verify`: lock check, Ruff, format, mypy (23 source files), 1447 passed and 1 optional Kitten skip. Exact-head CI [40244899300](https://github.com/ekkus93/pdf2audiobook/actions/runs/40244899300) passed Python 3.11–3.13, including unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract were installed. | None |
| 2026-10-25 | 370b43516d893d17d3a1c4d6d63d33c272c1fd5c | FX10.15a–c (R99): removed unused folio helper and test-only `chapter_text`; exposed `valid_box` while retaining its old internal alias; hoisted Roman marker tables; extracted OCR fallback into `_apply_ocr_fallback`; centralized block kind decisions; gathered capped page image/drawing metadata once for reuse. | Refactor validation: local `/verify` passed (lock check, Ruff, format, mypy on 23 source files, 1447 passed, 1 optional Kitten skip). Exact-head CI [40245247117](https://github.com/ekkus93/pdf2audiobook/actions/runs/40245247117) passed Python 3.11–3.13, including unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract were installed. Chapter structure tests now form their text projection locally after removal of the test-only production helper; expected behavior remained the same. | None |
| 2026-10-25 | 10e5016464cf54c804e6763382a798345709060e | FX10.16a–b (R96): one contextual list classifier now serves extraction and line joining; footnote kinds win before list detection; sequential numbered notes receive audited omit edits; initials stay prose; wrapped May/page numbers join; sentence-final lists end before same-margin prose. R96 and parent spec §4.3 record list-end and colon-label details. | At parent 84074f6, all five cases failed in `tests/test_list_classifier_fx10.py`: sequential numbered footnotes were lists, A/B initials became lists, both May/page number wraps split, and same-margin body text joined the preceding list. Local `/verify`: lock check, Ruff, format, mypy (23 source files), 1452 passed, 1 optional Kitten skip. Exact-head CI [40245718067](https://github.com/ekkus93/pdf2audiobook/actions/runs/40245718067) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract were installed. | None |
| 2026-10-25 | c578b9a9525c0ad62d61e13eb2ea099ea786558a | FX10.17a–b (R97): pagination ambiguity now counts candidate numerals only; PDF labels are checked against the selected sequence; edge distances under the documented 2pt tolerance tie. Updated parent §4.2. | At parent b65cb3a, `tests/test_pagination_multiple_margin_numerals.py::test_table_cell_numerals_do_not_create_page_number_ambiguity`, `::test_edge_distances_within_two_points_are_tied`, and `tests/test_page_number_sequences.py::test_poem_numerals_survive_while_edge_folios_are_removed` failed. Local `/verify`: lock check, Ruff, format, mypy (23 source files), 1454 passed, 1 optional Kitten skip. Exact-head CI [40245977219](https://github.com/ekkus93/pdf2audiobook/actions/runs/40245977219) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract were installed. | None |
| 2026-10-25 | c9b82e28d906fd41cc281b0de7f51e110db46c3e | FX10.18a–c (R98): recognized short headings remain usable despite small ornaments; auto OCR's glyph-art trigger applies only without usable text; `--ocr never` no longer claims OCR was attempted; empty-page warnings distinguish disabled OCR, non-text-like drawings and no drawings; parent §§4.1–4.2 updated. | At parent 10ec872, these regressions failed: `tests/test_vector_outlined_text.py::test_short_embedded_heading_with_ornament_does_not_require_tesseract`, `::test_drawing_only_page_without_ocr_never_claims_ocr_is_not_needed`, and `::test_a_single_rule_is_not_sent_to_ocr`. Local `/verify`: lock check, Ruff, format, mypy (23 source files), 1455 passed, 1 optional Kitten skip. Exact-head CI [40246285382](https://github.com/ekkus93/pdf2audiobook/actions/runs/40246285382) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract were installed. | None |
| 2026-10-25 | ec618d407dee62cbaaaffa988ec5c2025664e2b9 | FX10.19a–b (R104): named settlement paths use a `Literal` outcome; shared token and complete-usage validation serves provider, cache and ledger; capability paths are centralized and unchanged files are not rewritten; direct budgeted wrappers use per-attempt ledger accounting. | No behavior-specific tests added per R104; full local `/verify` passed unchanged: lock check, Ruff, format, mypy (24 source files), 1455 passed, 1 optional Kitten skip. Exact-head CI [40246671206](https://github.com/ekkus93/pdf2audiobook/actions/runs/40246671206) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract were installed. | None |
| 2026-10-25 | c3c91eaf96ed0f0e209bfe2e0c3ae980a0c75439 | FX10.20a–b (R100): JSON-mode rejection without usage settles as `rejected`; provider capability files remember the unsupported JSON mode, so later provider instances omit `response_format`. | At parent 1b4cf1a, `tests/test_llm_retry_budget_attempts.py::test_json_mode_rejection_is_rejected_and_capability_persists_between_providers` failed because `response_format` was retried across each provider and rejected rows were not settled `rejected`. Local `/verify`: lock check, Ruff, format, mypy (24 source files), 1456 passed, 1 optional Kitten skip. Exact-head CI [40246884881](https://github.com/ekkus93/pdf2audiobook/actions/runs/40246884881) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract were installed. | None |
| 2026-10-26 | dca814c26131a9faacf06a5e0586ec4dbc6b7d66 | FX10.21a–b (R101): token-usage settlement validates the candidate ledger totals inside a savepoint in the settlement transaction; overflowing or unrepresentable candidates remain `unknown` with their bound; provider settlement uses the same capped counters as in-memory totals. | At parent 0f20082, `tests/test_llm_cumulative_usage_settlement.py::test_cumulative_usage_overflow_is_unknown_and_resolvable` failed: `budget show` returned exit 5 with cumulative token overflow. Local `/verify`: lock check, Ruff, format, mypy (24 source files), 1457 passed, 1 optional Kitten skip. Exact-head CI [40247192998](https://github.com/ekkus93/pdf2audiobook/actions/runs/40247192998) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract were installed. | None |
| 2026-10-26 | e39e3d16b27dc3f2cf017176f86feb87990a145f | FX10.22a–c (R102): `reserve` requires token and/or USD bounds whenever the matching book budget is active; updated R70 policy and corrected misleading budget tests, with explicit postflight overspend and exact-exhaustion coverage. | At parent ca9e384, `tests/test_llm_budget_fail_closed.py::test_reserve_requires_a_bound_for_each_active_budget[100-None-None-None]` failed as expected. Local `/verify`: lock check, Ruff, format, mypy (24 source files), 1466 passed, 1 optional Kitten skip. Exact-head CI [40247580412](https://github.com/ekkus93/pdf2audiobook/actions/runs/40247580412) passed on Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract installed. | FX10.23 parameter detection and model resolution |
| 2026-10-26 | 20a8d28b5ea1bfa040414d1160139cb2aba58ed4 | FX10.23a–b (R103): capability fallback now requires explicit unsupported-parameter wording and excludes context-length errors; `_model()` delegates to `resolve_model()` so ambiguous auto selection fails before chat. | At parent 5fb7c2b, `tests/test_llm_retry_budget_attempts.py::test_context_length_error_mentioning_max_tokens_does_not_remove_or_persist_cap` showed a context error marked `max_tokens` unsupported, and `tests/test_llm_provider_matrix.py::test_auto_model_with_two_served_models_fails_through_real_resolver` sent a chat request instead of raising. Local `/verify`: lock check, Ruff, format, mypy (24 source files), 1468 passed, 1 optional Kitten skip. Exact-head CI [40247879838](https://github.com/ekkus93/pdf2audiobook/actions/runs/40247879838) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract installed. | FX10.24 merged §6.3 budget amendment and clarified the parent budget spec |
| 2026-10-26 | 20a8d28b5ea1bfa040414d1160139cb2aba58ed4 | FX10.24: merged the §11 §6.3 budget amendment and corrected the parent §6.3 text: unresolved sent/ambiguous attempts count against budgets at their recorded bound and are resolvable; only legacy open rows without bounds block budgets pending resolution. | `git diff --check` passed; documentation-only change. | FX10.25 unspeakable paragraphs become pauses |
| 2026-10-26 | df5b10ed74b88e3046e79c307d0d49ab11c8a882 | FX10.25a–b (R105): every nonempty paragraph whose normalized spoken form has no letters or digits produces one pause mapping and increments `pause_count`; pause-only chapters render silence without a TTS call. Pipeline pause counts use the same range helper. | At parent fa9e475, all five required punctuation-only paragraph cases raised `Chapter has no speakable text` instead of recording pauses. Local `/verify`: lock check, Ruff, format, mypy (24 source files), 1473 passed, 1 optional Kitten skip. Exact-head CI [40248126997](https://github.com/ekkus93/pdf2audiobook/actions/runs/40248126997) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract installed. | FX10.26 narration rules, remaining cases |
| 2026-10-26 | 76a559e6240d420e400f0e597a931bc743c9eb72 | FX10.26a–b (R106): narration normalization is shared by pronunciation keys and spoken tokens; internal dash-joined words use pronunciation lookups; invisible characters are stripped before numeric-range rewrites; `Dr.?` preserves only `?`; punctuation-only keys are refused; quoted/bracketed bare dashes become pauses. Alignment coverage spans chunk sizes 20–350 with pronunciations. | At parent 2b2e312, tests reproduced missed dash-joined and typographic-apostrophe lookups, `Doctor.?`, `1, 2` for the invisible numeric-range case, and acceptance of `...` as a pronunciation key. Local `/verify`: lock check, Ruff, format, mypy (24 source files), 1481 passed, 1 optional Kitten skip. Exact-head CI [40248376352](https://github.com/ekkus93/pdf2audiobook/actions/runs/40248376352) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract installed. | FX10.27 bounded progress bookkeeping |
| 2026-10-26 | f0a7ab6945d02e3102ac51d1093b9a55a58d4636 | FX10.27a–b (R107): synthesis progress is append-only JSONL with per-record and total-file read bounds; unavailable/corrupt progress warns and reports null pause/mapping fields, preserving null in the aggregate; `inspect` reports an oversized conversion status file with a fixed message. | Added a 500k-character no-op-TTS test that verifies the pause count and completes within 15 seconds (3.5 seconds locally); tested oversized progress records and oversized status files, including warning and unavailable report fields. Local `/verify`: lock check, Ruff, format, mypy (24 source files), 1485 passed, 1 optional Kitten skip. Exact-head CI [40248915463](https://github.com/ekkus93/pdf2audiobook/actions/runs/40248915463) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract installed. | FX10.28 voice-listing failures are errors |
| 2026-10-26 | 5a3f7ca095905e1c23c087694a37be4093b1601d | FX10.28a–b (R108): Kitten voice discovery raises sanitized `TTSError` on failure; supported providers must supply a string list; providers such as Piper explicitly declare no voice list; marker validation failures record `voice_list_unavailable` and exit 7. | Local `/verify`: 1487 passed, 1 optional Kitten skip; final exit-7 assertion passed in the focused test. Exact-head CI [40249223933](https://github.com/ekkus93/pdf2audiobook/actions/runs/40249223933) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract installed. | FX10.29 small audio fixes and code health |
| 2026-10-26 | cc1a83e6a2f3b9ea68485c880bad993a03fd8532 | FX10.29a–b (R109): cover bytes/hash are shared across the run, WAV writes use an owned byte counter, narration version constants are clearer, dead code is removed, and TTS provider/voice/speed selection is shared. | Local `/verify`: lock check, Ruff, format, mypy (24 files), 1488 passed, 1 optional Kitten skip. Exact-head CI [40249587505](https://github.com/ekkus93/pdf2audiobook/actions/runs/40249587505) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract installed. | FX10.30 remaining regression tests |
| 2026-10-26 | a815144543e59fc77de5779eeb10dfe44de1c172 | FX10.30a–d (R110): added the missing manifest, review UI, budget, extraction and audio regressions; refined the existing warning and stage-event assertions. Folio-near-body removal fails at 2904f19 as required. | At 6eedfa4, the ambiguous-page acknowledgement, structured damaged-source warning, and warning-count tests failed. Local `/verify`: lock check, Ruff, format, mypy (24 files), 1505 passed, 1 optional Kitten skip. Initial exact-head CI [40250323860](https://github.com/ekkus93/pdf2audiobook/actions/runs/40250323860) found an enabled-Ollama test fixture and privileged-port test assumption; follow-up [40250510077](https://github.com/ekkus93/pdf2audiobook/actions/runs/40250510077) passed Python 3.11–3.13 with unit, CLI and wheel/sdist smoke; FFmpeg and Tesseract installed. | FX10.31 coordinated analysis/audio fingerprint and sidecar bump |
| 2026-10-26 | ba51e8fcd6cb460602651acefeafe47d5b9a5fc5 | FX10.31a–c: bumped analysis/audio identities, recorded narration inputs in v3 MP3 sidecars and made `pack-m4b` render with those recorded inputs; merged the §9 amendment and added the upgrade note. | Local `/verify`: lock check, Ruff, format, mypy (24 files), 1507 passed, 1 optional Kitten skip. Exact-head CI [40250700211](https://github.com/ekkus93/pdf2audiobook/actions/runs/40250700211) passed Python 3.11–3.13; each reported 1507 passed, 1 optional Kitten skip, and wheel/sdist smoke passed. FFmpeg, Tesseract and Node.js 22 were installed, so their gated tests ran. | FX10.32 documentation and closure |
| 2026-10-26 | b5b467940e27d5938933e4d3a3ef58e3cadeeff5 | FX10.32a–d (R112): rewrote the README budget accounting and recovery guidance, documented paired boolean overrides and actual resolve syntax, confirmed parent §5/§7 plus every §11 amendment, refreshed maintainer/history notes, and amended R79 decisions. | `git diff --check` passed; `budget resolve --help` confirms positional ID and option syntax. Parent spec contains R31/R90 logging contract and R75/R81 identity matching. | FX10.33 closure and final gate |
| 2026-10-26 | 926073d7a7c5f3984a338eabc7cc4b53009fad5f | FX10.33a: requalified every fourth-review reopening whose covering task is complete, and rechecked corresponding original-TODO items. Previous-review evidence by full task SHA: FX8.03a—FX10.02 `a441f66d273abaa57e1cbceb79a7b69e53175399`; FX8.06b and FX9.09a/b/9.10a/b—FX10.03 `1919dfb115c14038f9fd428e9cba762f8a36bac1` and FX10.04 `cdd0e7e108e9a87a4e38f1b40376e07126c643b9`; FX8.12a/c, FX3.01a/b and FX9.11b—FX10.05 `7a9a27c57c42d749d3e6fc18b8dcbd9c45db0c6d`; FX9.12a/b—FX10.06 `9e7b6412bda858307347a46fcba5996606e102b1`; FX8.12b—FX10.08 `1a4bab99fd9a7c563ffb8d8636055e383ab1fa42` and FX10.31 `ba51e8fcd6cb460602651acefeafe47d5b9a5fc5`; FX3.02a/3.04b—FX10.09 `deeef53bc585b46dc8afdc3d8d5606b2f2e5daba`; FX5.08a/FX9.07b—FX10.10 `eeb011f0d3d33b7f55e4fc68f1d3cb72329ddafd`; FX1.04b—FX10.11 `1d2883cd44d750189fdfcc768e33660df7cc84cd`; FX1.05a/FX5.01—FX10.12 `abb5f6fc1cf9acfeed2d3712b93e654fb4840c84`; FX5.05a/FX7.01—FX10.13 `46e46af30cc5fa9c91dc26a64f9f9358ffcbfe50`; FX4.01c—FX10.14 `5f8aa274348f612055434fcae1144916ca6bed42`; FX2.01b—FX10.15 `370b43516d893d17d3a1c4d6d63d33c272c1fd5c`; FX8.04a/b and FX9.14a/b—FX10.16 `10e5016464cf54c804e6763382a798345709060e`; FX2.04a/FX8.06c/FX9.05b—FX10.18 `c9b82e28d906fd41cc281b0de7f51e110db46c3e`; FX9.02c—FX10.22 `e39e3d16b27dc3f2cf017176f86feb87990a145f`; FX6.03/FX8.15c—FX10.25 `df5b10ed74b88e3046e79c307d0d49ab11c8a882` and FX10.27 `f0a7ab6945d02e3102ac51d1093b9a55a58d4636`; original F.06 voice-marker subtask—FX10.28 `5a3f7ca095905e1c23c087694a37be4093b1601d`; R110 test gaps—FX10.30 `a815144543e59fc77de5779eeb10dfe44de1c172`; FX9.05a's Tesseract-gated test was present and verified running by FX10.01 CI `d9adb61f3a0b74ba81a98590f10e8a9535bf1427`; FX8.18/FX5.10/FX7.02a,c/FX7.03/FX9.19b—FX10.32 `b5b467940e27d5938933e4d3a3ef58e3cadeeff5`. Original P0.03c and its parent were rechecked against FX10.30. The previous-review FX9.19a closure was rechecked here. | Checklist/status-only change; `git diff --check` passed. P4.01b/FX5.06a and Piper speaker-count work remain open because their provider-selection/deferred acceptance isn't covered by a completed FX10 task; P5.05 and F.01 remain open/deferred. | FX10.33b final gate |
