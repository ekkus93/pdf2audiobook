# PDF2Audiobook Self-Contained Desktop App Specification

**Status:** Decided 2026-11-26; in progress
**Date:** 2026-11-26
**Companion:** [Self-Contained App TODO](PDF2AUDIOBOOK_SELF_CONTAINED_APP_TODO.md)
**Baseline:** `master` at `e1241c0`
**Supersedes:** [Desktop App Specification](PDF2AUDIOBOOK_TAURI_SPEC.md) owner decision O1 and D10.a, and the §1 exclusion of bundling FFmpeg and Tesseract

## 1. Decision

The owner decided on 2026-11-26 that the desktop app must be self-contained: a user installs the app and converts a book, with no terminal, no Python, no `uv` and no system packages. O1 ("require an installed CLI") is reversed.

O1 rejected bundling because the environment with the `kitten` extra measured 6.1 GB. That size comes from PyTorch and its NVIDIA and Triton packages (about 4.8 GB together, measured 2026-11-26), which only Kitten 2 and the speech recognizers need. The default voice (Kitten 0.8 `mini`) runs on ONNX Runtime (63 MB). So the app ships a small engine for the default path and downloads the heavy parts only when the user chooses a feature that needs them.

## 2. What "self-contained" means

After installing the AppImage or `.deb` on a clean Linux machine with no network:

- The app starts, finds its engine, and the Setup screen shows nothing that needs attention.
- The user can add a text PDF or a scanned English PDF and convert it to MP3s with the default voice, then play it and pack an M4B.
- Nothing asks the user to open a terminal.

With network access, from inside the app and with the user's consent:

- **Voice cloning and Kitten 2** (and its temperature setting) become available after one download.
- **Audio checking** with Whisper becomes available after one download.
- More OCR languages can be added.

Still optional and outside the app: Ollama for LLM help, and Piper. The app works fully without them and says so plainly.

## 3. Choices

These were settled with the decision, so the work can proceed. Each can be revisited, with a dated note here.

| # | Choice | Reason |
|---|---|---|
| C1 | Bundle a relocatable CPython (python-build-standalone, as `uv python` installs it) and a relocatable virtual environment built from `uv.lock`, in the app's resources. | It runs the same code and pinned packages as the CLI. A frozen executable (PyInstaller) would fight the dynamic imports in `kittenml` and `phonemizer`. |
| C2 | The bundled environment has the core dependencies plus the Kitten 0.8 ONNX path, without PyTorch. | Keeps the installer small (target in C8). |
| C3 | Bundle the `mini` model files, so the first conversion works offline. | Today `kittenml` downloads them from Hugging Face on first use. |
| C4 | Heavy features are **add-ons**, installed on demand into the user's data directory, never into the app image (an AppImage is read-only). Add-on packages are pinned and hash-checked from the lock file; model files keep their existing pinned, hash-checked fetches. | Matches how `tts fetch kitten2` and `asr fetch` already work, and keeps the base download small. |
| C5 | Add-ons use CPU PyTorch. | The CUDA build is about 3 GB more. GPU support is a later add-on option. |
| C6 | Bundle FFmpeg (an LGPL static build) and English OCR data. Other OCR languages are add-ons (plain data files). (Amended 2026-11-26: OCR runs through PyMuPDF's built-in Tesseract, which needs only the language data, so the Tesseract program is not bundled.) | Both are needed for the default path. |
| C7 | The app prefers its bundled engine. Today's discovery (a configured path, `PATH`, a `uv` checkout) stays available behind a developer setting. | Developers keep working against a checkout; users never see version mismatches. |
| C8 | Size budget: the compressed installer at most 400 MB, the installed app at most 1 GB, before add-ons. Measured in task 1; going over needs a dated note here. | A reasonable desktop download that the measured parts fit inside. |
| C9 | Licences: the app stays Apache-2.0. Bundled third-party components (CPython, FFmpeg LGPL, Tesseract, espeak-ng through `espeakng-loader`, ONNX Runtime, the model files) ship unmodified, as separate programs and data, with their licence texts and source offers in the app's About screen and package. | espeak-ng is GPL-3; shipping it alongside, not linked into the Rust app, keeps the app's licence. |
| C10 | Linux only (AppImage and `.deb`), as now. | Platform scope is unchanged (O2). |

## 4. Requirements

### SC1: The bundled engine

- A build script produces `engine/` for the app's resources: a relocatable CPython and environment with pdf2audiobook and its core dependencies at the versions in `uv.lock`, plus the ONNX path of `kittenml` and its runtime needs (ONNX Runtime, `phonemizer`, `espeakng-loader`, `soundfile`, and what else the measured import set requires), without PyTorch.
- `kittenml==0.9.6` declares PyTorch as a dependency. The bundle installs `kittenml` without its declared dependencies and adds the measured set explicitly. A test in the bundled environment imports the CLI and synthesizes a sample with `mini`, so a missing package fails the build.
- The `mini` model files are included and found without network access.
- The engine is invoked as `engine/bin/pdf2audiobook`. It works when the app is moved or mounted at a different path (AppImage).

**Acceptance:** On a clean container without Python, `uv`, FFmpeg or Tesseract, and without network, `engine/bin/pdf2audiobook doctor --json` reports FFmpeg, Tesseract and Kitten ready, and `convert` of a synthetic fixture with `--no-llm` produces playable MP3s. Sizes are recorded against C8.

### SC2: Finding the engine

- A new engine source, `bundled`. When the app has one and the developer setting is off, it is the only engine used. With the developer setting on, the configured path, `PATH` and the `uv` checkout are tried first and the bundled engine last; without a bundled engine (a development build) the old order applies. (Amended 2026-11-26: the draft said "tried first" without saying where the developer setting puts it.) A development build can point at a locally built engine with `PDF2AUDIOBOOK_ENGINE_DIR`.
- The app starts the bundled engine as `engine/bin/python3 -I -m pdf2audiobook`: isolated mode ignores the user's `PYTHON*` variables and user site-packages, and needs no shell.
- The bundled engine's version always equals the app's, so the version-mismatch path cannot occur for it.
- The engine runs with its own `PATH` additions (bundled FFmpeg and Tesseract first), its own Tesseract data directory, and the add-on directory (SC3). It never depends on the user's shell environment.

**Acceptance:** Rust tests for the order and the developer setting; a test that the bundled engine is chosen even when another `pdf2audiobook` is on `PATH`.

### SC3: Add-ons

- Two add-ons: **Voice cloning and Kitten 2** (full `kittenml` dependencies with CPU PyTorch, then the Kitten 2 model files) and **Audio checking** (Whisper with CPU PyTorch, then a Whisper model). They share one PyTorch. (Amended 2026-11-26: audio checking confirms a flag only when two of its three recognizers agree, so the Audio checking add-on installs all three, Whisper, wav2vec 2.0 and Vosk, with their models.)
- Each is offered where it is needed (choosing Clone a voice, Kitten 2, or an audio check) and on the Setup screen. Before downloading, the app shows what will be downloaded, from where, its size and where it goes, and asks for consent, as `tts fetch` does today.
- Packages come from a pinned, hash-locked list generated from `uv.lock` (`desktop/engine/addons.lock.json`, by `desktop/scripts/addon_lists.py`), installed with the bundled CPython's own pip (`--require-hashes --no-deps --only-binary :all:`) into `$XDG_DATA_HOME/pdf2audiobook/addons/<engine version>/` (or `~/.local/share/…`). Model files keep the existing pinned fetches into the cache. (Amended 2026-11-26: the draft named a bundled `uv`; pip is already in the bundled interpreter, so no further binary ships.)
- Packages are grouped into components by the set of add-ons that need them, each installed into its own folder, so a package both add-ons use (PyTorch among them) is installed once and removing one add-on keeps what the other needs. CUDA, NVIDIA and Triton packages are left out (C5).
- Packages that publish only source (`openai-whisper`, `antlr4-python3-runtime`) are built into wheels during the engine build from their hashed archives and ship inside the engine, so users never build anything.
- Downloads show progress, can be cancelled, resume or restart cleanly, and verify hashes. A failed or partial add-on is never used. An add-on can be removed from Settings.
- The engine adds the add-on directory to its import path only when it is complete and matches the engine version. After an app update, add-ons for an older engine are offered for reinstall, not used.

**Acceptance:** Tests with a local package index and fake model files cover consent, progress, cancel, a hash mismatch, a partial install, removal and the version check. A manual real-network run installs both add-ons, clones a voice and runs an audio check; it is recorded in the ledger.

### SC4: FFmpeg and Tesseract

- A pinned FFmpeg static build (LGPL) and Tesseract with `eng` data ship in the app, checked by hash at build time.
- The OCR language setting lists bundled and installed languages. Another language's `.traineddata` is an add-on download (pinned, hash-checked) into the add-on directory. (Amended 2026-11-26: the catalog pins tessdata_fast 4.1.0's files by size and git blob SHA-1, the hash GitHub's tree API reports, since no SHA-256 list is published; a writable folder holds the added languages and copies of the bundled ones, because PyMuPDF reads all languages from one folder.)

**Acceptance:** The SC1 container test converts a scanned (image-only) synthetic page with OCR. A test installs a fake language file and `doctor` reports it.

### SC5: Setup without terminals

- In the normal (non-developer) mode, no Setup row, dialog or error shows a shell command.
- Every row that needs attention has an in-app action: install an add-on, add an OCR language, or open Settings.
- LLM help is optional. When Ollama is not reachable, the row says so as optional information, and new books start with the LLM off, instead of a "needs attention" row. The user can still turn it on per book.
- Piper stays an optional row with no command.

**Acceptance:** Component tests show no command text in normal mode for every `doctor` state, and the LLM row and book default with Ollama unreachable.

### SC6: Visible voice choice

- In Book options and Speak again, the voice source is a visible choice (segmented buttons: **Built-in voice** · **Clone a voice**), not an item inside a dropdown. (Amended 2026-11-27: two filter chips in a labelled group, since Material Web's segmented button exists only in its unstable `labs` folder; the shared `CloneControls` also gives Settings → Voice defaults the same choice.) "Use shared configuration" remains the default state, shown as neither button pressed, with a line naming what the configuration uses.
- Choosing Clone a voice before the add-on is installed offers the add-on (SC3) in place.
- The Kitten 2 temperature slider keeps its rule (desktop temperature spec DT3).

**Acceptance:** Component tests for each state and the add-on offer.

### SC7: Packaging and CI

- Desktop CI builds the engine (SC1), bundles it with FFmpeg and Tesseract, builds the AppImage and `.deb`, and records their sizes.
- A CI job runs the SC1 acceptance in a clean container with networking disabled, against the built AppImage's engine.
- The end-to-end walkthrough runs against the bundled engine instead of the checkout.
- Licence texts and source offers for every bundled component are included and shown in the app (C9).

**Acceptance:** Green Desktop CI with the clean-container job; sizes in the ledger against C8.

### SC8: Documentation

- `desktop/README.md` and the getting-started guide describe installing the app with no other steps, the add-ons, and the developer setting. The Tauri specification gets a dated note pointing here for O1 and D10.a.
- The maintainer guide describes the engine build, how to update the pinned FFmpeg, Tesseract and add-on lists, and the size budget.

## 5. Privacy

Add-on and language downloads send no book content, and their errors and logs carry no paths or content, as today. Consent is asked each time something is downloaded. The bundled engine keeps all of the CLI's privacy rules.

## 6. Out of scope

- macOS and Windows installers (O2), signing (O4) and auto-update.
- Bundling Ollama or an LLM model, and bundling Piper.
- GPU PyTorch for add-ons (a later option, C5).
- Changing the CLI's own install path: the CLI stays installable with `uv` for command-line users.

## 7. Risks

- **The ONNX path's real import set.** `kittenml` may import PyTorch-dependent modules on the `mini` path. Task 1 measures it before anything else depends on it; if it does, the fallback is CPU PyTorch in the base engine (about 0.8 GB), checked against C8.
- **Relocatability.** Some wheels embed absolute paths. The SC1 container test runs the engine from a path different from the build path.
- **glibc.** The bundled CPython and wheels need a minimum glibc; the oldest supported distribution is recorded with the build.
