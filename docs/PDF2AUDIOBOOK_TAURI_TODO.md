# PDF2Audiobook — Desktop App (Tauri) TODO

**Status:** All items checked for Linux, 2026-11-14 (last code commit 9b03d4eefe28463bc3dffe6a5d5b4c9245cad451,
Python CI #849 and Desktop CI #4 passed). Exceptions: TD10.05's acceptance run was driven by
the end-to-end walkthrough rather than by hand and nobody listened to the audio; signing (O4)
and macOS/Windows installers (O2) wait for the owner; real LLM use with Ollama was not run
(optional). Owner decisions O1–O5 settled 2026-11-14 (spec §14).
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

- [x] TD0.01 Record the baseline on the branch: `/verify` result, `cargo --version`,
  `node --version`, and whether the Tauri Linux system libraries (WebKitGTK 4.1 and friends)
  are installed.
  - Evidence: On `tauri` at 5ff9749 (2026-11-14), Ubuntu 22.04.4: `uv lock --check` and
    `uv sync --locked --extra kitten --extra dev` clean; Ruff check and format check clean
    (392 files); mypy clean on 3.11, 3.12 and 3.13 (52 source files); pytest 2412 passed,
    1 skipped (the opt-in real-Kitten smoke); CLI smoke (`--help`, `config show --json`,
    `doctor --json`) passed. Toolchain: cargo 1.96.0, rustc 1.96.0, Node v24.13.0, npm 11.6.2.
    Tauri system libraries were missing (only GTK 3 and librsvg present, no `pkg-config`);
    installed from the Ubuntu archive with `apt-get install pkg-config libwebkit2gtk-4.1-dev
    libsoup-3.0-dev libayatana-appindicator3-dev librsvg2-dev libssl-dev libgtk-3-dev
    build-essential file patchelf libxdo-dev`, giving webkit2gtk-4.1 2.50.4, libsoup-3.0
    3.0.7, gtk+-3.0 3.24.33, ayatana-appindicator3 0.5.90, librsvg 2.52.5, OpenSSL 3.0.2.
- [x] TD0.02 **[OWNER DECISION]** Settle O1–O5 (spec §14) and record each answer here. Until
  then, work proceeds on the recommended defaults: installed CLI, Linux first, React, unsigned
  builds, branch added to CI.
  - Evidence: The owner decided on 2026-11-14 (recorded in spec §14): O1 require an installed
    CLI; O2 Linux only for now, macOS and Windows later; O3 React and TypeScript with Google's
    Material 3, polished and modern, with a chosen palette (spec D11: Midnight Iris with Amber);
    O4 unsigned builds; O5 add the `tauri` branch to the `ci.yml` push triggers.
- [x] TD0.03 Make CI run for the `tauri` branch (O5): add it to the `push` branches in
  `.github/workflows/ci.yml`, or open a draft pull request. Depends on TD0.02 for the choice.
  - Evidence: `ci.yml` push branches are now `[master, tauri]`; the `ci.yml` cross-check tests
    (`tests/test_ci_uv_pin.py` and others reading `ci.yml`) pass. Commit
    fc65d442887297608f60d97cd0ba4f7457e2ced0 started the first branch run, Python CI
    [43605414647](https://github.com/ekkus93/pdf2audiobook/actions/runs/43605414647), which
    passed.

## Phase TD1 — CLI contract additions (D2)

- [x] TD1.01 D2.f: `pdf2audiobook --version` with no command prints the version and exits 0.
  Test: run with no command; also with a command after it (unchanged).
  - Evidence: `--version` is now an eager option with its own callback
    (`src/pdf2audiobook/cli.py`, `_show_version`). `tests/test_cli_version.py`:
    `test_version_alone_prints_the_version_and_exits_zero` failed before the fix (exit 2,
    "Missing command") and passes after; `test_version_before_a_command_still_prints_only_the_version`
    and `test_no_arguments_still_shows_help` pass. Full checks: Ruff and format clean, mypy clean
    on 3.11/3.12/3.13, pytest 2415 passed, 1 skipped, CLI smoke passed. Commit
    c95255dd76663c3f3dff077157dc88312b3e1206, Python CI
    [43605569128](https://github.com/ekkus93/pdf2audiobook/actions/runs/43605569128) passed.
- [x] TD1.02 D2.a: `pdf2audiobook workspace BOOK [--output DIR] --json` prints
  `{"workspace", "exists"}` using the analysis rule. Tests: matches the folder `analyze`
  creates; `exists` false before and true after; missing book gives exit 3 and the existing
  message; nothing is written.
  - Evidence: `pdf2audiobook workspace` (`src/pdf2audiobook/cli.py`) uses the new public
    `pipeline.analysis_workspace_folder`, which wraps the analysis rule. Output is
    `{"workspace", "exists", "warnings"}`: every `--json` result carries `warnings`.
    `tests/test_cli_workspace.py`: `test_workspace_matches_the_folder_analyze_creates` (same folder
    as `analyze`; `exists` false before and true after; the tree is unchanged by the command),
    `test_workspace_uses_the_configured_output_folder`, and
    `test_missing_book_gives_exit_3_and_the_existing_message` (exit 3, the existing message, no
    path or name, nothing written). Full checks: Ruff and format clean, mypy clean on 3.11/3.12/3.13 (run as `uv run --isolated --extra dev mypy`, see "Found while"), pytest 2418 passed, 1 skipped. Commit
    8fa1af7b3f1c93c955b7358efc84bad04f3287eb, Python CI [43605747057](https://github.com/ekkus93/pdf2audiobook/actions/runs/43605747057) passed.
- [x] TD1.03 D2.b: add `reason` to JSON errors for each row of the spec table. Tests: one per
  reason that triggers the real failure and checks `reason` with `type`, `code` and `message`
  unchanged; an error with no reason has no `reason` key.
  - Evidence: `AudiobookError.error_reason` (`src/pdf2audiobook/errors.py`), set on
    `WorkspaceLockedError`, `PendingRecoveryError` and `ChapterConflictError` and per raise for
    the review gates (`chapter_selection.py`), LLM failures (`llm/provider.py`) and exhausted
    budgets (`llm/budget.py`, `llm/cache.py`); `cli.fail` adds `reason` only when set. The
    existing `LLMError.reason` log tag is unchanged. `tests/test_cli_error_reasons.py` (16 tests):
    end to end through `--json` for low confidence and an unapproved empty chapter
    (`review_required`), `damaged_source` and `ambiguous_page_numbers`
    (`review_acknowledgement_required`), a held lock (`workspace_locked`), a blocked pending
    update (`pending_recovery`); at the real source and through `cli.fail` for a conflicting
    edited chapter (`chapter_conflict`), refused connections to llama-server and Ollama
    (`llm_unreachable`), the configured and the served context (`llm_context_too_small`), both
    output-cap failures (`llm_output_cap`) and a used-up request budget (`budget_exhausted`).
    Each checks `type`, `code` and `message` too. `test_timeout_is_not_reported_as_unreachable`
    and `test_error_without_a_reason_has_no_reason_key` check the absent key. Against the
    unchanged source, 14 of 16 fail (the two that pass expect no reason). Full checks: Ruff and format clean, mypy clean on 3.11/3.12/3.13 (run as `uv run --isolated --extra dev mypy`, see "Found while"), pytest 2434 passed,
    1 skipped. Commit 246571bcff17276f357332ed11d165c67a63ef71, Python CI
    [43606260786](https://github.com/ekkus93/pdf2audiobook/actions/runs/43606260786) passed.
- [x] TD1.04 D2.c: `review --json` prints `{"url", "port"}` once listening, then flushes;
  `--port 0` works. Test: start with `--json --port 0`, read the line, fetch the URL, stop the
  server; human mode output unchanged.
  - Evidence: with `--json`, `review` prints one flushed line `{"url", "port"}` and no human
    lines. `tests/test_cli_review_json.py`:
    `test_real_server_on_port_zero_reports_a_reachable_address` (a real `review --json --port 0`
    process: reads the line, fetches the URL and gets the review page, stops it with SIGINT,
    exit 0, nothing else on stdout), `test_json_mode_prints_only_the_address_line`, and
    `test_human_mode_output_is_unchanged` (the three existing stderr lines, empty stdout). The
    two JSON tests failed before the change. Full checks: Ruff and format clean, mypy clean on 3.11/3.12/3.13 (run as `uv run --isolated --extra dev mypy`, see "Found while"), pytest 2437 passed, 1 skipped. Commit
    bbef731af2263514b2f15e4665eeb9550b804ca2, Python CI [43606481323](https://github.com/ekkus93/pdf2audiobook/actions/runs/43606481323) passed.
- [x] TD1.05 D2.d: SIGTERM stops a run like Ctrl+C: `run_status.json` says `stopped`, the lock
  is released, exit 130 with the `Interrupted` JSON error. Test with a slow fake TTS provider
  on POSIX. Windows `CTRL_BREAK_EVENT` handling waits for Windows support (O2).
  - Evidence: the console script is now `pdf2audiobook.cli:main`, which installs a SIGTERM
    handler that raises `KeyboardInterrupt`, then runs `app`; Ctrl+C's existing path does the
    rest. `tests/test_cli_sigterm.py::test_sigterm_during_synthesis_stops_like_ctrl_c` runs a
    real `convert` whose Kitten is replaced by a voice that blocks in synthesis, sends SIGTERM,
    and checks: exit 130 within 30 s, empty stdout, the `Interrupted` JSON error,
    `run_status.json` `state` is `stopped`, and `workspace_lock` can be taken at once. It failed
    before the change. `docs/MAINTAINER_GUIDE.md` names the new entry point. Full checks: Ruff and format clean, mypy clean on 3.11/3.12/3.13 (run as `uv run --isolated --extra dev mypy`, see "Found while"), pytest 2438 passed,
    1 skipped; CLI smoke passed. Windows `CTRL_BREAK_EVENT` is not handled yet, as the item
    allows (O2: Linux only). Commit 084afcce6f28f7fe8e52f19d69f50376a84da1d9, Python CI
    [43606790093](https://github.com/ekkus93/pdf2audiobook/actions/runs/43606790093) passed.
- [x] TD1.06 D2.e: `pdf2audiobook voices --json` lists the provider's voices. Tests: fake Kitten
  and Piper providers; the Kitten list matches `KittenProvider.list_voices`; an unavailable
  provider gives the existing install message.
  - Evidence: `pdf2audiobook voices` prints `{"provider", "voices", "listable",
    "default_voice", "warnings"}`; `--tts-model` maps as in `convert`. Piper has no voice names
    (its speakers are numbers in the model), so it reports `"listable": false` and an empty list
    rather than an empty list that looks like "no voices". `tests/test_cli_voices.py`:
    `test_kitten_voices_match_the_provider_listing` (fake `kittenml`; equals
    `KittenProvider("mini").list_voices()`), `test_tts_model_selects_the_kitten_model`,
    `test_piper_reports_that_its_speakers_cannot_be_listed` (no model path in the output),
    `test_missing_kitten_gives_the_existing_install_message` and
    `test_missing_piper_model_gives_the_existing_message`. With the real Kitten installed it lists
    Bella, Jasper, Luna, Bruno, Rosie, Hugo, Kiki and Leo. Full checks: Ruff and format clean, mypy clean on 3.11/3.12/3.13 (run as `uv run --isolated --extra dev mypy`, see "Found while"), pytest 2443 passed, 1 skipped. Commit
    c87c24a350b3044f2b7aed7b09b27ef5da2a9d47, Python CI [43606973444](https://github.com/ekkus93/pdf2audiobook/actions/runs/43606973444) passed.
- [x] TD1.07 D2.g: `pdf2audiobook thumbnail BOOK --output FILE.png [--width N] --json` renders
  the first page (PDF) or cover (EPUB) and prints `{"thumbnail", "width", "height"}`. Tests:
  PDF and EPUB fixtures, the requested width, an unreadable book gives the existing exit 3
  message, and nothing else is written.
  - Evidence: `pdf.render_thumbnail` renders page 0 at the requested width (default 320,
    16–2048) and writes it with `atomic_write`; the output must be a `.png` in an existing folder
    (exit 2 otherwise, nothing created). An EPUB's first page holds its cover. `cli thumbnail`
    prints `{"thumbnail", "width", "height", "warnings"}`. `tests/test_cli_thumbnail.py` (7
    tests): PDF at width 200 (PNG size and aspect, only the PNG added), default width 320, EPUB
    cover (the fixture's blue cover pixel), unreadable book (exit 3, the existing "cannot open PDF"
    message, no name or path, nothing written), missing book, missing output folder and a non-PNG
    output. 6 of 7 fail without the change. Ruff and format clean, mypy clean on 3.11/3.12/3.13 (isolated, as CI), pytest 2450 passed,
    1 skipped. Commit a7b81516e196d1646cc8f9842921aa38a99911cf, Python CI
    [43607182172](https://github.com/ekkus93/pdf2audiobook/actions/runs/43607182172) passed.
- [x] TD1.08 Document TD1.01–TD1.07 in the README command reference and exit-code notes, and
  in `docs/MAINTAINER_GUIDE.md` where it describes the JSON outputs.
  - Evidence: README command reference lists `workspace`, `voices`, `thumbnail` and
    `--version` and explains `review --json`; the exit-code table notes SIGTERM and a paragraph
    lists every `reason`. `docs/MAINTAINER_GUIDE.md` has a new "Machine-readable outputs for other
    programs" section covering TD1.01–TD1.07, and its entry-point paragraph names `cli:main`
    (TD1.05). Commit 272559f8276a8e57301afc7e7f219c58652a0457, Python CI
    [43607226126](https://github.com/ekkus93/pdf2audiobook/actions/runs/43607226126) passed.

## Phase TD2 — Project scaffold (D1)

- [x] TD2.01 Create `desktop/` with Tauri 2, Vite and TypeScript (framework per O3), pinned
  toolchains (`rust-toolchain.toml`, `.nvmrc` with Node 22, committed `Cargo.lock` and
  `package-lock.json`). `npm run tauri dev` opens an empty window on Linux.
  - Evidence: scaffolded with `create-tauri-app` 4.7.5 (`react-ts`), Tauri 2.12; trimmed to an
    empty shell (no demo command, no opener plugin; capability `core:default` only), product
    "pdf2audiobook", window 1280×800 with a 960×600 minimum. Pinned: `rust-toolchain.toml`
    (1.96.0 with rustfmt and clippy), `.nvmrc` (22), committed `Cargo.lock` and
    `package-lock.json`. Added ESLint 9 (typescript-eslint strict, react-hooks), Vitest 5 with
    jsdom and Testing Library, and `lint`, `typecheck` and `test` scripts. Local checks: lint,
    typecheck, 1 Vitest test, `npm run build`, `cargo fmt --check`, `cargo clippy --all-targets
    -- -D warnings`, `cargo test` all pass. `npm run tauri dev` on a virtual display (Xvfb, with
    `xvfb` and `x11-utils` installed from the Ubuntu archive) opened one window titled
    "pdf2audiobook", 1280×800, blank as intended; screenshot checked. Commit
    8f8a7e473d309d25bd42adc591e6ec6dbab827e4, Python CI [43607616011](https://github.com/ekkus93/pdf2audiobook/actions/runs/43607616011) passed
    (desktop checks join CI in TD10.02).
- [x] TD2.02 Exclude `desktop/` from the Python wheel and sdist, and from Ruff and mypy. Test:
  build the wheel and sdist and check that no `desktop/` file is inside.
  - Evidence: `MANIFEST.in` has `prune desktop`, Ruff has `extend-exclude = ["desktop"]` and
    mypy checks only its explicit `src/` list. The CI packaging step now fails if the wheel or
    sdist contains `desktop/`; that check caught a hand-made sdist containing `desktop/`. A local
    `uv build` of both had no `desktop/` entry. `tests/test_desktop_packaging.py` (3 tests) pins
    the three settings and the CI check. Ruff and format clean, mypy clean on 3.11/3.12/3.13 (isolated, as CI), pytest 2453 passed, 1
    skipped. Commit 946ddd9ef0c4f60ae492cb0dcf89d4169f8e1f46, Python CI
    [43607833526](https://github.com/ekkus93/pdf2audiobook/actions/runs/43607833526) passed, including the new packaging check.
- [x] TD2.03 D1.d: a test that fails when the versions in `pyproject.toml`, `Cargo.toml`,
  `package.json` and `tauri.conf.json` differ.
  - Evidence: `tests/test_desktop_versions.py`: `test_every_version_matches_pyproject` reads
    `pyproject.toml`, `package.json`, `package-lock.json` (`packages[""]`), `Cargo.toml` and
    `tauri.conf.json` (all 0.1.0); `test_a_differing_version_is_detected` changes each desktop
    file's version in a copy and checks the difference is found. Ruff and format clean, mypy clean on 3.11/3.12/3.13 (isolated, as CI),
    pytest 2458 passed, 1 skipped. Commit 88f3c599666fd1eab88406d10b1479323c5aa8f5, Python CI
    [43608025888](https://github.com/ekkus93/pdf2audiobook/actions/runs/43608025888) passed.
- [x] TD2.04 D1.e: `desktop/README.md` with setup, development run, every check, and building
  an installer; link it from the main README.
  - Evidence: `desktop/README.md` covers requirements (Rust 1.96.0, Node 22, the Tauri system
    packages, the CLI via `uv tool install ".[kitten]"`), development (`npm ci`, `npm run tauri
    dev`), every check (lint, typecheck, Vitest, build, cargo fmt, clippy, test), building
    installers and the folder layout. Its commands were run: `npm ci` (261 packages, tests pass),
    `npm run tauri build -- --bundles deb` (1m 26s, `pdf2audiobook_0.1.0_amd64.deb`, 1.79 MiB) and
    `--bundles appimage` (76.69 MiB; the first build downloads linuxdeploy). The main README links
    it under "Desktop app". Commit 94de70ca8142e146938f779d0930de0f842e39df, Python CI
    [43608326670](https://github.com/ekkus93/pdf2audiobook/actions/runs/43608326670) passed.

## Phase TD3 — Engine bridge (D3)

- [x] TD3.01 D3.a: locate the CLI (settings path, `PATH`, `uv run --project`), confirm it with
  `--version` and `doctor --json`, and refuse a version whose major or minor differs. Tests with
  a fake CLI for each source and for a version mismatch.
  - Evidence: `src-tauri/src/engine/locate.rs`: candidates in order (settings path if executable,
    `pdf2audiobook` on PATH, `uv run --project <checkout> pdf2audiobook` when uv is on PATH); each
    is confirmed by `--version` and `doctor --json` reporting the same version, and a different
    major or minor version is refused (`VersionMismatch`); errors hold no paths. 11 tests with
    real fake-CLI scripts: `configured_path_is_used_first`, `cli_on_path_is_found`,
    `source_checkout_runs_through_uv` (checkout path with spaces),
    `a_different_minor_version_is_refused`, `a_different_major_version_is_refused`,
    `a_mismatched_configured_cli_falls_back_to_a_matching_one_on_path`,
    `doctor_disagreeing_with_version_is_unresponsive`,
    `something_else_called_pdf2audiobook_is_unresponsive`,
    `nothing_found_reports_not_found_without_paths`, `a_file_that_is_not_executable_is_skipped`,
    `series_reads_major_and_minor`. Parallel tests hit ETXTBSY when one thread writes a script
    while another forks (confirmed: 5 retries over 5 runs); the test-only `TestRunner` retries
    that errno, and 10 consecutive runs passed. cargo fmt, clippy -D warnings, cargo test, and the
    frontend checks pass. Commit 3ab14c122ac89447db8a944f5a8d59097235e22c, Python CI
    [43608955476](https://github.com/ekkus93/pdf2audiobook/actions/runs/43608955476) passed
    (desktop checks join CI in TD10.02).
- [x] TD3.02 D3.b: typed requests to argument vectors for every supported command and option;
  `--json` and `--no-progress` always added; no shell. Tests: one per request variant, and a
  test that a book path with spaces, quotes and leading dashes stays a single argument.
  - Evidence: `src-tauri/src/engine/request.rs`: one `Request` variant per command the app runs
    (doctor, config show, inspect, workspace, voices, thumbnail, analyze, convert, review, edits
    list/accept/reject, pack-m4b, regenerate-chapter, recover, budget show), with typed options
    (enums for OCR, providers, review reasons, edit status, footnotes; ranges for speed, sample
    rate, width, chapters and token counts; no empty or NUL text). Arguments are `--no-progress
    COMMAND --name=value ... --json -- POSITIONALS`, built as a vector and started without a
    shell. Tests: one exact argument vector per variant (17), defaults pass no options,
    `json_and_no_progress_are_always_present`, `write_capable_commands_are_marked`,
    `invalid_values_are_refused_without_echoing_them`,
    `requests_deserialize_from_the_frontend_shape`, and `an_awkward_book_path_stays_one_argument`
    (`/books/-x my "quoted" 'book'; rm -rf $HOME.pdf`: a real child receives it as one argument
    after `--`). The opt-in `real_cli_accepts_the_read_only_requests` ran the real CLI through uv
    (doctor, config show, inspect, workspace, thumbnail) and passed; Typer accepts `--name=value`
    and a dash-named file after `--`. Commit 7115a8b0285cda590b74493878b285513d77ed5a, Python CI
    [43608974129](https://github.com/ekkus93/pdf2audiobook/actions/runs/43608974129) passed.
- [x] TD3.03 D3.c: parse success JSON, the error object with optional `reason`, and unreadable
  output (fixed message with the exit code only). Tests for each.
  - Evidence: `src-tauri/src/engine/result.rs`: exit 0 with a JSON object on stdout is `Success`;
    otherwise the last stderr line that is a well-formed `{"ok": false, "error": {...}}` envelope
    is `Failed` with `type`, `code`, `message` and optional `reason` (log and warning lines before
    it are skipped); anything else is `Unreadable` with the exit code only, shown with the fixed
    message "The engine returned an unreadable result". 8 tests: `success_json_is_returned`,
    `every_reason_is_kept` (all 9 codes), `an_error_without_a_reason_has_none`,
    `the_error_is_found_after_log_lines`, `unreadable_success_output_keeps_only_the_exit_code` and
    `a_failure_without_an_error_object_is_unreadable` (neither keeps the output text),
    `a_process_ended_by_a_signal_is_unreadable`, `outcomes_serialize_for_the_frontend`. The opt-in
    real-CLI test also parses a real missing-book failure as `InputError` 3 with no reason. cargo
    fmt, clippy -D warnings, cargo test (42 passed) clean. Commit
    ee2a92dc71362c5ebdc8ebe60b8feea4b025c75e, Python CI
    [43609044424](https://github.com/ekkus93/pdf2audiobook/actions/runs/43609044424) passed.
- [x] TD3.04 D3.d: at most one write-capable command per workspace in the bridge. Tests: a
  second start is refused while the first runs; read-only commands are not blocked.
  - Evidence: `src-tauri/src/engine/runs.rs`: `WorkspaceRuns::try_start` claims a canonicalized
    workspace path for write-capable requests (`Request::is_write`) and returns a guard that frees
    it on drop; read-only requests claim nothing. 7 tests:
    `a_second_write_is_refused_while_the_first_runs` (and allowed again after the guard drops),
    `read_only_commands_are_not_blocked`, `read_only_runs_do_not_hold_the_workspace`,
    `different_workspaces_run_independently`,
    `another_spelling_of_the_same_folder_is_the_same_workspace` (symlink and `..`),
    `only_one_of_many_simultaneous_starts_wins` (16 threads behind a barrier),
    `the_busy_message_has_no_path`. cargo fmt, clippy, cargo test (49 passed) clean. Commit
    62c153942b34dca1b5c1b15324ba0b175cce0cee, Python CI
    [43609098083](https://github.com/ekkus93/pdf2audiobook/actions/runs/43609098083) passed.
- [x] TD3.05 D3.e: environment passed through; encrypted PDFs take an environment variable
  name, never a password. Test that no password value is ever placed in arguments.
  - Evidence: `SystemRunner` never clears or sets the child's environment, and a PDF password can
    only be an `EnvVarName` (`[A-Za-z_][A-Za-z0-9_]*`, at most 128 characters), so no password
    value can reach the arguments. Tests: `the_child_inherits_the_app_environment` (a real child
    sees the same HOME and PATH), `the_child_gets_no_input_and_its_output_is_captured`,
    `find_on_path_needs_an_executable_file`,
    `a_pdf_password_is_only_ever_an_environment_variable_name` (inspect, thumbnail, analyze and
    convert each carry only `--pdf-password-env=BOOK_PDF_PASSWORD`),
    `a_password_typed_where_a_variable_name_belongs_is_refused` (`hunter2!`, `my secret`,
    `p@ssw0rd` and others refused, also when deserialized from the frontend, without echoing the
    value). cargo fmt, clippy, cargo test (54 passed) clean. Commit
    108780a0ff8673ae21582777b84562073ee32a1c, Python CI
    [43609143809](https://github.com/ekkus93/pdf2audiobook/actions/runs/43609143809) passed.

## Phase TD4 — Shared contracts (D9.c)

- [x] TD4.01 Write JSON Schemas in `desktop/contracts/` for every output in spec D9.c.
  - Evidence: 15 JSON Schemas (draft 2020-12) in `desktop/contracts/`: doctor, config-show,
    inspect-book, inspect-manifest, workspace, voices, thumbnail, analyze, convert, convert-dry-
    run, edits-list, pack-m4b, review-address, error (with the 9 `reason` codes) and run-status,
    plus a README. Required fields are typed; objects allow added fields, except the review
    address line, which is exactly `{url, port}`. All 15 validated against real CLI output
    captured from the README demo book with `--no-llm` (doctor, config, inspect, workspace,
    voices, thumbnail, analyze, convert, dry run, pack-m4b, review, a missing-book error and a
    `review_required` error, and `run_status.json`). Commit
    0a4a732eb53c290aa2bf168c9c0e3dc8fb15cc19, Python CI
    [43609354757](https://github.com/ekkus93/pdf2audiobook/actions/runs/43609354757) passed.
- [x] TD4.02 Python tests validate real CLI output against those schemas (the `jsonschema`
  package added to the `dev` extra, with the lockfile updated).
  - Evidence: `jsonschema>=4.23,<5` added to the `dev` extra (`uv.lock` updated; jsonschema
    4.26.0). `tests/test_desktop_contracts.py` (15 tests) produces every output with the real CLI
    code, offline (fake Kitten voice, stand-in review server), and validates it against
    `desktop/contracts` with format checking: doctor, config show, inspect book and manifest,
    workspace, voices, thumbnail, analyze, run_status.json, convert dry run, convert and pack-m4b
    (through FFmpeg), edits list, the review address and the error object with and without a
    reason; `test_every_contract_has_a_test` keeps the list complete. Temporarily requiring a
    missing field in the doctor schema made the test fail with `'renamed_field' is a required
    property`. Ruff and format clean, mypy clean on 3.11/3.12/3.13 (isolated), pytest 2473 passed,
    1 skipped. Commit f0e2ab4bced3963108d9fce66fdbcc338726af39, Python CI
    [43609557856](https://github.com/ekkus93/pdf2audiobook/actions/runs/43609557856) passed.
- [x] TD4.03 Rust tests validate the parser's fixtures against the same schemas.
  - Evidence: `src-tauri/tests/fixtures/` holds real CLI outputs captured from the README demo
    book (paths replaced with `/home/user/books`), plus a `running` run status with a live stage
    and an edits list with one edit. `src-tauri/src/engine/contracts.rs` validates each against
    its schema with the `jsonschema` crate (format checking on) and parses it through
    `result::parse`: every success fixture parses to itself, both stderr fixtures parse to typed
    errors (`InputError` 3; `review_required` 6); `contracts_reject_a_broken_output` shows a
    missing field or an unknown reason fails; `every_contract_has_a_fixture`. cargo fmt, clippy -D
    warnings, cargo test (59 passed) clean. Commit a5d5ddbf4243d4713f774e91b20174456cbdbfa7,
    Python CI [43609697528](https://github.com/ekkus93/pdf2audiobook/actions/runs/43609697528)
    passed.

## Phase TD5 — Screens (D4)

Each screen has component tests for its loading, empty, success and error states, works with
the keyboard, and shows the command it runs under "Details". Each screen's item also records
dark and light screenshots (spec D11.h).

- [x] TD5.00 Design foundation (D11): generate the Material 3 scheme from the seeds `#6D5BD0`
  and `#E8A25C` with `@material/material-color-utilities` at build time into `--md-sys-color-*`
  CSS variables for dark and light; bundle Roboto Flex, Roboto Mono and Material Symbols
  Rounded; pin `@material/web` and wrap each component used in a small React component; build
  the navigation rail, top app bar, card, snackbar and player bar from the same tokens.
  Tests: the generated roles match the spec D11.b table; every text and icon pairing passes
  WCAG AA (D11.c); no font or icon is fetched at run time.
  - Evidence: Colours: `src/theme/scheme.ts` generates the Material 3 scheme from `#6D5BD0` and
    `#E8A25C` (tonal spot, iris-tinted neutrals); the `m3-theme` Vite plugin runs it at build and
    dev time through `runnerImport` into `--md-sys-color-*` for dark (default), light and system.
    Fonts: Roboto Flex and Roboto Mono from `@fontsource-variable`, and Material Symbols Rounded
    subset by `desktop/scripts/subset_icons.py` from 5.4 MB to 40.6 KB (44 icons drawn by
    codepoint; FILL, GRAD, opsz and wght axes kept). `@material/web` 2.5.0 pinned, with wrappers
    for buttons, icon buttons, text field, select, switch, checkbox, chips, dialog, progress and
    slider; navigation rail, top app bar, card, snackbar and player bar built from the same
    tokens; M3 type, shape and motion tokens with reduced motion respected. Tests (122):
    `scheme.test.ts` reads the D11.b table from the spec and matches all 22 roles in both themes;
    `contrast.test.ts` checks WCAG AA for every text pairing (4.5:1) and icon/boundary pairing
    (3:1) in both themes; `offline.test.ts` finds no remote URL in the HTML, the generated theme
    or any stylesheet and its imports, and every `url()` resolves locally; `ui.test.tsx` covers
    every wrapper and shell component. The built CSS holds the generated values (`#c9bfff` dark,
    `#5f52a7` light primary) and only local fonts. A real `npm run tauri dev` window shows the
    themed shell. Commit 0ec5846acacd50c7e58a141bd836757a59bc373c, Python CI
    [43610399942](https://github.com/ekkus93/pdf2audiobook/actions/runs/43610399942) passed.
  - Note: On 2026-11-14, after reviewing the first two screens, the owner asked for snazzier
    buttons (spec D11.i: gradient, gloss, sheen and gradient outlines, commits b93af00 and
    1ffbf1f) and a more striking font, choosing Instrument Serif with Figtree over the original
    Roboto Flex (spec D11.d). Roboto Mono stays. The offline test now checks the new fonts.
- [x] TD5.01 Setup: `doctor --json` results, Ollama served-context check, install hints.
  - Evidence: Setup screen (`src/screens/Setup.tsx`, rules in `setupChecks.ts`): finds the CLI,
    runs `doctor --json` and lists pdf2audiobook (version and where it was found), FFmpeg,
    Tesseract and missing OCR languages, Kitten, Piper (optional) and the LLM; every missing piece
    shows the exact install command with a copy button. The Ollama served-context check needed a
    CLI addition first: `doctor --check-llm` (commit 1f4bf43c673614e1aca14ae5bcd9985615eabf8a,
    `tests/test_cli_doctor_llm_check.py` 6 tests, doctor contract and fixture updated; Python CI
    [43610721251](https://github.com/ekkus93/pdf2audiobook/actions/runs/43610721251) passed), run
    only when the user presses Check context because it loads the model; too little context shows
    the Modelfile fix. Against the real Ollama it reported `qwen3.5:9b` served with 4,096 tokens
    against about 9,248 needed. Tests: `setupChecks.test.ts` (9) and `Setup.test.tsx` (10):
    loading, success, everything ready, engine not found, version mismatch, doctor failure,
    unreadable result, the on-request LLM check, the commands under a native Details disclosure,
    copy, and named keyboard-operable controls. Setup has no empty state. Keyboard use was checked
    in the real app under Xvfb: Tab to Settings and Enter opens Setup; this exposed an invisible
    focus ring on the rail, now fixed. Screenshots: `docs/images/tauri/setup-dark.png`, `setup-
    light.png`, `setup-llm-check-dark.png`, `keyboard-focus-dark.png`. Bridge commands
    (locate_engine, run_engine, describe_request) commit 3c5870fdfcd917820904e15a577506cfdca34b74,
    Python CI [43612250270](https://github.com/ekkus93/pdf2audiobook/actions/runs/43612250270)
    passed; screen commit eeafb686e7b3a1e389d48c3be497800f6c1f8772, Python CI
    [43612258477](https://github.com/ekkus93/pdf2audiobook/actions/runs/43612258477) passed.
- [x] TD5.02 Library: books in the output folder with state and last run; "Add book" dialog.
  - Evidence: Library screen (`src/screens/Library.tsx`, states in `bookState.ts`): a grid of book
    cards from the output folder (from the app settings, or the CLI's `general.output_dir`), each
    with a thumbnail made by the CLI's `thumbnail` command and cached in the app's cache folder,
    the title, chapter count, a state chip (not analyzed, needs review, ready, analyzing,
    converting, converted, needs attention) and the last run time from `run_status.json`. To judge
    review state and find the source book, `inspect MANIFEST --json` gained `source_path`,
    `review_required`, `review_acknowledged` and `approved` (commit
    0769bb4bb9371a0ed6e6a0b349c01bc00bf1efcf, contract and fixture updated; Python CI
    [43610927673](https://github.com/ekkus93/pdf2audiobook/actions/runs/43610927673) passed). "Add
    book" is a Material extended FAB opening the native file dialog (Tauri dialog plugin,
    `dialog:allow-open` only) filtered to PDF and EPUB; the book is remembered in the app settings
    and shown as "Not analyzed" until its workspace exists. The commands run (config show,
    inspect, thumbnail, workspace) are listed under Details. Tests: Rust
    `the_library_lists_books_with_their_inspection_and_thumbnail`,
    `a_configured_output_folder_overrides_the_cli_setting`,
    `added_books_appear_until_they_are_analyzed` and the settings tests; frontend
    `bookState.test.ts` (12) and `Library.test.tsx` (8): loading, success, Details, empty (names
    the folder), engine not found (sends to Setup), failure with retry, adding a book, a cancelled
    dialog and the labelled FAB. Checked in the real app under Xvfb with three original demo
    books: thumbnails, states and the FAB render in both themes. Screenshots:
    `docs/images/tauri/library-dark.png`, `library-light.png`. Commits
    3c5870fdfcd917820904e15a577506cfdca34b74 and eeafb686e7b3a1e389d48c3be497800f6c1f8772 (Python
    CI passed, see TD5.01) and 4e14283c93a428372ab3d94eda7cd600cfce6220 (Details), Python CI #823
    [43612519881](https://github.com/ekkus93/pdf2audiobook/actions/runs/43612519881) passed.
- [x] TD5.02a **[OWNER REVIEW]** The owner reviews the Setup and Library screens in dark and
  light (D11.h) before TD5.03–TD5.08 are built.
  - Evidence: The owner reviewed the Setup and Library screens in dark and light on 2026-11-14
    (screenshots in `docs/images/tauri/`). Feedback: liked overall; asked twice for snazzier
    buttons (done in b93af00 and 1ffbf1f, spec D11.i; the owner accepted the result for now, to
    revisit later) and for a more striking font (Instrument Serif with Figtree chosen from four
    rendered options, done in 8790b03, spec D11.d). The owner then approved the screens and the
    font choice and asked to continue.
- [x] TD5.03 Book options: LLM, model, context and output caps, voice (from `voices --json`),
  speed, chapter range, cover, and remote-content consent.
  - Evidence: Book page (`src/screens/BookPage.tsx`, form logic in `bookOptions.ts`), opened by
    clicking a library card (the card is one named button). Options load from the CLI's `config
    show` and `voices --json` and cover: LLM on or off, provider, model, context and output caps,
    remote-content consent (shown only for OpenAI, and required before either button works),
    voice, speed, all chapters or a range, and a cover image (native dialog filtered to JPEG and
    PNG). Validation mirrors the CLI (model required, context at least 512, the output cap plus
    128 must fit the context, speed 0.1 to 3, a range within the book). Nothing is stored per
    book: the choices become flags on the `analyze` and `convert` requests, whose exact commands
    appear under Details. Tests: `bookOptions.test.ts` (10: defaults from the config, every rule,
    the requests built) and `BookPage.test.tsx` (9: loading, success, load failure, Analyze and
    Convert with the options, an unanalyzed book, the OpenAI consent gate, cover choice, Details,
    the back button, opening from the library card). Checked in the real app under Xvfb in both
    themes. Screenshots: `docs/images/tauri/book-options-dark.png`, `book-options-light.png`.
    Commit c2c15bb94edca866599c6208ac2ab6f2b13baed5, Python CI #831
    [43623865218](https://github.com/ekkus93/pdf2audiobook/actions/runs/43623865218) passed.
- [x] TD5.04 Run: progress view (TD6) with cancel.
  - Evidence: Run screen (`src/screens/Run.tsx`): book title and task, the current stage with its
    detail, a percentage, a progress bar, done of total in words (characters, LLM requests,
    pages), elapsed time and the estimate (or "estimating…"), finished stages with their times,
    and Stop. A finished run shows success with its time, Stopped, or the engine's error.
    `Run.test.tsx` covers the empty state, polling in steps, estimating, Stop, success, stopped,
    errors and unreadable results. In the real app under Xvfb a 13-chapter demo book converted
    with real Kitten speech: mid-run 15%, chapter 3/13, 2,535 of 16,804 characters, 10 s elapsed,
    about 1m 17s left; finished in 1m 02s with 13 MP3s. Screenshots: `docs/images/tauri/run-
    progress-dark.png`, `run-progress-light.png`, `run-finished-light.png`. Commits
    6f625312b01393c8e0606ba32b3505259dff2324, Python CI #832
    [43625820043](https://github.com/ekkus93/pdf2audiobook/actions/runs/43625820043) passed
    (bridge) and ed1e99728d722a4be0e4d97d71479a594d787ea3, Python CI #833
    [43625829091](https://github.com/ekkus93/pdf2audiobook/actions/runs/43625829091) passed
    (screen).
- [x] TD5.05 Review: opens on `review_required` and `review_acknowledgement_required` (TD7).
  - Evidence: A run that stops with `review_required` or `review_acknowledgement_required` opens
    chapter review by itself, once, and shows "This book's chapters need your review" with a
    Review chapters button (`Run.test.tsx`, both reasons). The book page has a review panel, amber
    when chapters need review, with Review chapters (`BookPage.test.tsx`). Commit
    0fdc1afd180305c31510286559782db15f8a2ed2, Python CI #836
    [43626595603](https://github.com/ekkus93/pdf2audiobook/actions/runs/43626595603) passed.
- [x] TD5.06 Pending edits: list, accept or reject each, and "accept all" behind a
  confirmation that shows the count.
  - Evidence: The book page's Pending edits section (`src/screens/PendingEdits.tsx`) lists each
    pending edit with its chapter, provider, original text (struck through) beside the proposed
    text, and the model's reason; Accept and Reject act on that edit (`edits accept|reject MANIFEST ID`), and Accept all asks first in a dialog that shows the count. `edits list --json`
    omitted the text, so the CLI gained `--with-text`, which adds `original`, `replacement` and
    `reason` only when asked (`tests/test_cli_edits_with_text.py`: none without the flag, all
    three with it; contract `edits-list` extended and checked; commit
    c93643471f29a7cf43902063588780201178a11a, Python CI #837
    [43626777117](https://github.com/ekkus93/pdf2audiobook/actions/runs/43626777117) passed).
    `PendingEdits.test.tsx` (6 tests): the list, nothing waiting, a load failure, accepting and
    rejecting one edit for the book's workspace, Accept all only after confirming the count, and a
    refused decision. In the real app, Accept all on two pending edits of the Lighthouse demo book
    confirmed with "Accept all 2 edits?"; afterwards `edits list --status all --json` showed both
    `accepted` and the section said "No edits are waiting for you". Screenshots:
    `docs/images/tauri/pending-edits-dark.png`, `pending-edits-light.png`, `pending-edits-accept-
    all-dark.png`. Commit 7e9cfab5ae7b3ec5e66474c4596797693d7d6a42, Python CI #838
    [43627404890](https://github.com/ekkus93/pdf2audiobook/actions/runs/43627404890) passed.
- [x] TD5.07 Chapters and audio: per-chapter state, player, open folder, M4B, export (TD8).
  - Evidence: The book page's Chapters and audio section (`src/screens/ChaptersAudio.tsx`) shows
    each chapter with Converted, Failed or Not converted (from `conversion_status` and the MP3s
    present) and a play button for converted ones, plus Open folder, Make M4B and Export zip
    (TD8.02, TD8.03); a bottom player (`src/screens/Player.tsx`) plays, pauses, moves between
    chapters and goes on to the next one when a chapter ends. Tests: `ChaptersAudio.test.tsx`
    (11), `Player.test.tsx` (6), `BookPage.test.tsx` (the section and play hand-off). Open folder
    runs `xdg-open` on the book's `audio/` folder only (bridge command `open_audio_folder`), not a
    general opener. In the release build a chapter played and the player moved on to the next by
    itself. Screenshots: `docs/images/tauri/chapters-audio-dark.png`, `chapters-audio-light.png`,
    `player-dark.png`. Commit 46d7bb33dad9a083c2424fa6b5e08c070ab61308, Python CI #840
    [43631327843](https://github.com/ekkus93/pdf2audiobook/actions/runs/43631327843) passed.
- [x] TD5.08 Settings: CLI location, output folder, default voice with the README samples, LLM
  settings; effective CLI configuration shown read-only.
  - Evidence: Settings (`src/screens/Settings.tsx`) edit only the app's settings file: CLI
    location and source checkout (with Browse), output folder (showing the CLI's own folder when
    empty), default voice with play buttons for the README's eight Kitten samples (bundled from
    `docs/audio/voices` by Vite, not copied), LLM provider and model, and theme. New books start
    from these (`bookOptions.defaults` preferences; empty fields use the CLI's values). The
    effective CLI configuration (`config show --sources --json`) is shown read-only as setting,
    value and source (built-in, config file or environment), with where to change it; the setup
    check is part of the page. Rust: the three new fields load from older settings files and
    round-trip. Tests: `Settings.test.tsx` (configRows and source labels; defaults shown; saving
    keeps unedited fields and applies the theme; clearing a field goes back to the CLI's value;
    Browse; sample playback and its failure; the read-only table; the CLI unreachable; a failed
    save), `bookOptions.test.ts` (preferences used, CLI model for a preferred provider). In the
    real app, choosing Luna and saving wrote `"default_voice": "Luna"` to `settings.json` with the
    other fields kept, and a book page then started with Luna. Screenshots:
    `docs/images/tauri/settings-dark.png`, `settings-light.png`, `settings-saved-dark.png`,
    `settings-cli-config-dark.png`. Commit 27d434f6074b9749dafd29beddc8c4731e10ae47, Python CI
    #841 [43632382414](https://github.com/ekkus93/pdf2audiobook/actions/runs/43632382414) passed.
- [x] TD5.09 Each D2.b `reason` leads to the action in the spec table. Tests for every reason.
  - Evidence: `src/screens/reasons.tsx` maps each D2.b reason to its action on the Run screen:
    review_acknowledgement_required shows the book-wide reasons still unacknowledged (from
    `inspect`) and Acknowledge and convert (runs convert again with `--accept-review`);
    workspace_locked offers Wait and try again (retries every 5 s until the book is free) or
    Cancel; chapter_conflict offers Regenerate chapter N with a backup (`regenerate-chapter
    --chapter N`), then Run again; llm_unreachable links to the LLM settings;
    llm_context_too_small explains `num_ctx` (the README's Modelfile steps) and the Context
    setting; llm_output_cap suggests a larger output cap; budget_exhausted shows the budget screen
    (`budget show --json` against the configured limits, with how to raise them and resolve
    unknown requests). review_required (review opens by itself) and pending_recovery (Recover)
    were done in TD5.05 and TD6.03. `reasons.test.tsx` (26 tests) covers each reason through the
    Run screen, plus a failure without a reason; with `Run.test.tsx` all nine are tested. New
    contract `budget-show` with a Python test on a real ledger and a Rust fixture from real
    output. In the real app, with the book's lock held by another process, Convert showed "Another
    task is using this book"; Wait and try again retried every 5 s, and after the lock was
    released the conversion started by itself. Screenshots: `docs/images/tauri/reason-locked-
    dark.png`, `reason-locked-waiting-dark.png`. Commit 4512c39b8770f35e74f8b5a4c9d1aed516915544,
    Python CI #842
    [43633181030](https://github.com/ekkus93/pdf2audiobook/actions/runs/43633181030) passed.

## Phase TD6 — Progress and long runs (D5)

- [x] TD6.01 D5.a: poll `run_status.json` from the workspace given by TD1.02 and show stage,
  counts, elapsed and estimate. Test with a fake CLI that writes the file in steps.
  - Evidence: `LiveRuns::progress` (`src-tauri/src/engine/live.rs`) reads the workspace's
    `reports/run_status.json` (size-limited) on each poll; the Run screen polls it about once a
    second. The workspace is the one the library knows for the book (from its folder, or from the
    `workspace` command for an added book). `progress_follows_run_status_until_the_result` runs a
    fake CLI that writes `run_status.json` in steps and checks each step and the final result;
    `Run.test.tsx` checks the screen updates through the steps. Commits
    6f625312b01393c8e0606ba32b3505259dff2324, Python CI #832
    [43625820043](https://github.com/ekkus93/pdf2audiobook/actions/runs/43625820043) passed and
    ed1e99728d722a4be0e4d97d71479a594d787ea3, Python CI #833
    [43625829091](https://github.com/ekkus93/pdf2audiobook/actions/runs/43625829091) passed.
- [x] TD6.02 D5.b: a run ends when the child exits; a stale `running` state is shown as stopped.
  - Evidence: A run ends when its child exits: a waiter thread collects the output and parses the
    result. A `run_status.json` still at `running` after the child exits is reported as `stopped`
    (`a_run_left_running_in_run_status_is_reported_stopped_once_the_child_exits`). The library
    marks a book `live` only while this app has a run on it, so a stale `running` status no longer
    shows as Converting (`bookState.test.ts`: a running status left by a stopped run isn't in
    progress). Commits 6f625312b01393c8e0606ba32b3505259dff2324, Python CI #832
    [43625820043](https://github.com/ekkus93/pdf2audiobook/actions/runs/43625820043) passed and
    ed1e99728d722a4be0e4d97d71479a594d787ea3, Python CI #833
    [43625829091](https://github.com/ekkus93/pdf2audiobook/actions/runs/43625829091) passed.
- [x] TD6.03 D5.c: cancel sends the termination signal, waits up to 30 seconds, then kills, and
  offers `recover` after a `pending_recovery` error. Tests with a fake CLI that ignores the
  signal and one that exits cleanly.
  - Evidence: Stop sends SIGTERM to the CLI (which treats it as Ctrl+C, TD1.05; uv 0.12.5 was
    checked to forward SIGTERM and pass back exit 130), waits up to 30 s (`CANCEL_GRACE`), then
    kills the run's process group (`process_group(0)`). Tests with fake CLIs:
    `cancel_stops_a_cooperative_run_with_its_own_result` (the Interrupted error, well within the
    grace period) and `cancel_kills_a_run_that_ignores_the_signal_after_the_grace_period` (nothing
    of the group left). After a `pending_recovery` error the Run screen offers Recover, and if
    that is refused because files changed, "Back up the changed files and recover"
    (`Run.test.tsx`; commit f728e3e57442f2edfdd1aae973f8c17baa3590fd, Python CI #835
    [43626149718](https://github.com/ekkus93/pdf2audiobook/actions/runs/43626149718) passed). In
    the real app Stop ended a real conversion within a second: Stopped, `run_status.json`
    `stopped`, finished chapters kept, no engine process left. Screenshot: `docs/images/tauri/run-
    stopped-dark.png`. Commits 6f625312b01393c8e0606ba32b3505259dff2324, Python CI #832
    [43625820043](https://github.com/ekkus93/pdf2audiobook/actions/runs/43625820043) passed and
    ed1e99728d722a4be0e4d97d71479a594d787ea3, Python CI #833
    [43625829091](https://github.com/ekkus93/pdf2audiobook/actions/runs/43625829091) passed.
- [x] TD6.04 D5.d: closing the window during a run asks, then cancels; no child process
  outlives the app. Test that checks for orphaned processes after a forced close.
  - Evidence: Closing the main window during a run is held back (`prevent_close`) and the frontend
    asks "Stop the running task and quit?" (Keep running is the default focus); Stop and quit
    calls `quit_app`, which stops every run (SIGTERM, then the group kill after the grace period)
    before exiting, and `RunEvent::Exit` stops any run left however the app ends.
    `shutdown_leaves_no_process_behind` runs a fake CLI that ignores SIGTERM and has started a
    grandchild, and checks no process of its group is left running (zombies don't count: this
    container's PID 1, jupyter-labhub, never reaps orphans). `App.test.tsx` checks the prompt and
    quit. In the real app a close request (WM_DELETE_WINDOW) mid-conversion showed the prompt;
    Stop and quit closed the window, left `run_status.json` `stopped`, finished chapters kept, and
    no engine or app process running. Screenshot: `docs/images/tauri/run-close-dialog-dark.png`.
    Commits 6f625312b01393c8e0606ba32b3505259dff2324, Python CI #832
    [43625820043](https://github.com/ekkus93/pdf2audiobook/actions/runs/43625820043) passed and
    ed1e99728d722a4be0e4d97d71479a594d787ea3, Python CI #833
    [43625829091](https://github.com/ekkus93/pdf2audiobook/actions/runs/43625829091) passed.

## Phase TD7 — Chapter review (D6)

- [x] TD7.01 D6.a: start `review --json --port 0`, open the URL in a review window that may
  load only that origin.
  - Evidence: `open_review` (`src-tauri/src/commands.rs`, server in `engine/review.rs`) starts
    `review --json --port 0` holding the book's write guard, reads the address line, and opens it
    in a separate window whose navigation is limited to that exact `http://127.0.0.1:<port>`
    origin (`allowed`; `the_window_may_only_load_the_review_server` refuses other ports, https,
    localhost, other hosts and file URLs). The window is not in any capability, so it has no
    access to the app's commands. Tests: `the_address_line_is_read_and_stop_ends_the_server`,
    `an_engine_error_before_the_address_is_reported` (e.g. `workspace_locked`),
    `no_address_in_time_is_refused_and_the_server_is_stopped`. In the real app the window opened
    as "Review chapters: The Lighthouse at Gull Point" showing the review page. Screenshot:
    `docs/images/tauri/review-window-dark.png`. Commit 0fdc1afd180305c31510286559782db15f8a2ed2,
    Python CI #836
    [43626595603](https://github.com/ekkus93/pdf2audiobook/actions/runs/43626595603) passed.
- [x] TD7.02 D6.b: closing the window stops the server and refreshes the book's state.
  - Evidence: When the review window is destroyed, the server is stopped (SIGTERM, then the group
    kill after the grace period; `a_server_that_ignores_sigterm_is_killed_after_the_grace_period`)
    and `review-closed` is sent; the app then re-reads the library and the open book
    (`App.test.tsx`: re-reads the library when the review window closes). In the real app, after a
    close request the window was gone and no review server process was left. Commit
    0fdc1afd180305c31510286559782db15f8a2ed2, Python CI #836
    [43626595603](https://github.com/ekkus93/pdf2audiobook/actions/runs/43626595603) passed.
- [x] TD7.03 D6.c: explain that merging and splitting need a manifest edit, with a link to the
  README section; no manifest writes by the app.
  - Evidence: The review panel's "Merging or splitting chapters" disclosure explains that the
    review page can rename chapters and move their bounds but not add or remove them, that merging
    or splitting means editing the `chapters` list in the manifest with a backup, as in the README
    section "Protecting manual edits", and that the app never edits the manifest; it shows the
    manifest path with a copy button (`BookPage.test.tsx`). Note: the README is named rather than
    linked, because opening links needs the opener plugin, which spec D8.a excludes. Commit
    0fdc1afd180305c31510286559782db15f8a2ed2, Python CI #836
    [43626595603](https://github.com/ekkus93/pdf2audiobook/actions/runs/43626595603) passed.

## Phase TD8 — Listening and output (D7)

- [x] TD8.01 D7.a: play chapter MP3s through the asset protocol scoped to the book's `audio/`
  folder. Test that a path outside it is refused.
  - Evidence: Chapter MP3s are read through Tauri's asset protocol, enabled with an empty scope;
    listing a book's chapters (`book_audio`) allows that book's `audio/` folder only (a symlinked
    `audio` pointing elsewhere is refused).
    `audio::tests::the_asset_scope_allows_only_the_opened_books_audio_folder` runs Tauri's real
    scope on a mock app: nothing before a book is opened, then its chapters but not
    `manifest.json` or the workspace. WebKitGTK's media element can't stream from the custom
    `asset:` scheme (error 4, "source not supported"), so the player fetches the file over the
    asset protocol and plays a `blob:` URL (see "Found while"); `Player.test.tsx` checks a path
    outside the folder is refused (403) and shows "This chapter couldn't be loaded". In the real
    app the asset protocol returned the chapter (200, audio/mpeg, 176,066 bytes) and refused the
    book's `manifest.json` next to it (403). Note: the scope keeps the audio folders of books
    opened earlier in the session; Tauri's scope can't be narrowed again. Commit
    46d7bb33dad9a083c2424fa6b5e08c070ab61308, Python CI #840
    [43631327843](https://github.com/ekkus93/pdf2audiobook/actions/runs/43631327843) passed.
- [x] TD8.02 D7.b: "Make M4B" runs `pack-m4b --json` to a user-chosen path, with the cover if
  set; a stale chapter shows the CLI's message and offers to continue converting.
  - Evidence: Make M4B asks for a path with the save dialog and runs `pack-m4b --json` with the
    book's cover when one is set. A stale or missing chapter shows the CLI's message and a
    Continue converting button; other failures don't (`ChaptersAudio.test.tsx`).
    `tests/test_pack_m4b_safety.py` now also pins the phrase "stale or missing" the app
    recognizes. In the real app, saving through the GTK dialog wrote `tides.m4b`; ffprobe showed
    three chapters with their titles, 23.88 s in all. Screenshot: `docs/images/tauri/m4b-saved-
    dark.png`. Commit 46d7bb33dad9a083c2424fa6b5e08c070ab61308, Python CI #840
    [43631327843](https://github.com/ekkus93/pdf2audiobook/actions/runs/43631327843) passed.
- [x] TD8.03 D7.c: "Export zip" with chapter MP3s and, optionally, the source book, written to a
  user-chosen path outside the workspace. Test the zip's contents.
  - Evidence: Export zip asks for a path with the save dialog and writes the chapter MP3s under
    `<title>/audio/` and, if ticked (the default), the source book under `<title>/`
    (`audio::export_zip`), stored uncompressed, written to a temporary file and renamed, mode
    0644. Tests: `the_zip_holds_the_chapters_and_optionally_the_book` (entry names, contents,
    0644, no temporary file left, and the audio-only variant),
    `a_zip_inside_the_workspace_is_refused_and_nothing_is_written`,
    `a_book_with_no_mp3_has_nothing_to_export`; `ChaptersAudio.test.tsx` checks the book is
    included by default and left out when unticked. In the real app the export held the PDF and
    the three MP3s under `Field Notes on Tides/`. Commit 46d7bb33dad9a083c2424fa6b5e08c070ab61308,
    Python CI #840
    [43631327843](https://github.com/ekkus93/pdf2audiobook/actions/runs/43631327843) passed.

## Phase TD9 — Security and privacy (D8)

- [x] TD9.01 D8.a: capabilities limited to dialog, the bridge's commands and the scoped asset
  protocol. Test (or a checked-in review script) that fails if another permission is added.
  - Evidence: The main window's capability now grants only `core:event:allow-listen`,
    `core:event:allow-unlisten`, `dialog:allow-open` and `dialog:allow-save` (was `core:default`);
    the app's own commands need no permission, the review window has none, and the asset protocol
    starts with an empty scope (TD8.01). `src-tauri/tests/permissions.rs` fails if a capability
    file, window, permission or Tauri plugin (Rust or npm) is added; adding `core:default` back
    made it fail. In the release build, events still arrive: the Review chapters button re-enabled
    when the review window closed (`review-closed`). Commit
    1c0ecc967e8fa63c5f16440bf82bc5e64b268260, Python CI #843
    [43634551329](https://github.com/ekkus93/pdf2audiobook/actions/runs/43634551329) passed.
- [x] TD9.02 D8.b: CSP for the main window with no remote origins and no `unsafe-eval`; the
  review window limited to its loopback URL.
  - Evidence: `tauri.conf.json` sets `csp`: `default-src`, `script-src` and `style-src` `'self'`,
    `style-src-attr 'unsafe-inline'` (Material's style attributes), `img-src 'self' data:`
    (thumbnails), `media-src 'self' blob:`, `connect-src` limited to `'self'` and Tauri's IPC and
    asset protocols, `object-src` and `frame-src 'none'`. `devCsp` adds only Vite's dev server
    (`ws://localhost:1420`, inline scripts) for `tauri dev`. `permissions.rs` checks both: no
    `unsafe-eval`, no wildcard, no remote origin. The review window may only load its
    `http://127.0.0.1:<port>` page (TD7.01's `the_window_may_only_load_the_review_server`). In a
    release build the library, thumbnails, fonts, playback and voice samples all worked under the
    policy. Commit 1c0ecc967e8fa63c5f16440bf82bc5e64b268260, Python CI #843
    [43634551329](https://github.com/ekkus93/pdf2audiobook/actions/runs/43634551329) passed.
- [x] TD9.03 D8.c: privacy test with marker strings in the title, file name and text; none
  appears in the app log or any error dialog.
  - Evidence: The app now keeps a log (`src-tauri/src/applog.rs`): one JSON line per event (app
    start, each CLI command, run start and end, review opened and closed) with only the event
    name, the CLI command's name, exit code, duration, outcome and the `reason` code if it looks
    like one; never a path, title or message. It goes to `pdf2audiobook-desktop.log` in the app's
    log folder and is moved aside past 512 KB. `src-tauri/src/privacy.rs`: a fake CLI echoes
    title, file-name and text markers on stdout and stderr and in its error message, warnings and
    a non-code reason, run with marker paths both as a command and as a live run; the log holds no
    marker and no path. With the code check bypassed the test failed. A second test checks every
    bridge error (refused requests, a busy book, audio and export refusals, a CLI that can't
    start) holds no marker. `tests/test_desktop_privacy.py` (7 tests): a real PDF with the markers
    in its title, file name and text; review_required, workspace_locked, llm_unreachable (a
    refused loopback port), pack-m4b without audio, budget without a ledger and an unreadable book
    all fail with no marker in anything printed, and `edits list --json` carries none. In the
    release build the log held lines such as `{"event":"engine_command","command":"voices","exit_c
    ode":0,"seconds":0.891,"outcome":"success"}`. Commit 1c0ecc967e8fa63c5f16440bf82bc5e64b268260,
    Python CI #843
    [43634551329](https://github.com/ekkus93/pdf2audiobook/actions/runs/43634551329) passed.
- [x] TD9.04 D8.d: the app itself makes no network requests. Test with networking blocked for
  the app process (the fake CLI needs none).
  - Evidence: `desktop/scripts/no_network.py` runs a command under a seccomp filter (libseccomp
    through ctypes, no privileges) that makes `socket()` fail for IPv4 and IPv6 in the process and
    everything it starts; Unix sockets still work. The release app ran under it with the real CLI
    from the project and `UV_OFFLINE=1`: the library, a book page, chapter playback through to the
    next chapter, Settings with the setup check (FFmpeg, Tesseract and Kitten ready), and a clean
    exit (code 0). Static checks: `permissions.rs` `the_app_links_no_network_client` (`cargo tree
    --offline` for the shipped build has no reqwest, hyper, h2, ureq or similar; with dev edges
    reqwest does appear, so the check would see one) and `src/network.test.ts` (no WebSocket,
    EventSource, XHR or beacons; one `fetch`, for the app's own files; no remote address). Note:
    the review window talks to the CLI's review server on 127.0.0.1 by design (D6); that server is
    the CLI's, and it is not run under the filter. Commit
    1c0ecc967e8fa63c5f16440bf82bc5e64b268260, Python CI #843
    [43634551329](https://github.com/ekkus93/pdf2audiobook/actions/runs/43634551329) passed.

## Phase TD10 — End to end, CI and packaging (D9.d, D10)

- [x] TD10.01 D9.d: `tauri-driver` WebDriver test on Linux: add the demo book, analyze with
  `--no-llm`, review (retitle chapter 1 and save), convert with `--dry-run`.
  - Evidence: `desktop/e2e/walkthrough.mjs` (`npm run e2e`) drives a release build through `tauri-
    driver` and WebKitWebDriver with plain W3C WebDriver calls: the library starts empty; Add book
    opens the native file dialog, where `xdotool` types the README demo book's path
    (`scripts/readme_screenshots/make_demo_pdf.py`); the book is analyzed with the LLM switched
    off; Review chapters opens the review window, chapter 1 is retitled and saved ("Saved and
    approved"), and the window is closed as a user would (`e2e/close_window.py`,
    WM_DELETE_WINDOW); then Convert runs with `--dry-run` (the app's CLI location points at a
    wrapper that adds it to the real CLI from the checkout). It then reads the manifest: chapter 1
    has the new title and is approved. Screenshots go to an artifacts folder (ImageMagick;
    WebKitWebDriver's own screenshot command doesn't answer under Xvfb), and the temporary home is
    removed. It found a bug: after a run, Back to the book showed the book as it was before the
    run, so an analyzed book had no review panel; fixed in
    b99e4bb852e5d3e4d032caba1f0e699c2ab14ff4 (`App.test.tsx` fails without the fix; Python CI #845
    [43637832735](https://github.com/ekkus93/pdf2audiobook/actions/runs/43637832735) passed).
    Locally it passed twice against the release binary; in CI it passes against the release binary
    and against the AppImage. Commit a3e270843871d0267793c57b95fa1eadad7fb66f; CI:
    9b03d4eefe28463bc3dffe6a5d5b4c9245cad451, Desktop CI #4
    [43638534169](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638534169) passed
    (Python CI #849
    [43638534189](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638534189) passed).
- [x] TD10.02 D10.c: CI job for `desktop/` (fmt, clippy, tests, frontend checks, Linux
  `tauri build`, the end-to-end test). Depends on TD0.03.
  - Evidence: `.github/workflows/desktop.yml` ("Desktop CI") runs on pushes to master and tauri,
    on pull requests and by hand, on Ubuntu 22.04: apt packages for WebKitGTK, its WebDriver and
    the X tools (time-bounded, retried, cached), Node 22 with `npm ci`, stable Rust with clippy
    and rustfmt, uv 0.12.9 with the locked CLI; then frontend lint, type check, tests and build,
    `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test`, `tauri build
    --bundles appimage,deb`, and the walkthrough under Xvfb against the release binary and against
    the AppImage. `tests/test_desktop_ci.py` (5 tests) checks the triggers, every check, the uv
    pin shared with `ci.yml`, Node 22, the AppImage walkthrough and the unsigned artifacts.
    Attempts: Desktop CI #1
    [43637961235](https://github.com/ekkus93/pdf2audiobook/actions/runs/43637961235) (a3e2708)
    failed at `npm ci`: the lock file written by npm 11 lacked optional packages npm 10 expects;
    rewritten with npm 10 in 66f09811d1ce6a625578219a20e1800314f88663. #2
    [43638257820](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638257820) (66f0981) and
    #3 [43638448307](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638448307) (f443007)
    failed in two frontend tests whose fetch stubs passed jsdom's Blob to Node 22's Response;
    fixed in 9b03d4e. 9b03d4eefe28463bc3dffe6a5d5b4c9245cad451, Desktop CI #4
    [43638534169](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638534169) passed
    (Python CI #849
    [43638534189](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638534189) passed):
    every step, about 10 minutes.
- [x] TD10.03 D10.b: Linux AppImage and `.deb` from CI as build artifacts. macOS and Windows
  wait for O2.
  - Evidence: Desktop CI builds the AppImage and `.deb` and uploads them as the `pdf2audiobook-
    desktop-linux-unsigned` artifact (`if-no-files-found: error`). Desktop CI #4
    [43638534169](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638534169)
    (9b03d4eefe28463bc3dffe6a5d5b4c9245cad451): `pdf2audiobook_0.1.0_amd64-unsigned.AppImage`
    (82,143,736 bytes) and `pdf2audiobook_0.1.0_amd64-unsigned.deb` (3,608,282 bytes), artifact
    85,070,981 bytes; the AppImage then passed the walkthrough in the same run. macOS and Windows
    wait for O2.
- [x] TD10.04 **[OWNER DECISION]** D10.d signing and notarization (O4). Unsigned builds are
  labelled as unsigned until then.
  - Evidence: The owner chose unsigned builds for now (spec §14, O4). Installers are labelled in
    their file names: CI renames them to `*-unsigned.AppImage` and `*-unsigned.deb` before
    uploading (`tests/test_desktop_ci.py::test_installers_are_uploaded_and_named_unsigned`), as in
    Desktop CI #4
    [43638534169](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638534169). Signing and
    notarization stay an owner decision for later.
  - Note: The owner chose unsigned builds for now (spec §14, O4). The item stays open until the
    build labels unsigned installers, which is part of TD10.03.
- [x] TD10.05 Manual acceptance on this machine: install the AppImage, convert the README demo
  book with real Kitten speech, and record the result. Real LLM use with Ollama is recorded
  separately and stays optional.
  - Evidence: On this machine (Ubuntu 22.04 container, WebKitGTK 2.50.4, no FUSE): the AppImage
    built from f443007122faf2a76af80b7b90af58e4b5a4adb8's code (sha256
    4af7ebcfff82d11fe14fabb17f140c8fdfd678e3b388cc8da034284634db0518, 82,086,392 bytes) was
    installed by copying it into an Applications folder and run with `APPIMAGE_EXTRACT_AND_RUN=1`.
    The README demo book was added through the file dialog, analyzed without the LLM, reviewed
    (chapter 1 retitled and saved) and converted with real Kitten speech (`E2E_DRY_RUN=0`):
    "Conversion finished in 8s" and four MP3s, 4.9 s, 33.6 s, 29.7 s and 24.1 s (ffprobe).
    Screenshots: `docs/images/tauri/acceptance-appimage-added-dark.png`, `acceptance-appimage-
    converted-dark.png`. The first attempt found that the AppImage's environment broke the CLI
    (see "Found while"); fixed in f443007 before this run. Note: the run was driven by the
    walkthrough under Xvfb rather than by hand, and nobody listened to the audio. Real LLM use
    with Ollama was not run (optional).

## Found while writing the spec and working

- `pdf2audiobook --version` exits 2 with "Missing command" unless a command follows it
  (master at 05ca4c37685325ced177cf06d21de2506fe18cd2). Tracked as TD1.01.
- Local mypy is not clean when the `kitten` extra is installed: `tts/__init__.py:59` reports
  `import-untyped` for `kittenml`, which its `type: ignore[import-not-found]` doesn't cover.
  CI installs only the `dev` extra, where the import is not found and the ignore applies, so CI
  is clean. The TD0.01 baseline result came from mypy's cache. Checks in this TODO therefore run
  mypy as CI does, in an isolated environment without Kitten:
  `uv run --isolated --extra dev mypy --no-incremental --python-version X`. Not fixed here.
- The book page's options start from the CLI's configuration (and the app's Settings), not from
  how the book was last analyzed. A book analyzed with `--no-llm`, whose chapters were then
  approved in review, gets "Use an LLM" on by default when the CLI config enables the LLM; Convert
  then stops with "This workspace contains manually approved or protected chapter/cleanup
  edits" because the LLM stage changed. The CLI's protection is right; the app could start from
  the book's own analysis settings instead. Seen in the real app while checking TD5.09; not
  fixed here.
- WebKitGTK's media element can't stream from Tauri's custom `asset:` scheme ("source not
  supported", error 4), though `fetch` over it works. The player and the voice samples therefore
  fetch the file and play a `blob:` URL (TD8.01). In this container, with no sound device, the
  release build plays and advances through chapters; with a PipeWire null sink started by hand
  the web process stalled for some seconds while connecting.

- The AppImage's launcher points `PATH`, `PYTHONHOME`, `PYTHONPATH`, `LD_LIBRARY_PATH`,
  `XDG_DATA_DIRS` and GTK/GIO variables into the image, and the app's child processes inherited
  them: the CLI's Python couldn't start ("The pdf2audiobook command-line tool did not respond as
  expected"). Found in TD10.05's acceptance run; the release binary run directly was fine. The
  bridge now gives every child (CLI, live runs, the review server, `xdg-open`) the host's
  environment back: variables pointing into the image keep only their entries outside it or are
  removed, and the launcher's own variables are dropped; everything else passes unchanged, so
  spec D3.e still holds for what the user set (`engine::process::host_environment`). CI now also
  walks through the AppImage itself.
- `npm ci` on CI's Node 22 (npm 10) rejected a lock file written by npm 11 (optional
  `@emnapi` packages left out). The lock is now written with npm 10; `desktop/README.md` says so.

## Progress ledger

| Date | Branch SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-14 | fc65d442887297608f60d97cd0ba4f7457e2ced0 | Tauri TD0.03 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): Python CI runs on pushes to the `tauri` branch | `ci.yml` cross-check tests pass; Exact-head Python CI #790 [43605414647](https://github.com/ekkus93/pdf2audiobook/actions/runs/43605414647) passed on attempt 1 | None |
| 2026-11-14 | c95255dd76663c3f3dff077157dc88312b3e1206 | Tauri TD1.01 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): `pdf2audiobook --version` works without a command | /verify-equivalent checks: pytest 2415 passed, 1 skipped; mypy 3.11/3.12/3.13 clean; Exact-head Python CI #791 [43605569128](https://github.com/ekkus93/pdf2audiobook/actions/runs/43605569128) passed on attempt 1 | None |
| 2026-11-14 | 8fa1af7b3f1c93c955b7358efc84bad04f3287eb | Tauri TD1.02 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): `workspace` command shows a book's workspace folder | pytest 2418 passed, 1 skipped; Exact-head Python CI #792 [43605747057](https://github.com/ekkus93/pdf2audiobook/actions/runs/43605747057) passed on attempt 1 | None |
| 2026-11-14 | 246571bcff17276f357332ed11d165c67a63ef71 | Tauri TD1.03 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): stable `reason` codes on JSON errors | pytest 2434 passed, 1 skipped; 14 of 16 new tests fail without the change; Exact-head Python CI #794 [43606260786](https://github.com/ekkus93/pdf2audiobook/actions/runs/43606260786) passed on attempt 1 | None |
| 2026-11-14 | bbef731af2263514b2f15e4665eeb9550b804ca2 | Tauri TD1.04 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): `review --json` prints its address as one JSON line | pytest 2437 passed, 1 skipped; Exact-head Python CI #795 [43606481323](https://github.com/ekkus93/pdf2audiobook/actions/runs/43606481323) passed on attempt 1 | None |
| 2026-11-14 | 084afcce6f28f7fe8e52f19d69f50376a84da1d9 | Tauri TD1.05 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): SIGTERM stops a run like Ctrl+C (new `cli:main` entry point) | pytest 2438 passed, 1 skipped; real-process SIGTERM test; Exact-head Python CI #796 [43606790093](https://github.com/ekkus93/pdf2audiobook/actions/runs/43606790093) passed on attempt 1 | Windows CTRL_BREAK_EVENT not handled (Linux only, O2) |
| 2026-11-14 | c87c24a350b3044f2b7aed7b09b27ef5da2a9d47 | Tauri TD1.06 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): `voices` command lists the provider's voices | pytest 2443 passed, 1 skipped; Exact-head Python CI #797 [43606973444](https://github.com/ekkus93/pdf2audiobook/actions/runs/43606973444) passed on attempt 1 | None |
| 2026-11-14 | a7b81516e196d1646cc8f9842921aa38a99911cf | Tauri TD1.07 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): `thumbnail` command | pytest 2450 passed, 1 skipped; Exact-head Python CI #798 [43607182172](https://github.com/ekkus93/pdf2audiobook/actions/runs/43607182172) passed on attempt 1 | None |
| 2026-11-14 | 272559f8276a8e57301afc7e7f219c58652a0457 | Tauri TD1.08 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): README and maintainer guide describe the new CLI outputs | docs only; Exact-head Python CI #799 [43607226126](https://github.com/ekkus93/pdf2audiobook/actions/runs/43607226126) passed on attempt 1 | None |
| 2026-11-14 | 8f8a7e473d309d25bd42adc591e6ec6dbab827e4 | Tauri TD2.01 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): Tauri 2 + React + TypeScript scaffold in `desktop/` | local desktop checks (lint, typecheck, Vitest, build, fmt, clippy, cargo test) pass; empty window opened under Xvfb; Exact-head Python CI #801 [43607616011](https://github.com/ekkus93/pdf2audiobook/actions/runs/43607616011) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 946ddd9ef0c4f60ae492cb0dcf89d4169f8e1f46 | Tauri TD2.02 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): `desktop/` kept out of the Python packages, Ruff and mypy | pytest 2453 passed, 1 skipped; CI packaging check for `desktop/`; Exact-head Python CI #802 [43607833526](https://github.com/ekkus93/pdf2audiobook/actions/runs/43607833526) passed on attempt 1 | None |
| 2026-11-14 | 88f3c599666fd1eab88406d10b1479323c5aa8f5 | Tauri TD2.03 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): app and CLI versions must match | pytest 2458 passed, 1 skipped; Exact-head Python CI #803 [43608025888](https://github.com/ekkus93/pdf2audiobook/actions/runs/43608025888) passed on attempt 1 | None |
| 2026-11-14 | 94de70ca8142e146938f779d0930de0f842e39df | Tauri TD2.04 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): desktop README, linked from the main README | deb and AppImage builds and npm ci checked; Exact-head Python CI #804 [43608326670](https://github.com/ekkus93/pdf2audiobook/actions/runs/43608326670) passed on attempt 1 | None |
| 2026-11-14 | 3ab14c122ac89447db8a944f5a8d59097235e22c | Tauri TD3.01 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): locate and confirm the CLI | cargo test 11 passed; fmt and clippy clean; Exact-head Python CI #807 [43608955476](https://github.com/ekkus93/pdf2audiobook/actions/runs/43608955476) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 7115a8b0285cda590b74493878b285513d77ed5a | Tauri TD3.02 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): typed requests to CLI argument vectors | cargo test 34 passed, opt-in real-CLI test passed; Exact-head Python CI #808 [43608974129](https://github.com/ekkus93/pdf2audiobook/actions/runs/43608974129) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | ee2a92dc71362c5ebdc8ebe60b8feea4b025c75e | Tauri TD3.03 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): parse CLI results and JSON errors | cargo test 42 passed; Exact-head Python CI #809 [43609044424](https://github.com/ekkus93/pdf2audiobook/actions/runs/43609044424) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 62c153942b34dca1b5c1b15324ba0b175cce0cee | Tauri TD3.04 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): one write-capable command per workspace | cargo test 49 passed; Exact-head Python CI #810 [43609098083](https://github.com/ekkus93/pdf2audiobook/actions/runs/43609098083) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 108780a0ff8673ae21582777b84562073ee32a1c | Tauri TD3.05 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): environment passthrough, password variable names only | cargo test 54 passed; Exact-head Python CI #811 [43609143809](https://github.com/ekkus93/pdf2audiobook/actions/runs/43609143809) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 0a4a732eb53c290aa2bf168c9c0e3dc8fb15cc19 | Tauri TD4.01 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): JSON Schemas for the CLI outputs | all 15 validated against real CLI output; Exact-head Python CI #813 [43609354757](https://github.com/ekkus93/pdf2audiobook/actions/runs/43609354757) passed on attempt 1 | None |
| 2026-11-14 | f0e2ab4bced3963108d9fce66fdbcc338726af39 | Tauri TD4.02 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): real CLI output checked against the contracts | pytest 2473 passed, 1 skipped; Exact-head Python CI #814 [43609557856](https://github.com/ekkus93/pdf2audiobook/actions/runs/43609557856) passed on attempt 1 | None |
| 2026-11-14 | a5d5ddbf4243d4713f774e91b20174456cbdbfa7 | Tauri TD4.03 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): bridge fixtures checked against the contracts | cargo test 59 passed; Exact-head Python CI #815 [43609697528](https://github.com/ekkus93/pdf2audiobook/actions/runs/43609697528) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 0ec5846acacd50c7e58a141bd836757a59bc373c | Tauri TD5.00 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): Material 3 design foundation | 122 frontend tests; build and dev window checked; Exact-head Python CI #817 [43610399942](https://github.com/ekkus93/pdf2audiobook/actions/runs/43610399942) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 1f4bf43c673614e1aca14ae5bcd9985615eabf8a | Tauri TD5.01 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): `doctor --check-llm` reports the served Ollama context | pytest 2479 passed, 1 skipped; real Ollama check; Exact-head Python CI #818 [43610721251](https://github.com/ekkus93/pdf2audiobook/actions/runs/43610721251) passed on attempt 1 | None |
| 2026-11-14 | 0769bb4bb9371a0ed6e6a0b349c01bc00bf1efcf | Tauri TD5.02 (docs/PDF2AUDIOBOOK_TAURI_TODO.md) (partial): inspect shows source and review state | pytest 2479 passed, 1 skipped; Exact-head Python CI #819 [43610927673](https://github.com/ekkus93/pdf2audiobook/actions/runs/43610927673) passed on attempt 1 | None |
| 2026-11-14 | 3c5870fdfcd917820904e15a577506cfdca34b74 | Tauri TD5.01/TD5.02 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): bridge commands, app settings, library scan | cargo test 74 passed; Exact-head Python CI #820 [43612250270](https://github.com/ekkus93/pdf2audiobook/actions/runs/43612250270) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | eeafb686e7b3a1e389d48c3be497800f6c1f8772 | Tauri TD5.01 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): Setup and Library screens | 161 frontend tests; real-app screenshots; Exact-head Python CI #821 [43612258477](https://github.com/ekkus93/pdf2audiobook/actions/runs/43612258477) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 4e14283c93a428372ab3d94eda7cd600cfce6220 | Tauri TD5.02 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): Library screen with Details | 162 frontend tests, cargo test 74 passed; Exact-head Python CI #823 [43612519881](https://github.com/ekkus93/pdf2audiobook/actions/runs/43612519881) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | c2c15bb94edca866599c6208ac2ab6f2b13baed5 | Tauri TD5.03 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): book page with analysis and conversion options | 197 frontend tests; real-app screenshots; Exact-head Python CI #831 [43623865218](https://github.com/ekkus93/pdf2audiobook/actions/runs/43623865218) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 6f625312b01393c8e0606ba32b3505259dff2324 | Tauri TD6.01-TD6.04 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): run, watch, cancel and shut down long tasks | cargo test 81 passed; real-app stop and quit checked; Exact-head Python CI #832 [43625820043](https://github.com/ekkus93/pdf2audiobook/actions/runs/43625820043) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | ed1e99728d722a4be0e4d97d71479a594d787ea3 | Tauri TD5.04 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): Run screen with progress, Stop and a quit prompt | 210 frontend tests; real conversion in the app; Exact-head Python CI #833 [43625829091](https://github.com/ekkus93/pdf2audiobook/actions/runs/43625829091) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | f728e3e57442f2edfdd1aae973f8c17baa3590fd | Tauri TD6.03 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): offer recovery after a pending update | 212 frontend tests; Exact-head Python CI #835 [43626149718](https://github.com/ekkus93/pdf2audiobook/actions/runs/43626149718) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 0fdc1afd180305c31510286559782db15f8a2ed2 | Tauri TD5.05, TD7.01-TD7.03 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): chapter review in a locked-down window | cargo test 86 passed, 219 frontend tests; real review window opened and closed; Exact-head Python CI #836 [43626595603](https://github.com/ekkus93/pdf2audiobook/actions/runs/43626595603) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | c93643471f29a7cf43902063588780201178a11a | Tauri TD5.06 part (docs/PDF2AUDIOBOOK_TAURI_TODO.md): `edits list --with-text` adds the edit text only on request | pytest 2481 passed, 1 skipped; edits-list contract extended; Exact-head Python CI #837 [43626777117](https://github.com/ekkus93/pdf2audiobook/actions/runs/43626777117) passed on attempt 1 | None |
| 2026-11-14 | 7e9cfab5ae7b3ec5e66474c4596797693d7d6a42 | Tauri TD5.06 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): review pending edits one by one or all at once | 225 frontend tests; real Accept all checked with the CLI; Exact-head Python CI #838 [43627404890](https://github.com/ekkus93/pdf2audiobook/actions/runs/43627404890) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 46d7bb33dad9a083c2424fa6b5e08c070ab61308 | Tauri TD5.07, TD8.01-TD8.03 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): chapters, player, M4B and zip export | cargo test 93 passed, 244 frontend tests; real M4B and zip checked; Exact-head Python CI #840 [43631327843](https://github.com/ekkus93/pdf2audiobook/actions/runs/43631327843) passed on attempt 1 | Desktop checks not yet in CI (TD10.02); the asset scope keeps folders of books opened earlier in the session |
| 2026-11-14 | 27d434f6074b9749dafd29beddc8c4731e10ae47 | Tauri TD5.08 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): settings for the CLI, output folder, default voice and LLM | 274 frontend tests; real save and default voice checked; Exact-head Python CI #841 [43632382414](https://github.com/ekkus93/pdf2audiobook/actions/runs/43632382414) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 4512c39b8770f35e74f8b5a4c9d1aed516915544 | Tauri TD5.09 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): an action for each engine error reason | 300 frontend tests incl. every reason; budget-show contract; real lock wait checked; Exact-head Python CI #842 [43633181030](https://github.com/ekkus93/pdf2audiobook/actions/runs/43633181030) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | 1c0ecc967e8fa63c5f16440bf82bc5e64b268260 | Tauri TD9.01-TD9.04 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): narrow permissions, CSP, content-free log, no network | pytest 2489 passed, 1 skipped; cargo test 101+7 passed; 303 frontend tests; release app run with IPv4/IPv6 refused; Exact-head Python CI #843 [43634551329](https://github.com/ekkus93/pdf2audiobook/actions/runs/43634551329) passed on attempt 1 | Desktop checks not yet in CI (TD10.02) |
| 2026-11-14 | b99e4bb852e5d3e4d032caba1f0e699c2ab14ff4 | Tauri TD10.01 fix (docs/PDF2AUDIOBOOK_TAURI_TODO.md): Back to the book shows the book as the run left it | 316 frontend tests; App test fails without the fix; Exact-head Python CI #845 [43637832735](https://github.com/ekkus93/pdf2audiobook/actions/runs/43637832735) passed on attempt 1 | None |
| 2026-11-14 | a3e270843871d0267793c57b95fa1eadad7fb66f | Tauri TD10.01, TD10.02 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): end-to-end walkthrough and Desktop CI workflow | walkthrough passed locally twice; Desktop CI #1 [43637961235](https://github.com/ekkus93/pdf2audiobook/actions/runs/43637961235) failed at npm ci (npm 11 lock file); Exact-head Python CI #846 [43637961245](https://github.com/ekkus93/pdf2audiobook/actions/runs/43637961245) passed on attempt 1 | Desktop CI failing (fixed in later commits) |
| 2026-11-14 | 66f09811d1ce6a625578219a20e1800314f88663 | Tauri TD10.02 fix (docs/PDF2AUDIOBOOK_TAURI_TODO.md): lock file written with npm 10 for CI | Desktop CI #2 [43638257820](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638257820) failed in two frontend tests on Node 22; Exact-head Python CI #847 [43638257842](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638257842) passed on attempt 1 | Desktop CI failing (fixed in 9b03d4e) |
| 2026-11-14 | f443007122faf2a76af80b7b90af58e4b5a4adb8 | Tauri TD10.05 fix (docs/PDF2AUDIOBOOK_TAURI_TODO.md): child processes get the host environment inside an AppImage; CI walks through the AppImage | cargo test 104 passed; Desktop CI #3 [43638448307](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638448307) failed in the same two Node 22 tests; Exact-head Python CI #848 [43638448299](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638448299) passed on attempt 1 | Desktop CI failing (fixed in 9b03d4e) |
| 2026-11-14 | 9b03d4eefe28463bc3dffe6a5d5b4c9245cad451 | Tauri TD10.01-TD10.04 (docs/PDF2AUDIOBOOK_TAURI_TODO.md): Desktop CI passes, unsigned AppImage and .deb artifacts | 316 frontend tests on Node 22 and 24; Desktop CI #4 [43638534169](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638534169) passed every step incl. both walkthroughs; Exact-head Python CI #849 [43638534189](https://github.com/ekkus93/pdf2audiobook/actions/runs/43638534189) passed on attempt 1 | macOS and Windows installers wait for O2; signing waits for O4 |
