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

## Found while writing the spec and working

- `pdf2audiobook --version` exits 2 with "Missing command" unless a command follows it
  (master at 05ca4c37685325ced177cf06d21de2506fe18cd2). Tracked as TD1.01.
- Local mypy is not clean when the `kitten` extra is installed: `tts/__init__.py:59` reports
  `import-untyped` for `kittenml`, which its `type: ignore[import-not-found]` doesn't cover.
  CI installs only the `dev` extra, where the import is not found and the ignore applies, so CI
  is clean. The TD0.01 baseline result came from mypy's cache. Checks in this TODO therefore run
  mypy as CI does, in an isolated environment without Kitten:
  `uv run --isolated --extra dev mypy --no-incremental --python-version X`. Not fixed here.

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
