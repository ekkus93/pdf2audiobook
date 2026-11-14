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

The Python side has its own checks (see the main [README](../README.md#linting-type-checking-and-tests)).
`tests/test_desktop_versions.py` there fails if this app's version differs from `pyproject.toml`,
so change the version in `package.json`, `package-lock.json`, `src-tauri/Cargo.toml` and
`src-tauri/tauri.conf.json` together with it.

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
Builds are unsigned for now.

## Layout

| Path | What |
|---|---|
| `src/` | React and TypeScript frontend |
| `src-tauri/src/` | Rust: the bridge that runs the CLI, and the Tauri commands the frontend calls |
| `src-tauri/capabilities/` | Permissions the frontend gets; kept to the minimum |
| `src-tauri/tauri.conf.json` | Window, bundle and security settings |
