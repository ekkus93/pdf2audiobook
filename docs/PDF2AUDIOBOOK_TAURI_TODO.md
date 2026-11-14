# PDF2Audiobook — Desktop App (Tauri) TODO

**Status:** Not started; owner decisions O1–O5 settled 2026-11-14 (spec §14)
**Date:** 2026-11-14
**Branch:** `tauri`, from master at 05ca4c37685325ced177cf06d21de2506fe18cd2 (tag `v0.1.0`)
**Specification:** `docs/PDF2AUDIOBOOK_TAURI_SPEC.md` (D1–D11)

## Working rules

- Work in phase order. Use `[x]` only when the item is implemented and its tests or evidence
  are recorded in an `Evidence:` line. Check a parent only when all its subitems are checked.
  An item marked **[OWNER DECISION]** waits for the owner; items that depend on it say so.
- The Python CLI stays the engine (spec §2). CLI changes (phase TD1) are additive, come with a
  contract test, and leave every existing output, flag and exit code unchanged.
- Privacy: no book text, titles, file names or private paths in the app's logs, errors or
  dialogs; every new error path gets a privacy test, as in the CLI.
- Commits: Conventional Commits, lowercase imperative subject, no body, no `Co-Authored-By`
  trailer. Scopes: `cli` for TD1, `desktop` for the app, `ci` for workflows, `docs` for
  documentation. One logical change per commit.
- Checks before each commit: `/verify` and mypy on 3.12 and 3.13 for Python changes; for
  `desktop/` changes, `cargo fmt --check`, `cargo clippy -- -D warnings`, `cargo test` and the
  frontend lint, type-check and tests.
- Push after each commit to `origin/tauri`. Once CI runs for the branch (TD0.03), record each
  pushed commit's CI result in a separate `docs:` commit, with the full SHA and real run ID, in
  this file's ledger and in `docs/PDF2AUDIOBOOK_TODO.md`. The ledgers are append-only.

## Phase TD0 — Baseline and decisions

- [ ] TD0.01 Record the baseline on the branch: `/verify` result, `cargo --version`,
  `node --version`, and whether the Tauri Linux system libraries (WebKitGTK 4.1 and friends)
  are installed.
- [x] TD0.02 **[OWNER DECISION]** Settle O1–O5 (spec §14) and record each answer here. Until
  then, work proceeds on the recommended defaults: installed CLI, Linux first, React, unsigned
  builds, branch added to CI.
  - Evidence: The owner decided on 2026-11-14 (recorded in spec §14): O1 require an installed
    CLI; O2 Linux only for now, macOS and Windows later; O3 React and TypeScript with Google's
    Material 3, polished and modern, with a chosen palette (spec D11: Midnight Iris with Amber);
    O4 unsigned builds; O5 add the `tauri` branch to the `ci.yml` push triggers.
- [ ] TD0.03 Make CI run for the `tauri` branch (O5): add it to the `push` branches in
  `.github/workflows/ci.yml`, or open a draft pull request. Depends on TD0.02 for the choice.

## Phase TD1 — CLI contract additions (D2)

- [ ] TD1.01 D2.f: `pdf2audiobook --version` with no command prints the version and exits 0.
  Test: run with no command; also with a command after it (unchanged).
- [ ] TD1.02 D2.a: `pdf2audiobook workspace BOOK [--output DIR] --json` prints
  `{"workspace", "exists"}` using the analysis rule. Tests: matches the folder `analyze`
  creates; `exists` false before and true after; missing book gives exit 3 and the existing
  message; nothing is written.
- [ ] TD1.03 D2.b: add `reason` to JSON errors for each row of the spec table. Tests: one per
  reason that triggers the real failure and checks `reason` with `type`, `code` and `message`
  unchanged; an error with no reason has no `reason` key.
- [ ] TD1.04 D2.c: `review --json` prints `{"url", "port"}` once listening, then flushes;
  `--port 0` works. Test: start with `--json --port 0`, read the line, fetch the URL, stop the
  server; human mode output unchanged.
- [ ] TD1.05 D2.d: SIGTERM stops a run like Ctrl+C: `run_status.json` says `stopped`, the lock
  is released, exit 130 with the `Interrupted` JSON error. Test with a slow fake TTS provider
  on POSIX. Windows `CTRL_BREAK_EVENT` handling waits for Windows support (O2).
- [ ] TD1.06 D2.e: `pdf2audiobook voices --json` lists the provider's voices. Tests: fake Kitten
  and Piper providers; the Kitten list matches `KittenProvider.list_voices`; an unavailable
  provider gives the existing install message.
- [ ] TD1.07 D2.g: `pdf2audiobook thumbnail BOOK --output FILE.png [--width N] --json` renders
  the first page (PDF) or cover (EPUB) and prints `{"thumbnail", "width", "height"}`. Tests:
  PDF and EPUB fixtures, the requested width, an unreadable book gives the existing exit 3
  message, and nothing else is written.
- [ ] TD1.08 Document TD1.01–TD1.07 in the README command reference and exit-code notes, and
  in `docs/MAINTAINER_GUIDE.md` where it describes the JSON outputs.

## Phase TD2 — Project scaffold (D1)

- [ ] TD2.01 Create `desktop/` with Tauri 2, Vite and TypeScript (framework per O3), pinned
  toolchains (`rust-toolchain.toml`, `.nvmrc` with Node 22, committed `Cargo.lock` and
  `package-lock.json`). `npm run tauri dev` opens an empty window on Linux.
- [ ] TD2.02 Exclude `desktop/` from the Python wheel and sdist, and from Ruff and mypy. Test:
  build the wheel and sdist and check that no `desktop/` file is inside.
- [ ] TD2.03 D1.d: a test that fails when the versions in `pyproject.toml`, `Cargo.toml`,
  `package.json` and `tauri.conf.json` differ.
- [ ] TD2.04 D1.e: `desktop/README.md` with setup, development run, every check, and building
  an installer; link it from the main README.

## Phase TD3 — Engine bridge (D3)

- [ ] TD3.01 D3.a: locate the CLI (settings path, `PATH`, `uv run --project`), confirm it with
  `--version` and `doctor --json`, and refuse a version whose major or minor differs. Tests with
  a fake CLI for each source and for a version mismatch.
- [ ] TD3.02 D3.b: typed requests to argument vectors for every supported command and option;
  `--json` and `--no-progress` always added; no shell. Tests: one per request variant, and a
  test that a book path with spaces, quotes and leading dashes stays a single argument.
- [ ] TD3.03 D3.c: parse success JSON, the error object with optional `reason`, and unreadable
  output (fixed message with the exit code only). Tests for each.
- [ ] TD3.04 D3.d: at most one write-capable command per workspace in the bridge. Tests: a
  second start is refused while the first runs; read-only commands are not blocked.
- [ ] TD3.05 D3.e: environment passed through; encrypted PDFs take an environment variable
  name, never a password. Test that no password value is ever placed in arguments.

## Phase TD4 — Shared contracts (D9.c)

- [ ] TD4.01 Write JSON Schemas in `desktop/contracts/` for every output in spec D9.c.
- [ ] TD4.02 Python tests validate real CLI output against those schemas (the `jsonschema`
  package added to the `dev` extra, with the lockfile updated).
- [ ] TD4.03 Rust tests validate the parser's fixtures against the same schemas.

## Phase TD5 — Screens (D4)

Each screen has component tests for its loading, empty, success and error states, works with
the keyboard, and shows the command it runs under "Details". Each screen's item also records
dark and light screenshots (spec D11.h).

- [ ] TD5.00 Design foundation (D11): generate the Material 3 scheme from the seeds `#6D5BD0`
  and `#E8A25C` with `@material/material-color-utilities` at build time into `--md-sys-color-*`
  CSS variables for dark and light; bundle Roboto Flex, Roboto Mono and Material Symbols
  Rounded; pin `@material/web` and wrap each component used in a small React component; build
  the navigation rail, top app bar, card, snackbar and player bar from the same tokens.
  Tests: the generated roles match the spec D11.b table; every text and icon pairing passes
  WCAG AA (D11.c); no font or icon is fetched at run time.
- [ ] TD5.01 Setup: `doctor --json` results, Ollama served-context check, install hints.
- [ ] TD5.02 Library: books in the output folder with state and last run; "Add book" dialog.
- [ ] TD5.02a **[OWNER REVIEW]** The owner reviews the Setup and Library screens in dark and
  light (D11.h) before TD5.03–TD5.08 are built.
- [ ] TD5.03 Book options: LLM, model, context and output caps, voice (from `voices --json`),
  speed, chapter range, cover, and remote-content consent.
- [ ] TD5.04 Run: progress view (TD6) with cancel.
- [ ] TD5.05 Review: opens on `review_required` and `review_acknowledgement_required` (TD7).
- [ ] TD5.06 Pending edits: list, accept or reject each, and "accept all" behind a
  confirmation that shows the count.
- [ ] TD5.07 Chapters and audio: per-chapter state, player, open folder, M4B, export (TD8).
- [ ] TD5.08 Settings: CLI location, output folder, default voice with the README samples, LLM
  settings; effective CLI configuration shown read-only.
- [ ] TD5.09 Each D2.b `reason` leads to the action in the spec table. Tests for every reason.

## Phase TD6 — Progress and long runs (D5)

- [ ] TD6.01 D5.a: poll `run_status.json` from the workspace given by TD1.02 and show stage,
  counts, elapsed and estimate. Test with a fake CLI that writes the file in steps.
- [ ] TD6.02 D5.b: a run ends when the child exits; a stale `running` state is shown as stopped.
- [ ] TD6.03 D5.c: cancel sends the termination signal, waits up to 30 seconds, then kills, and
  offers `recover` after a `pending_recovery` error. Tests with a fake CLI that ignores the
  signal and one that exits cleanly.
- [ ] TD6.04 D5.d: closing the window during a run asks, then cancels; no child process
  outlives the app. Test that checks for orphaned processes after a forced close.

## Phase TD7 — Chapter review (D6)

- [ ] TD7.01 D6.a: start `review --json --port 0`, open the URL in a review window that may
  load only that origin.
- [ ] TD7.02 D6.b: closing the window stops the server and refreshes the book's state.
- [ ] TD7.03 D6.c: explain that merging and splitting need a manifest edit, with a link to the
  README section; no manifest writes by the app.

## Phase TD8 — Listening and output (D7)

- [ ] TD8.01 D7.a: play chapter MP3s through the asset protocol scoped to the book's `audio/`
  folder. Test that a path outside it is refused.
- [ ] TD8.02 D7.b: "Make M4B" runs `pack-m4b --json` to a user-chosen path, with the cover if
  set; a stale chapter shows the CLI's message and offers to continue converting.
- [ ] TD8.03 D7.c: "Export zip" with chapter MP3s and, optionally, the source book, written to a
  user-chosen path outside the workspace. Test the zip's contents.

## Phase TD9 — Security and privacy (D8)

- [ ] TD9.01 D8.a: capabilities limited to dialog, the bridge's commands and the scoped asset
  protocol. Test (or a checked-in review script) that fails if another permission is added.
- [ ] TD9.02 D8.b: CSP for the main window with no remote origins and no `unsafe-eval`; the
  review window limited to its loopback URL.
- [ ] TD9.03 D8.c: privacy test with marker strings in the title, file name and text; none
  appears in the app log or any error dialog.
- [ ] TD9.04 D8.d: the app itself makes no network requests. Test with networking blocked for
  the app process (the fake CLI needs none).

## Phase TD10 — End to end, CI and packaging (D9.d, D10)

- [ ] TD10.01 D9.d: `tauri-driver` WebDriver test on Linux: add the demo book, analyze with
  `--no-llm`, review (retitle chapter 1 and save), convert with `--dry-run`.
- [ ] TD10.02 D10.c: CI job for `desktop/` (fmt, clippy, tests, frontend checks, Linux
  `tauri build`, the end-to-end test). Depends on TD0.03.
- [ ] TD10.03 D10.b: Linux AppImage and `.deb` from CI as build artifacts. macOS and Windows
  wait for O2.
- [ ] TD10.04 **[OWNER DECISION]** D10.d signing and notarization (O4). Unsigned builds are
  labelled as unsigned until then.
  - Note: The owner chose unsigned builds for now (spec §14, O4). The item stays open until the
    build labels unsigned installers, which is part of TD10.03.
- [ ] TD10.05 Manual acceptance on this machine: install the AppImage, convert the README demo
  book with real Kitten speech, and record the result. Real LLM use with Ollama is recorded
  separately and stays optional.

## Found while writing the spec

- `pdf2audiobook --version` exits 2 with "Missing command" unless a command follows it
  (master at 05ca4c37685325ced177cf06d21de2506fe18cd2). Tracked as TD1.01.

## Progress ledger

| Date | Branch SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
