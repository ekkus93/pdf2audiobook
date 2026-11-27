# PDF2Audiobook Self-Contained Desktop App TODO

**Status:** In progress, started 2026-11-26
**Date:** 2026-11-26
**Baseline:** `master` at `e1241c0`
**Specification:** [Self-Contained App Specification](PDF2AUDIOBOOK_SELF_CONTAINED_APP_SPEC.md) (SC1–SC8, choices C1–C10)

## Working rules

- Work in the order below. Task 1 decides whether C2 holds; record its measurements before building on it.
- Write each task's tests first and run them against the parent commit, so the failing test IDs are recorded before the fix.
- Use `[x]` only when the implementation exists and its named tests pass. Otherwise mark the item partial in the ledger.
- Conventional Commits (`build`, `desktop`, `ci`, `docs` scopes as they fit), lowercase imperative subject, no body.
- Before each commit: `/verify` for Python changes; for `desktop/` changes, `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test`, `npm run lint`, `npm run typecheck` and `npm test`, checking each command's exit status, not only its counts.
- Check Desktop CI and Python CI after every push. A failed run blocks the next task until it is fixed or explained.
- CI stays offline except package installs and the explicitly pinned downloads the build fetches. Never commit model weights, binaries, generated audio or private paths.

## 1. Measure the slim engine (SC1, C2, C8)

- [x] 1.1 Build a relocatable CPython and environment from `uv.lock` with the core dependencies and `kittenml` without its declared dependencies. Find the smallest added set that lets `mini` synthesize a sample, and record it.
- [x] 1.2 Record the size of the environment, the `mini` model files, FFmpeg and Tesseract with `eng`, against C8. If C2 fails, record the fallback size and amend C2.
- [x] 1.3 Run the engine from a moved path and with network disabled. Record the minimum glibc.

## 2. Engine build (SC1, SC4)

- [x] 2.1 A build script (`desktop/scripts/build-engine.sh` or similar) that produces `engine/` reproducibly from `uv.lock`, with the pinned FFmpeg and Tesseract, hash-checked.
- [x] 2.2 Bundle the `mini` model files and make the engine find them offline.
- [ ] 2.3 The engine wrapper sets `PATH`, the Tesseract data directory and the add-on path, independent of the user's environment.
- [x] 2.4 A smoke test in the built engine: import, `doctor --json`, synthesize a sample, OCR a scanned synthetic page.

## 3. Finding the engine (SC2)

- [ ] 3.1 Rust: the `bundled` source, tried first; other sources only with the developer setting or without a bundled engine. Tests.
- [ ] 3.2 The app passes the engine's environment to every run. Tests.
- [ ] 3.3 Settings: the developer setting, off by default.

## 4. Add-ons (SC3, SC4)

- [ ] 4.1 Generate the pinned, hash-locked add-on package lists from `uv.lock` (Kitten 2 and Audio checking, sharing CPU PyTorch). A test that they match the lock.
- [ ] 4.2 Engine side: install, verify, remove, and report add-ons (a CLI command with a `--json` contract), using the bundled `uv`; the import path includes only complete, version-matched add-ons. Tests with a local index.
- [ ] 4.3 OCR language add-ons. Tests.
- [ ] 4.4 App side: consent, progress, cancel and removal, offered where each feature is chosen and on Setup. Component and Rust tests.
- [ ] 4.5 Manual real-network run: install both add-ons, clone a voice, run an audio check. Record it.

## 5. Setup without terminals (SC5)

- [ ] 5.1 No command text in normal mode for any `doctor` state; in-app actions instead. Tests.
- [ ] 5.2 Unreachable Ollama is optional information, and new books start with the LLM off. Tests.

## 6. Visible voice choice (SC6)

- [ ] 6.1 Segmented Built-in voice / Clone a voice choice in Book options and Speak again, with the add-on offer. Tests.

## 7. Packaging and CI (SC7)

- [ ] 7.1 Desktop CI builds the engine and the AppImage and `.deb` with it, and records sizes.
- [ ] 7.2 A clean-container job, networking disabled, runs the SC1 acceptance against the built AppImage's engine.
- [ ] 7.3 The end-to-end walkthrough uses the bundled engine.
- [ ] 7.4 Licence texts and source offers shipped and shown in About.

## 8. Documentation (SC8)

- [ ] 8.1 `desktop/README.md`, the getting-started guide, a dated note in the Tauri specification, and the maintainer guide.

## 9. Finish

- [ ] 9.1 Run every check, and install the built AppImage on a clean machine or VM: convert a book with no other installs. Record it.
- [ ] 9.2 Review against SC1–SC8 and record any unresolved limitations below.

## Unresolved limitations

(Filled in by 9.2.)

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-26 | 2121eaafa353a262a033acc03cea5c44c6dc150e | Spec, TODO and the Tauri spec's dated O1/D10.a notes. 1.1 and 1.3 done, 1.2 partial (local spike, not committed): uv-managed CPython 3.11.18 (python-build-standalone) with the locked core dependencies, pdf2audiobook, `kittenml==0.9.6` installed without its declared dependencies, and five locked packages for the ONNX path: `onnxruntime` 1.31.0, `phonemizer` 3.4.0, `espeakng-loader` 0.2.4, `soundfile` 0.14.0, `huggingface-hub` 1.33.0 (pulling in 10 small dependencies). `kittenml` imports PyTorch only for Kitten 2, so C2 holds. A synthetic two-chapter PDF converted to two MP3s with `mini`. Copied to another path, with the build directory hidden, an empty environment, `HF_HUB_OFFLINE=1` and no network (`unshare -rn`), it converted again. The console-script shebang holds the build path, so the app must start the engine through its bundled interpreter (`python -c 'from pdf2audiobook.cli import main; main()'` or a `__main__` module). Sizes: engine 362 MB (largest: PyMuPDF 65 MB, ONNX Runtime 63 MB, NumPy 61 MB, espeak-ng 21 MB; `pip` 6.5 MB can be dropped), `mini` model files 78 MB; together 157 MB compressed (zstd -19), within C8. Newest glibc symbol required: GLIBC_2.29. Not yet measured: FFmpeg and Tesseract (the spike used the system's). | Docs only. Python CI [969](https://github.com/ekkus93/pdf2audiobook/actions/runs/45945036944) and Desktop CI [124](https://github.com/ekkus93/pdf2audiobook/actions/runs/45945036926) passed. | 1.2: FFmpeg and Tesseract sources and sizes |
| 2026-11-26 | f1ef653eac19b8518ed6894c44b34b581f15bc2f, dc57348164bf63c200a4d1fc27adc1854ecc8ae5 | 1.2 partial, 2.1 partial, 2.2, 2.3 (engine side), 2.4. OCR runs through PyMuPDF's built-in Tesseract and needs only language data: an image-only page OCRed correctly with no `tesseract` program and no network, so the app ships `eng.traineddata` (tessdata_fast 4.1.0, 4 MB, byte-identical to Debian's) instead of Tesseract (amends C6). New `pdf2audiobook.bundle`: inside a bundled engine (marker file at the interpreter prefix) the CLI puts the engine's `bin/` first on `PATH` and sets `TESSDATA_PREFIX` unless the user did; the Kitten provider loads the bundled model folder while keeping the model ID as its identity. `tesseract_languages()` lists `TESSDATA_PREFIX` when set, and `doctor`'s `tesseract` now means OCR is available. `python -m pdf2audiobook` works. `desktop/engine/pins.json` pins CPython 3.11.18, the ONNX package set, FFmpeg (BtbN LGPL n8.1.3, autobuild 2026-11-26), English OCR data and the `mini` model revision, each with its SHA-256. `desktop/scripts/build_engine.py` builds `engine/` from `uv.lock` with `--require-hashes --no-deps`, adds a relocatable launcher, trims pip, Tk, IDLE and headers, precompiles bytecode and writes the marker; `desktop/scripts/smoke_engine.py` runs `doctor` and converts a text PDF and a scanned page with an empty environment and `unshare -rn`. A build without FFmpeg (`--without-ffmpeg`, using the system's for the smoke) is 471 MB; the smoke passed, and a moved copy started offline. | `tests/test_engine_bundle.py` (8 tests) failed at the parent (the module did not exist), then passed. Full suite 2,874 passed/6 skipped; Ruff and format clean; mypy clean for the changed files (7 errors elsewhere appear with the Kitten and Whisper extras installed, identical without this change; CI runs mypy without them). | FFmpeg not downloaded or measured: fetching and running the prebuilt binary was blocked by the permission check. BtbN keeps about a month of dated builds, so the pin needs a durable mirror. |
| 2026-11-26 | eeb3647c8b1a05920638808775e98263c9f37f71 | 1.2 and 2.1 done. The pinned FFmpeg archive (BtbN LGPL n8.1.3-41-ga8029b6528) downloaded and matched its SHA-256; it has the encoders the engine uses (libmp3lame, aac, flac, pcm_s16le, pcm_f32le, mjpeg, png) and needs GLIBC_2.28, so the engine's floor stays GLIBC_2.29 (CPython wheels). The static `ffmpeg` is 142 MB. The full build (`build_engine.py` with FFmpeg) passed `smoke_engine.py` with networking off and an empty environment, and the bundled `ffmpeg` was the one found. Sizes against C8: 607 MB installed (budget 1 GB), 200 MB as xz -6 and 211 MB as zstd -19 (budget 400 MB, before the Tauri app). | Local only. | The FFmpeg pin's source keeps about a month of dated builds; a durable mirror is needed before CI depends on it. |
| 2026-11-26 | dc57348164bf63c200a4d1fc27adc1854ecc8ae5 | CI for `f1ef653` and `dc57348`, pushed together (the first has no run of its own). | Python CI [970](https://github.com/ekkus93/pdf2audiobook/actions/runs/45946363127) passed 3.11/3.12/3.13 with 2,874 passed/6 skipped each. Desktop CI [125](https://github.com/ekkus93/pdf2audiobook/actions/runs/45946363117) passed. | None |
| 2026-11-26 | eeb3647c8b1a05920638808775e98263c9f37f71 | CI for the FFmpeg check record. | Docs only. Python CI [971](https://github.com/ekkus93/pdf2audiobook/actions/runs/45951701284) and Desktop CI [126](https://github.com/ekkus93/pdf2audiobook/actions/runs/45951701286) passed. | FFmpeg mirror |
