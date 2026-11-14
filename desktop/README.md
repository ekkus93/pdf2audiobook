# pdf2audiobook desktop app

A desktop app for [pdf2audiobook](../README.md), built with [Tauri 2](https://tauri.app), React and
TypeScript. It is a front end only: every book operation runs the `pdf2audiobook` command-line
tool, which must be installed separately. The design and requirements are in
[`docs/PDF2AUDIOBOOK_TAURI_SPEC.md`](../docs/PDF2AUDIOBOOK_TAURI_SPEC.md), and progress is tracked
in [`docs/PDF2AUDIOBOOK_TAURI_TODO.md`](../docs/PDF2AUDIOBOOK_TAURI_TODO.md).

**Status:** in development. Linux only for now; builds are unsigned.

## Requirements

| What | Version | Notes |
|---|---|---|
| Rust | 1.96.0 | Pinned in `rust-toolchain.toml`; `rustup` installs it on first use, with `rustfmt` and `clippy`. |
| Node.js | 22 or newer | `.nvmrc` pins 22, matching CI. `nvm use` picks it up. |
| Tauri's Linux libraries | WebKitGTK 4.1 and others | See below. |
| The pdf2audiobook CLI | 0.1.x | Its major and minor version must match the app's. |

On Ubuntu 22.04 or newer, install Tauri's system libraries with:

```bash
sudo apt install pkg-config libwebkit2gtk-4.1-dev libsoup-3.0-dev \
  libayatana-appindicator3-dev librsvg2-dev libssl-dev libgtk-3-dev \
  build-essential file patchelf libxdo-dev
```

Install the CLI from a checkout of this repository (the app doesn't bundle Python):

```bash
uv tool install ".[kitten]"   # run in the repository root; provides `pdf2audiobook` on PATH
```

## Development

```bash
cd desktop
npm ci                 # install the exact versions in package-lock.json
npm run tauri dev      # start Vite and open the app window, with hot reload
```

The first `tauri dev` compiles the Rust side, which takes a few minutes; later starts are quick.

## Checks

Run all of these before committing; CI runs the same ones.

```bash
cd desktop
npm run lint           # ESLint, no warnings allowed
npm run typecheck      # TypeScript for the app and for vite.config.ts
npm test               # Vitest component tests (jsdom)
npm run build          # type-check and production build of the frontend

cd src-tauri
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
```

The end-to-end walkthrough (spec D9.d) drives a release build through `tauri-driver`: it adds
the README demo book through the file dialog, analyzes it without the LLM, retitles chapter 1
in review and saves, then converts with `--dry-run` (the app runs the real CLI from this
checkout through a wrapper that adds `--dry-run`, so no speech model is needed). It needs an X
display, `xdotool`, WebKitGTK's `WebKitWebDriver` (`webkit2gtk-driver` on Ubuntu) and
`tauri-driver` (`cargo install tauri-driver --locked`):

```bash
npm run tauri build -- --no-bundle
xvfb-run -s "-screen 0 1280x800x24" npm run e2e   # screenshots go to e2e/artifacts/
```

`E2E_NATIVE_DRIVER`, `E2E_TAURI_DRIVER` and `E2E_APP` point it at other binaries.

The "Desktop CI" workflow (`.github/workflows/desktop.yml`) runs all of the above on Ubuntu
22.04, builds the AppImage and `.deb`, and uploads them as the `pdf2audiobook-desktop-linux-unsigned`
artifact.

The Python side has its own checks (see the main [README](../README.md#linting-type-checking-and-tests)).
`tests/test_desktop_versions.py` there fails if this app's version differs from `pyproject.toml`,
so change the version in `package.json`, `package-lock.json`, `src-tauri/Cargo.toml` and
`src-tauri/tauri.conf.json` together with it.

## Security and privacy

- **Permissions.** The main window may call the app's own commands, listen to its events and
  open the file dialogs, nothing more (`src-tauri/capabilities/default.json`). The review window
  has no permissions at all and may only load the CLI's review page on `127.0.0.1`. Chapter
  audio is read through Tauri's asset protocol, which starts with an empty scope; listing a
  book's chapters allows that book's `audio/` folder only. `src-tauri/tests/permissions.rs`
  fails if a permission, capability, plugin or network client is added.
- **Content Security Policy.** The release build allows only the app's own scripts and styles,
  `data:` images (thumbnails), `blob:` media (the player) and Tauri's IPC and asset protocols;
  no remote origin and no `eval`. `devCsp` adds Vite's dev server and React's refresh preamble
  for `npm run tauri dev` only.
- **Log.** The app writes one JSON line per event (app start, each CLI command, runs, the review
  window) to `pdf2audiobook-desktop.log` in its log folder
  (`~/.local/share/io.github.ekkus93.pdf2audiobook/logs/` on Linux). Each line holds an event
  name, the CLI command's name, its exit code, duration, outcome and `reason` code, never a
  path, title or message. `src-tauri/src/privacy.rs` and `../tests/test_desktop_privacy.py`
  check that marker strings in a book's title, file name and text reach neither the log nor an
  error.
- **No network.** The app makes no network requests; only the CLI does (an LLM server, model
  downloads). To check, run it with IPv4 and IPv6 refused for it and every process it starts:

  ```bash
  python3 scripts/no_network.py -- src-tauri/target/release/pdf2audiobook-desktop
  ```

## Design system

The app uses Google's Material 3 (spec D11) with the Midnight Iris palette.

- **Colours** are generated from two seeds in `src/theme/scheme.ts` at build time (the
  `m3-theme` Vite plugin) into `--md-sys-color-*` variables; never type a colour in by hand.
  `src/theme/scheme.test.ts` checks the result against the table in the spec, and
  `contrast.test.ts` checks WCAG AA contrast for every pairing.
- **Components** come from `@material/web` (pinned; in maintenance mode), each wrapped in a
  small component in `src/ui/`. The rail, app bar, cards, snackbar and player bar are built
  there from the same tokens.
- **Icons** are Material Symbols Rounded, drawn from a 40 KB subset of the 5.4 MB font. To add
  one, put its name in `src/theme/icons.json` (sorted) and run, from `desktop/`:

  ```bash
  uv run --no-project --with fonttools --with brotli python scripts/subset_icons.py
  ```

  This rewrites the font in `src/assets/fonts/` and `src/theme/icons.generated.ts`; commit
  both. The build itself never needs Python.

## Building an installer

```bash
cd desktop
npm run tauri build -- --bundles deb        # Debian/Ubuntu package
npm run tauri build -- --bundles appimage   # portable AppImage
```

The installers are written to `src-tauri/target/release/bundle/deb/` and
`src-tauri/target/release/bundle/appimage/`. A release build takes a few minutes (about 90
seconds for the `.deb` on a 20-core machine). The first AppImage build downloads `linuxdeploy`
from GitHub. The `.deb` is about 2 MB and the AppImage about 77 MB, since it bundles WebKitGTK.
Builds are unsigned for now; CI adds `-unsigned` to the installers' file names (spec D10.d).

## Layout

| Path | What |
|---|---|
| `src/` | React and TypeScript frontend |
| `src-tauri/src/` | Rust: the bridge that runs the CLI, and the Tauri commands the frontend calls |
| `src-tauri/capabilities/` | Permissions the frontend gets; kept to the minimum |
| `src-tauri/tauri.conf.json` | Window, bundle and security settings |
| `scripts/` | Icon subsetting and the no-network launcher |
