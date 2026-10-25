# PDF2Audiobook — Fourth Review Fixes TODO

**Status:** FX10.00–FX10.05 complete; FX10.06 is next.
**Date:** 2026-10-25
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

- [ ] FX10.06 Take the workspace lock before analysis and in review saves (R85).
  - [ ] FX10.06a Regression tests:
    - with the lock held, `convert --no-resume` is refused and leaves `manifest.json` and `chapters/*.txt` byte-identical;
    - `analyze` is refused;
    - a review-UI POST gets 409 and the manifest is unchanged.
  - [ ] FX10.06b Lock in `convert`, `analyze` and `batch` (per book) before any analysis. Use a non-blocking lock in review saves.
- [ ] FX10.07 Share chapter selection between convert and dry-run (R83).
  - [ ] FX10.07a Regression tests:
    - a hand-emptied chapter exits 6 in dry-run;
    - an approved empty chapter is listed as skipped;
    - dry-run logs `review_acknowledged` and writes nothing.
  - [ ] FX10.07b Extract one function that applies acknowledgements, recomputes reasons and decides converted, skipped and refused chapters. Use it in convert and dry-run.
- [ ] FX10.08 Make `pack-m4b` package every chapter convert produces, leaving out the ones it skips (R84, first step). No format change; the recorded rendering inputs and the sidecar bump come in FX10.31.
  - [ ] FX10.08a Regression test: a book with an approved empty chapter packages with that chapter left out, and the output names it. Test the selection without FFmpeg; the happy path is FFmpeg-gated.
  - [ ] FX10.08b Use the FX10.07 selection function in `pack-m4b`, and report skipped chapters by number.
  - [ ] FX10.08c Merge the spec §11 §8 amendment (`pack-m4b` omits skipped chapters).
- [ ] FX10.09 Small pipeline fixes (R82, R86, R87).
  - [ ] FX10.09a Regression tests:
    - after approval, a `min_boundary_confidence` change is accepted;
    - an LLM-model change with the LLM disabled is accepted;
    - `convert --no-resume` on an approved workspace with unchanged settings succeeds in dry-run;
    - a dangling `audio/x.mp3` symlink survives a successful convert;
    - a rejected page-number removal survives reanalysis.
  - [ ] FX10.09b Remove gate-only and disabled-LLM settings from the analysis fingerprint. Keep approved analysis on `--no-resume` with unchanged stages.
  - [ ] FX10.09c Skip and warn on MP3 cleanup candidates that can't be inspected.
  - [ ] FX10.09d Preserve deterministic edits whose `accepted` differs from the generated default.
  - [ ] FX10.09e Merge the spec §11 §5 resume amendment.

### CLI, configuration and logging

- [ ] FX10.10 Keep stderr to one JSON value in `--json` mode and "Error:" in human mode (R90).
  - [ ] FX10.10a Regression tests:
    - `--quiet --json` failure gives one JSON value on stderr;
    - `--quiet` human failure starts with "Error:";
    - a config warning plus a failure in `--json` mode gives one JSON value containing the warning code;
    - in human mode the same gives `Warning:` and `Error:` lines and no `{`.
  - [ ] FX10.10b Buffer events until the output mode is known. Put warnings in the JSON object's `warnings` array; render human `Warning:` lines. `--quiet` never adds output.
  - [ ] FX10.10c Amend R72's decision text in the previous review spec. Merge the spec §11 §7 amendment and the §8 `warnings`-array contract. Document the `warnings` array in README.md.
- [ ] FX10.11 Use one exit code for workspace failures (R91).
  - [ ] FX10.11a Regression test: a parametrized CLI test over `analyze`, `convert`, `convert --dry-run`, `batch`, `review` and `pack-m4b` with an unusable `--output`, in text and JSON modes, asserting the code, the fixed message, and no path or errno text.
  - [ ] FX10.11b Raise one typed workspace error; record its code per book in `batch`.
- [ ] FX10.12 Configuration robustness (R92).
  - [ ] FX10.12a Regression tests:
    - URLs with `#`, `?`, `/` and `@` in the password are fully redacted in `config show` and `--sources`;
    - a nested non-table section, with and without an env override, exits 2;
    - a non-vacuous secret-field redaction test.
  - [ ] FX10.12b Redact the whole userinfo before parsing (redact everything if unparseable). Reject non-table values at any depth. Mark real secret fields, or register a test-only one.
- [ ] FX10.13 Paired `--resume` and group help examples (R93, R94).
  - [ ] FX10.13a Tests:
    - `--resume` and `--no-resume` override TOML on `analyze` and `batch`;
    - `budget --help` and `config --help` contain "Example".
  - [ ] FX10.13b Add the options and the examples. Audit every pipeline-read boolean for a missing pair. Merge the spec §11 §8 amendment.
- [ ] FX10.14 `budget` CLI edge cases (R95).
  - [ ] FX10.14a Regression tests:
    - `budget show` on a v2 ledger works;
    - `resolve` of a missing ID and of a complete row each give their own message and exit 2.
  - [ ] FX10.14b Read legacy ledgers read-only in `show`. Decide and implement legacy handling in `resolve`, and record the decision in the spec.

### Extraction and structure

- [ ] FX10.15 **Refactor** extraction (R99).
  - [ ] FX10.15a Remove `nearer_edge_than_body`, and `chapter_text` if only tests use it. Make `_valid_box` public or move it.
  - [ ] FX10.15b Build the Roman-numeral tables once. Move the OCR fallback out of `extract_pdf`. Make `_classify_block_kind` the only kind decision.
  - [ ] FX10.15c Compute each page's drawings and image info once, with the shared item cap.
- [ ] FX10.16 One list classifier that respects footnotes and initials (R96).
  - [ ] FX10.16a Regression tests:
    - numbered small-type footnotes stay `footnote`, and `--footnotes omit` removes them;
    - "A. Smith …" / "B. Jones …" stays one paragraph;
    - the "May / 12." and "page / 42)" wraps join;
    - a list followed by a same-margin body line keeps the paragraph separate.
  - [ ] FX10.16b Classify footnotes before lists. Use one list classifier for block kinds and the join check. Apply the spec's list-end rule.
- [ ] FX10.17 Decide page-number ambiguity among candidates only (R97).
  - [ ] FX10.17a Regression tests:
    - two table-cell numerals at the foot give no warning and no review reason;
    - the sonnet fixture gives no label-mismatch warning;
    - 18pt vs 18.4pt is a tie and warns.
  - [ ] FX10.17b Count only candidates. Compare only the chosen sequence with the labels. Add a named tie tolerance (2pt) documented in MAINTAINER_GUIDE.md.
- [ ] FX10.18 Keep short valid text out of OCR (R98).
  - [ ] FX10.18a Regression tests:
    - a "Part One" page with a 48-path ornament analyzes with Tesseract unavailable and has `embedded` origin;
    - `--ocr never` on an outlined page doesn't say "attempting OCR";
    - the single-rule page's warning wording.
  - [ ] FX10.18b Apply the glyph-like-drawings rule only when there is no usable text. Name the actual outcome in each warning.
  - [ ] FX10.18c Merge the spec §11 §4.1–§4.2 amendments.

### LLM budget and providers

- [ ] FX10.19 **Refactor** the LLM request loop (R104).
  - [ ] FX10.19a Split `_complete_json_request` into named settle paths with a `Literal` outcome type.
  - [ ] FX10.19b Write the usage-validation predicate once. Build the capability-file path once and write it only on change. Remove or align the no-ledger budget path.
- [ ] FX10.20 Settle JSON-mode rejections as `rejected` and remember them (R100).
  - [ ] FX10.20a Regression test: three requests against a stub rejecting `response_format` give one `rejected` row and three `complete` rows, and the capability persists across provider instances.
  - [ ] FX10.20b Settle the rejection `rejected`; store the fallback in the capability store.
- [ ] FX10.21 Reject cumulative overflow at settlement (R101).
  - [ ] FX10.21a Regression test: two 2^62-token responses leave `budget show` working, with the second row `unknown` and resolvable.
  - [ ] FX10.21b Check cumulative totals inside the settlement transaction; settle with validated usage only.
- [ ] FX10.22 Make `reserve` fail closed without a bound under any budget (R102).
  - [ ] FX10.22a Regression test: an unbounded `reserve` under a token budget is refused.
  - [ ] FX10.22b Refuse unbounded reservations under a token or USD budget. Amend the R70 decision text.
  - [ ] FX10.22c Add truthfully named tests for the conditions the mis-named `…_blocks_…`, overspend and exact-exhaustion tests describe. Rename the existing tests to what they assert, with a reason in the commit message.
- [ ] FX10.23 Parameter detection and model resolution (R103).
  - [ ] FX10.23a Test: a context-length 400 mentioning `max_tokens`. If it shows the misfire, require an explicit unsupported-parameter phrase and never persist a capability from a context-length error. Otherwise record "not reproducible" in the ledger.
  - [ ] FX10.23b Make `_model()` use the pipeline resolver. Test `auto` with two served models through the real `resolve_model`.
- [ ] FX10.24 Merge the spec §11 §6.3 amendment, and fix parent spec §6.3 line 191.

### Audio and TTS

- [ ] FX10.25 Turn every unspeakable paragraph into a pause (R105).
  - [ ] FX10.25a Regression tests: `# # #`, `~~~`, `• • •`, `———` and `⁂` each make one pause entry and no TTS call, and coverage passes.
  - [ ] FX10.25b Detect pauses from the spoken form (no letters or digits). Count them in `pause_count`.
- [ ] FX10.26 Narration rules, remaining cases (R106).
  - [ ] FX10.26a Regression tests:
    - `said—Hermione` applies the `hermione` key;
    - `O’Brien said.` applies an `o’brien` key;
    - `Dr.?` reads "Doctor?";
    - `1–<U+200B>2` reads "1 to 2";
    - `"—"` and `(—)` become pauses;
    - a punctuation-only key is rejected at load.
  - [ ] FX10.26b Implement each rule. Extend the alignment property test to include pronunciations and chunk sizes from 20 to the default.
- [ ] FX10.27 Bound progress bookkeeping (R107).
  - [ ] FX10.27a Regression tests:
    - a 500k-character chapter with a no-op TTS keeps the correct `pause_count` within a time budget;
    - an oversized status file makes `inspect` print the fixed "too large" message.
  - [ ] FX10.27b Make progress writes linear (append-only records). Warn and mark fields unavailable when a bounded read hits its cap.
- [ ] FX10.28 Make voice-listing failures errors (R108).
  - [ ] FX10.28a Regression test: a Kitten stub whose voice listing raises fails the marker chapter with `voice_list_unavailable`, exit 7.
  - [ ] FX10.28b Raise `TTSError` from `list_voices`; skip validation only for providers that declare no voice list.
- [ ] FX10.29 Small audio fixes and code health (R109).
  - [ ] FX10.29a Tests:
    - the cover is read once per run;
    - after a size-limit error the progress status is `failed` and the chunk isn't `completed`.
  - [ ] FX10.29b Read and hash the cover once. Track WAV bytes without the private `wave` attribute. Rename the two narration constants. Remove the dead check. Extract provider construction and voice/speed selection.

### Tests, fingerprints, documentation and closure

- [ ] FX10.30 Close the test gaps behind checked items (R110). Add each test in the spec §8 table, citing the item it backs in the commit message.
  - [ ] FX10.30a Manifest, review and CLI gaps: FX0.03c, FX1.02b/FX8.16b, FX3.01b, FX8.06d, FX8.15a, FX8.15b, FX9.07c, FX5.09.
  - [ ] FX10.30b Budget gaps: FX4.01d, FX8.08c, FX8.09a, FX8.09b.
  - [ ] FX10.30c Extraction gaps: FX8.02c/FX9.16a (folio near body text, failing at 2904f19), FX9.03 (replace "D. H. LAWRENCE"; whitespace one-letter numeral).
  - [ ] FX10.30d Audio gaps: FX8.14a (batch validation), FX8.14e (`OSError` injection, chapter size limit), FX9.17 (version constant reaches the fingerprint).
- [ ] FX10.31 Bump the fingerprints once (spec §10).
  - [ ] FX10.31a Bump the extraction/analysis fingerprint to `analysis-v22` for R82, R96, R97 and R98.
  - [ ] FX10.31b In one commit, make the R84 second step together with the chapter audio fingerprint bump for R105 and R106, so users regenerate audio only once:
    - record the rendering inputs (at least the footnote policy) in each MP3 sidecar and set `sidecar_version = 3`;
    - render with the recorded inputs in `pack-m4b`.

    Regression tests:
    - convert with `pdf.footnotes = "omit"`, then `pack-m4b --no-config`, verifies freshness;
    - a v2 sidecar is stale.
  - [ ] FX10.31c Add the MAINTAINER_GUIDE upgrade notes, keeping the earlier notes as history. Merge the spec §11 §9 amendment (sidecars record rendering inputs).
- [ ] FX10.32 Update the docs (R112).
  - [ ] FX10.32a README.md: rewrite the budget section; document the paired `--no-*` forms and the `budget resolve` syntax.
  - [ ] FX10.32b Parent spec: R31/R90 logging in §7, R75/R81 matching in §5; confirm every spec §11 amendment is merged.
  - [ ] FX10.32c MAINTAINER_GUIDE.md: remove the stale v20 sentence; restore the v19 and mp3-v5 notes as history; document identity matching, the lock scope, the tie tolerance and the CI skip-summary check.
  - [ ] FX10.32d Previous review spec: amend R79 for the FX9.16d page-number decision and the FX9.02c decision (superseded by R102).
- [ ] FX10.33 Closure.
  - [ ] FX10.33a Re-check each item unchecked in FX10.00 only when the FX10 task that covers it (spec §13) is checked, citing that task's commit SHA. Re-check original-TODO items the same way.
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
