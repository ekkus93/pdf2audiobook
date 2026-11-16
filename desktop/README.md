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

For the optional audio check (below), install the speech recognizers too, with
`uv tool install ".[kitten,asr]"`; the app offers to download their models.

## Checking the audio

The audio check is optional and off by default; see
[`docs/PDF2AUDIOBOOK_AUDIO_VERIFICATION_SPEC.md`](../docs/PDF2AUDIOBOOK_AUDIO_VERIFICATION_SPEC.md)
and the main README's [Checking the audio with speech recognition](../README.md#checking-the-audio-with-speech-recognition-optional).

- **Before converting:** switch on *Check the new audio with speech recognition* in the book's
  options (`convert --verify-audio`). The check runs after conversion, as part of the same run.
- **Afterwards:** *Audio check → Verify existing audio* checks every converted chapter
  (`verify-audio`), as a run of its own on the Run page; stopping it keeps the chapters already
  checked and never touches audio.
- **Speech recognizers:** the panel shows which of Whisper, Wav2Vec2 and Vosk are ready
  (`asr list`). *Download recognizers…* lists each model's size and folder and, when you agree,
  has the CLI download and check them (`asr fetch --yes`); the app itself still makes no network
  request. Packages that aren't installed have to be installed with the CLI (above).
- **Results** (`audio-report show`, which loads no model): chapters with no mismatch are only
  counted. For the others the panel shows the verdict, which recognizers voted and whether fewer
  than three did, and each passage the recognizers heard differently: the text around it, the
  expected words, what each recognizer heard, and when. A passage counts only when two
  recognizers agree; one recognizer alone is shown as a disagreement. Results whose audio or text
  changed since the check are marked out of date.
- **Chapters not compared:** a chapter whose text or pronunciations changed since it was spoken, or whose
  MP3 FFmpeg can't read, shows why no comparison was made, and *Speak again…* is the way to check it again.
- **Actions,** none automatic: *Listen* plays the chapter from two seconds before the passage;
  *Sounds right* marks it reviewed (`audio-report dismiss`; *Not reviewed* undoes it) without
  changing any file; *Speak again…* synthesizes only that chapter again with the voice and speed
  you choose (`resynthesize`), keeping its current audio playable until the new audio is ready
  and then in `audio/.backup/`, and checks the new audio; *Correct the text* opens the review
  page, after which *Speak again…* uses the corrected text.

Transcripts and excerpts reach only this panel: never the app log or an error message
(`src-tauri/src/privacy.rs`).

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

CI installs with `npm ci` on Node 22 (npm 10), which rejects a lock file written by npm 11
that leaves out optional platform packages. After changing dependencies with a newer npm,
rewrite the lock with `npx npm@10 install --package-lock-only` before committing.

The end-to-end walkthrough (spec D9.d) drives a release build through `tauri-driver`: it adds
the README demo book through the file dialog, analyzes it without the LLM, retitles chapter 1
in review and saves, then converts with `--dry-run` (the app runs the real CLI from this
checkout through a wrapper that adds `--dry-run`, so no speech model is needed). It then checks
the audio: verifies the book, listens at the passage flagged in chapter 2, marks it reviewed and
speaks the chapter again, after which no chapter is flagged. CI has no speech recognizer models,
so the wrapper sends `asr`, `verify-audio`, `audio-report` and `resynthesize` to
`e2e/fake_asr.mjs`, which answers from the bridge's real-output fixtures, and gives each chapter
a short silent MP3 (`e2e/fixtures/silence.mp3`). It needs an X
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
  audio is read through the app's own `chapter:` protocol (`audio::serve`), which answers only
  the main window and serves only MP3s, by file name, from the `audio/` folder of the book being
  played; playing another book closes the previous one's, while browsing to one doesn't. Tauri's asset protocol is off: its scope can
  only grow, so it would keep every book opened earlier readable.
  `src-tauri/tests/permissions.rs` fails if a permission, capability, plugin or network client
  is added, or if the asset protocol comes back.
- **Content Security Policy.** The release build allows only the app's own scripts and styles,
  `data:` images (thumbnails), `blob:` media (the player), Tauri's IPC and the `chapter:` protocol;
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
from GitHub. The `.deb` is about 2 MB and the AppImage about 93 MB, since it bundles WebKitGTK
and GStreamer (`bundleMediaFramework` in `tauri.conf.json`). Without GStreamer's audio plugins
inside it, the AppImage's page crashed as soon as a chapter played (`autoaudiosink not found`), so
building it needs `gstreamer1.0-plugins-base` and `gstreamer1.0-plugins-good` installed; the
walkthrough plays a chapter in the AppImage to catch this.
Builds are unsigned for now; CI adds `-unsigned` to the installers' file names (spec D10.d).

## Layout

| Path | What |
|---|---|
| `src/` | React and TypeScript frontend |
| `src-tauri/src/` | Rust: the bridge that runs the CLI, and the Tauri commands the frontend calls |
| `src-tauri/capabilities/` | Permissions the frontend gets; kept to the minimum |
| `src-tauri/tauri.conf.json` | Window, bundle and security settings |
| `scripts/` | Icon subsetting and the no-network launcher |
