# PDF2Audiobook Desktop Temperature Control Specification

**Status:** Proposed (draft)
**Date:** 2026-11-26
**Companion:** [Desktop Temperature TODO](PDF2AUDIOBOOK_DESKTOP_TEMPERATURE_TODO.md)
**Baseline:** `master` at `600fa34`
**Supplements:** [Kitten 2 Temperature Specification](PDF2AUDIOBOOK_KITTEN2_TEMPERATURE_SPEC.md) (§6 follow-up), [Desktop App Specification](PDF2AUDIOBOOK_TAURI_SPEC.md) (D4.3 Book options)

## 1. Purpose and scope

The CLI has a Kitten 2 sampling temperature: `tts.kitten.temperature`, default `0.2`, range `0.05`–`1.5`, and `--tts-temperature` on `convert`, `batch` and `resynthesize`. The desktop app cannot set it yet. This adds a temperature control to the two places where the app already sets the speed for a run: **Book options → Voice** and the **Speak again** dialog.

In scope: the Book options form, the Speak again dialog, the Rust request builder, and the app's types for `config show`. Out of scope:
- **Settings → Voice defaults.** It only writes voice-cloning keys. A shared default temperature is set in the TOML editor on the same screen, like a default speed.
- Batch conversion. The app has no batch screen.
- `top_k`, `top_p`, `min_p` and the decoding preset, which the CLI does not expose either.

## 2. Requirements

### DT1: Requests

- `ConvertOptions` and `Request::Resynthesize` in `src-tauri/src/engine/request.rs` gain `temperature: Option<f64>`, default `None`.
- When it is set, the builder passes `--tts-temperature=<value>`. It must be finite and in `[0.05, 1.5]`; anything else is `RequestError::OutOfRange("The temperature")`, and nothing runs. `None` passes no flag, so the CLI's own precedence applies.
- The TypeScript `ConvertOptions` and the `resynthesize` request carry the same optional field.

**Acceptance:** Rust tests show the flag for `convert` and `resynthesize`, no flag for `None`, and refusal of `0.04`, `1.51`, NaN and infinity. The privacy tests still pass; the value is a number and carries no content.

### DT2: Where the starting value comes from

- The app's `CliConfig` type reads `tts.kitten.temperature`, and `temperature` in a profile. Both are optional, so an older CLI that lacks them still loads.
- A book starts with its filename-stem profile's `temperature`, then `tts.kitten.temperature`, then `0.2`. This is the CLI's own precedence for a book; environment overrides are already folded into `config show`.
- The form also records whether the book will use Kitten 2: when cloning is selected or inherited, or when the effective provider is `kitten` and the effective model (profile `kitten_model`, then `tts.kitten.model`) is `kitten2` or `KittenML/kitten-tts-2`.

**Acceptance:** Unit tests for `defaults()` cover the built-in fallback, the config value, a profile override, and each way of selecting Kitten 2.

### DT3: Book options

- When the book will use Kitten 2, the Voice group shows a **Temperature** slider under Speed: range `0.05`–`1.5`, step `0.05`, value shown to two decimals. Its supporting text says that lower keeps the narration closer to the text, and that higher can sound more expressive but slips more often.
- When the book will not use Kitten 2, the slider is hidden and `convert` sends no temperature.
- Choosing **Clone a voice** shows the slider, since cloning selects Kitten 2. Choosing **Built-in voice** returns to the inherited model's state.
- `validate()` refuses a non-finite or out-of-range value with "Between 0.05 and 1.5".

**Acceptance:** Component tests show the slider for Kitten 2 and cloning, its absence for `mini` and Piper, and the value in the `convert` request only when Kitten 2 is used.

### DT4: Speak again

- The Speak again dialog starts from the book options' temperature and shows the same slider when the chapter will be spoken by Kitten 2, under the same rule as DT3, including a clone chosen in the dialog.
- `resynthesize` sends the chosen value only in that case.

**Acceptance:** Component tests show the slider and the request value for Kitten 2 and cloning, and neither for `mini`.

### DT5: Documentation

- The desktop sections of the [voices guide](guides/voices.md#kitten-2-temperature) and the voice cloning guide name the control.
- The Kitten 2 temperature specification's §6 follow-up points here.

## 3. Identity and privacy

No CLI change. The temperature already belongs to Kitten 2 audio identity, so a changed value regenerates that book's Kitten 2 audio, as it does from the CLI. The app adds no log, error or stored field. The flag value appears in the command shown under Details, like `--speed`.

## 4. Validation

- Write each requirement's tests first and run them against the parent commit. Record the failing test IDs in the ledger.
- For `desktop/` changes: `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test`, and the frontend lint, type-check and tests. Check Desktop CI and Python CI after each push.
