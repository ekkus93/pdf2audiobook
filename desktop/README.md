# pdf2audiobook desktop app

A desktop app for [pdf2audiobook](../README.md), built with [Tauri 2](https://tauri.app), React and
TypeScript. Every book operation runs the `pdf2audiobook` command-line tool, and the installers
carry their own copy of it: a built-in engine with Python, FFmpeg, English OCR data and the default
voice. Nothing else needs installing, and converting a book needs no network. The design and
requirements are in [`docs/PDF2AUDIOBOOK_TAURI_SPEC.md`](../docs/PDF2AUDIOBOOK_TAURI_SPEC.md) and
the [Self-Contained App Specification](../docs/PDF2AUDIOBOOK_SELF_CONTAINED_APP_SPEC.md); progress
is tracked in [`docs/PDF2AUDIOBOOK_TAURI_TODO.md`](../docs/PDF2AUDIOBOOK_TAURI_TODO.md) and
[`docs/PDF2AUDIOBOOK_SELF_CONTAINED_APP_TODO.md`](../docs/PDF2AUDIOBOOK_SELF_CONTAINED_APP_TODO.md).

**Status:** in development. Linux only for now; builds are unsigned.

## Installing

Download the AppImage or the `.deb` from a Desktop CI run (the `pdf2audiobook-desktop-linux-unsigned`
artifact). Both need Ubuntu 22.04 or a Linux of the same age or newer, on x86-64.

- **AppImage** (about 260 MB): make it executable and run it. No installation and no FUSE
  needed (set `APPIMAGE_EXTRACT_AND_RUN=1` where FUSE is missing).
- **`.deb`** (about 160 MB, 470 MB installed): `sudo apt install ./pdf2audiobook_*-unsigned.deb`.
  It uses the system's WebKitGTK, which is why it is smaller.

Books go to `audiobooks` in your home folder unless you choose another folder in Settings. The app
needs no Python, `uv`, FFmpeg or Tesseract on the computer. Optional features are
add-ons the app downloads when you choose them (see [Add-ons and OCR
languages](#add-ons-and-ocr-languages)); an LLM for chapter analysis is optional too (Ollama, set
up separately).

**Licence.** pdf2audiobook's own code is Apache-2.0. The installers also carry PyMuPDF (AGPL-3.0)
and GPL components such as espeak-ng in the built-in engine, so the app as distributed is under
the GNU AGPL 3.0 ([text](licenses/AGPL-3.0.txt)). Settings → About says so and lists every
component inside the app with its licence: the engine's, and the Rust crates and npm packages
compiled into the app. Each Desktop CI build uploads `pdf2audiobook-<version>-source.tar` with
its installers: this repository at that commit and the source of every copyleft component.

## Add-ons and OCR languages

Two features need large downloads, so they are add-ons rather than part of the installer. The app
offers each one where it is needed (choosing *Clone a voice*, or the audio check), and lists both
in **Settings → Add-ons and OCR languages** with *Install…* and *Remove*.

| Add-on | For | Download |
|---|---|---|
| Voice cloning and Kitten 2 | Cloning a voice from a recording, and the larger Kitten 2 voices | about 3.2 GB: packages, including CPU PyTorch (no graphics card needed), and the Kitten 2 model |
| Audio checking | The three speech recognizers the audio check uses (Whisper, Wav2Vec2, Vosk) | about 3.2 GB: packages, including CPU PyTorch, and the three models |

Packages the two share, PyTorch among them, are downloaded once. Before downloading, the app says
what it will fetch, from where and how much. While it installs, the dialog shows each stage (packages, then model
files) with a progress bar, and **Stop** ends it: parts that finished installing are kept, so installing again
continues from there, and nothing half-installed is left. Every package is checked against the hash pinned in
the app (`engine/addons.lock.json`, generated from `uv.lock`), and the models keep their pinned,
hash-checked downloads. Add-ons go in `~/.local/share/pdf2audiobook/addons/<version>/` (under
`$XDG_DATA_HOME` when set), for that app version only; after an update the app says to install them
again. No book text is sent anywhere.

English OCR data is built in. **OCR languages** adds others (Tesseract's `tessdata_fast` files,
1–15 MB each, checked against pinned hashes) and removes the ones you added.

## Requirements

To build or develop the app (using it needs none of this):

| What | Version | Notes |
|---|---|---|
| Rust | 1.96.0 | Pinned in `rust-toolchain.toml`; `rustup` installs it on first use, with `rustfmt` and `clippy`. |
| Node.js | 22 or newer | `.nvmrc` pins 22, matching CI. `nvm use` picks it up. |
| Tauri's Linux libraries | WebKitGTK 4.1 and others | See below. |
| uv | 0.12.9 | Builds the built-in engine (see [Building an installer](#building-an-installer)). |
| A C compiler and `make` | | Builds FFmpeg for the engine; `build-essential` provides both, and the static C library. |

On Ubuntu 22.04 or newer, install Tauri's system libraries with:

```bash
sudo apt install pkg-config libwebkit2gtk-4.1-dev libsoup-3.0-dev \
  libayatana-appindicator3-dev librsvg2-dev libssl-dev libgtk-3-dev \
  build-essential file patchelf libxdo-dev gstreamer1.0-plugins-base gstreamer1.0-plugins-good
```

The AppImage build bundles these GStreamer plugins, so they must be installed before building
(see [Building an installer](#building-an-installer)). CI installs these GStreamer packages too.

### A development engine

`npm run tauri dev` has no built-in engine, so it runs a CLI you install, as before. Switch on
**Settings → Engine → Use a development engine**; the app then looks for a configured path, then
`pdf2audiobook` on `PATH`, then a `uv` checkout, then the built-in engine. Install the CLI from
the repository root with:

```bash
uv tool install ".[kitten]"   # provides `pdf2audiobook` on PATH
```

For the audio check, install the speech recognizers too, with `uv tool install ".[kitten,asr]"`.
To try a development build with a built engine instead, set `PDF2AUDIOBOOK_ENGINE_DIR` to the
engine folder (`PDF2AUDIOBOOK_ENGINE_DIR=$PWD/engine-dist/engine npm run tauri dev`).
With the developer setting off, the app uses only its built-in engine; an installer whose engine
is damaged says to reinstall the app.

## Checking the audio

The audio check is optional and off by default; see
[`docs/PDF2AUDIOBOOK_AUDIO_VERIFICATION_SPEC.md`](../docs/PDF2AUDIOBOOK_AUDIO_VERIFICATION_SPEC.md)
and the [audio verification guide](../docs/guides/audio-verification.md).

- **Before converting:** switch on *Check the new audio with speech recognition* in the book's
  options (`convert --verify-audio`). The check runs after conversion, as part of the same run.
- **Afterwards:** *Audio check → Verify existing audio* checks every converted chapter
  (`verify-audio`), as a run of its own on the Run page; stopping it keeps the chapters already
  checked and never touches audio.
- **Speech recognizers:** the panel shows which of Whisper, Wav2Vec2 and Vosk are ready
  (`asr list`). *Download recognizers…* lists each model's size and folder and, when you agree,
  has the CLI download and check them (`asr fetch --yes`); the app itself still makes no network
  request. With the built-in engine, *Install audio checking…* installs the [audio checking
  add-on](#add-ons-and-ocr-languages) instead; a development engine needs the `asr` extra
  ([above](#a-development-engine)).
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

`E2E_BUNDLED=1`, with `E2E_APP` set to an AppImage that carries the engine, runs it as a user
would: no CLI is configured, so the app must find its built-in engine. The stand-in recognizers
and voice cloner can't be used then, so it converts with real speech from the bundled voice,
checks that the audio check offers its add-on with no terminal command, and opens About's
licence lists, the AGPL statement and the app's own libraries.

The "Desktop CI" workflow (`.github/workflows/desktop.yml`) runs all of the above on Ubuntu
22.04, builds the engine and the AppImage and `.deb` with it, runs the clean-machine check, walks
through the build (with `E2E_CLONE=1`) and the AppImage (with `E2E_BUNDLED=1`), and uploads the
installers as the `pdf2audiobook-desktop-linux-unsigned` artifact.

The Python side has its own checks; see
[development and validation](../docs/guides/development.md#linting-type-checking-and-tests).
`tests/test_desktop_versions.py` there fails if this app's version differs from `pyproject.toml`,
so change the version in `package.json`, `package-lock.json`, `src-tauri/Cargo.toml` and
`src-tauri/tauri.conf.json` together with it.

## Configuration

The app creates its preferences file on first startup and, after finding the CLI, runs
`pdf2audiobook config init --json` to create any missing shared TOML config. Existing files
are preserved. No models are downloaded by initialization.

Open **Settings → CLI configuration** to edit the shared file. Saving validates the draft
with the CLI, keeps comments, and replaces the file atomically. An invalid draft or a file
changed externally is not saved. **Reload from disk** discards the draft and loads the latest
file. The effective-settings table shows environment overrides; app preferences above it
remain separate. See the [configuration guide](../docs/guides/configuration.md).

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

From the repository root:

```bash
uv run --no-project python desktop/scripts/build_engine.py desktop/engine-dist   # the built-in engine
python3 desktop/scripts/smoke_engine.py desktop/engine-dist/engine              # offline smoke test
(cd desktop && npm run tauri build -- --bundles appimage,deb)                   # the app, without the engine
python3 desktop/scripts/package_engine.py desktop/engine-dist/engine            # add the engine; prints sizes
bash desktop/scripts/clean_machine_check.sh desktop/src-tauri/target/release/bundle/appimage/*.AppImage
uv run --no-project python desktop/scripts/source_archive.py desktop/engine-dist/engine \
  --output desktop/src-tauri/target/release/bundle/source                        # the source archive
```

- **The engine** (`build_engine.py`, about 470 MB in `desktop/engine-dist/engine`, ignored by
  git): Python 3.11 (python-build-standalone, as `uv` installs it), the CLI and its locked packages, Kitten's ONNX voice path without
  PyTorch, FFmpeg built from source with only what the engine uses, English OCR data, the default
  voice model, the add-on lists and the licence notices. Everything is pinned in `uv.lock` and
  `engine/pins.json` and checked by hash; downloads and the FFmpeg build are kept in
  `tmp/engine-cache` (`--cache`). The first build takes a few minutes, later ones about a minute.
- **The smoke test** runs the engine with an empty environment and, where `unshare` allows, no
  network: `doctor`, a text PDF and a scanned page to MP3s, an M4B, and every other use of FFmpeg.
- **Packaging** (`package_engine.py`): Tauri's AppImage step runs `linuxdeploy`, which rewrites the
  library paths of every program file in the image, so the app is bundled without the engine and
  this script adds it afterwards, unchanged, to `usr/lib/pdf2audiobook/engine` in both installers.
  It also adds the app's own licence notices (`app_notices.py`: the app as distributed, then every
  crate `cargo tree` links into the Linux build and every non-development npm package, with their
  licence texts) at `usr/lib/pdf2audiobook/licenses`. It fails if an installer is over the size
  budget (400 MB compressed, 1 GB installed).
- **The clean-machine check** runs the smoke test from inside the AppImage in a stock Ubuntu 22.04
  container with no network, so nothing from the build machine can help. It needs Docker.
- **The source archive** (`source_archive.py`, about 130 MB): `git archive HEAD` plus the source
  of every copyleft component in the engine and the app (FFmpeg, LAME, espeak-ng, the GPL, AGPL
  and MPL Python packages as their `uv.lock` sdists, and the MPL crates), each checked by hash,
  and `SOURCES.json` listing them. It stops if a copyleft component has no pinned source, or if
  tracked files have uncommitted changes, since the archive would not match the build.

The installers are written to `src-tauri/target/release/bundle/deb/` and
`src-tauri/target/release/bundle/appimage/`. The first AppImage build downloads `linuxdeploy`
from GitHub. Without the engine the AppImage is about 95 MB in CI (more on newer distributions),
since it bundles WebKitGTK and GStreamer (`bundleMediaFramework` in `tauri.conf.json`). Without GStreamer's audio plugins
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
| `scripts/` | Icon subsetting, the no-network launcher, and building, packaging and checking the built-in engine |
| `engine/` | The engine's pins (`pins.json`), the add-on package lists (`addons.lock.json`) and the OCR language catalog (`tessdata.json`) |
| `contracts/` | JSON schemas for the CLI results the app reads |

## Local voice cloning

Book options and **Speak again** offer **Voice source → Clone a voice** (KittenTTS 2). With the
built-in engine, the first time it offers the [voice cloning add-on](#add-ons-and-ocr-languages).
Use native pickers for a 5–30 second WAV/FLAC/MP3 and an optional transcript file, or type
its transcript. The CLI performs validation and local inference. Model setup shows pinned
sources, size and destination before an explicit, cancelable download. Settings can apply
voice defaults to the shared TOML editor; only **Save configuration** persists them.
Typed transcripts stay transient and use private files only while a CLI child runs.
See the [voice cloning guide](../docs/guides/voice-cloning.md) and
[release acceptance ledger](../docs/PDF2AUDIOBOOK_VOICE_CLONING_TODO.md).

For the native clone walkthrough, use `E2E_CLONE=1 bash e2e/isolated.sh` from `desktop/`,
with the usual `E2E_APP` and driver paths. The helper creates a separate D-Bus session, Xvfb
screen, runtime directory and GTK file chooser; it preserves the host desktop's session.
It needs `dbus-run-session`, `xvfb-run`, `xdotool`, FFmpeg, `x11-utils`,
`xdg-desktop-portal` and `xdg-desktop-portal-gtk`. CI runs it for the executable and AppImage.
Screenshots include dark and light clone controls; all reference/speech data are synthetic.
