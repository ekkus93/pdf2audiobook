# PDF2Audiobook Desktop Temperature Control TODO

**Status:** Complete 2026-11-26; four limitations recorded below
**Date:** 2026-11-26
**Baseline:** `master` at `600fa34`
**Specification:** [Desktop Temperature Control Specification](PDF2AUDIOBOOK_DESKTOP_TEMPERATURE_SPEC.md) (DT1–DT5)

## Working rules

- Work in the order below. Write each task's tests first and run them against the parent commit, so the failing test IDs are recorded before the fix.
- Use `[x]` only when the implementation exists and its named tests pass. Otherwise mark the item partial in the ledger.
- Conventional Commits with the `desktop` or `docs` scope, lowercase imperative subject, no body.
- Before each `desktop/` commit: `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test`, `npm run lint`, `npm run typecheck` and `npm test`.
- Check Desktop CI and Python CI after every push. A failed run blocks the next task until it is fixed or explained.
- No book text, titles, file names or private paths in logs, errors or dialogs.

## 1. Requests (DT1)

- [x] 1.1 Rust: `temperature: Option<f64>` on `ConvertOptions` and `Request::Resynthesize`; `--tts-temperature=<value>` when set; `OutOfRange("The temperature")` outside `[0.05, 1.5]` or non-finite. Tests for both commands, `None`, the bounds, NaN and infinity.
- [x] 1.2 TypeScript: the optional `temperature` on `ConvertOptions` and the `resynthesize` request.

## 2. Starting value (DT2)

- [x] 2.1 `CliConfig` reads the optional `tts.kitten.temperature` and profile `temperature`.
- [x] 2.2 `defaults()` sets `temperature` (profile, then config, then `0.2`) and whether the book's inherited model is Kitten 2. Unit tests for each source and each way of selecting Kitten 2.

## 3. Book options (DT3)

- [x] 3.1 A Temperature slider in the Voice group, shown only when the book will use Kitten 2 (including a chosen or inherited clone), with supporting text on the trade-off.
- [x] 3.2 `validate()` range check; `requests()` sends `temperature` only when Kitten 2 is used. Component and unit tests.

## 4. Speak again (DT4)

- [x] 4.1 The dialog starts from the book's temperature, shows the slider under the same rule, and sends the value only for Kitten 2. Component tests.

## 5. Documentation (DT5)

- [x] 5.1 The voices and voice cloning guides name the desktop control; the Kitten 2 temperature spec §6 points here.

## 6. Finish

- [x] 6.1 Run the desktop checks and `/verify`. Record the counts.
- [x] 6.2 Review the diff against DT1–DT5 and record any unresolved limitations below.

## Unresolved limitations

Recorded by the 6.2 review, 2026-11-26.

1. **Settings → Voice defaults** does not set a temperature. A shared default goes in the TOML editor on the same screen (spec §1).
2. The app decides whether Kitten 2 will speak with its own copy of the CLI's rule (`KITTEN2_MODELS` in `bookOptions.ts`, `KITTEN2_MODEL_NAMES` in `tts/selection.py`). A new Kitten 2 model name must be added to both.
3. Against a CLI older than `--tts-temperature`, a Kitten 2 conversion from the app fails with an unknown-option error. The form falls back to `0.2` when `config show` has no temperature, and still sends it. This affects only an app paired with an older CLI.
4. Nobody has looked at the slider in the running app. The component tests check it renders, starts at the right value and reaches the request. The end-to-end walkthrough (Desktop CI) clones a voice, so its run now passes `--tts-temperature=0.2`, but it does not move the slider.

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-26 | 29de3115bfdcd51024ae3276fe2ea0a617cf54c9 | 1.1–6.2 (DT1–DT5): Rust `temperature` on `convert` and `resynthesize` requests with `--tts-temperature` and an `OutOfRange("The temperature")` check; TypeScript types; `defaults()` starts from the profile, then `tts.kitten.temperature`, then 0.2, and records whether Kitten 2 is configured; a shared `TemperatureControl` slider (0.05–1.5, step 0.05) in Book options → Voice and Speak again, shown and sent only when Kitten 2 speaks (configured or cloning); guides and the Kitten 2 temperature spec §6 updated. | Tests written first and failing at the parent: Rust `the_kitten_2_temperature_is_passed_only_when_set` (did not compile); 5 of 18 `bookOptions.test.ts` tests; 4 of 5 new or changed component tests (`BookPage`: starts from the configuration…, appears when a voice is cloned…; `AudioCheck`: repairs a clone…, speaks again with the book's Kitten 2 temperature…); the hidden-slider test is a guard that already held. Local: `cargo fmt --check`, `cargo clippy --all-targets -D warnings`, `cargo test` 121 + 7 passed (4 ignored); `npm run lint`, `npm run typecheck`, `npm test` 21 files, 412 passed (but the run exited 1 on two unhandled Lit warnings, missed locally because only the counts were read). `/verify` with mypy on 3.11/3.12/3.13: 2,866 passed, 6 skipped (opt-in real-model tests and the absent Kitten extra). Python CI [966](https://github.com/ekkus93/pdf2audiobook/actions/runs/45939738360) passed 3.11/3.12/3.13 with 2,866 passed/6 skipped each. Desktop CI [121](https://github.com/ekkus93/pdf2audiobook/actions/runs/45939738212) FAILED at Frontend tests: two new tests overrode `value` on `md-slider` and `md-outlined-text-field` with `Object.defineProperty`, which Lit reports as class-field shadowing, and Vitest fails on unhandled errors. | Fixed in `a6b5710` |
| 2026-11-26 | a6b57108dd7b6407c3472723a1493866bfa59433 | The new tests set the slider and text-field values through the elements' own properties. | `npm test` 412 passed, exit 0, no unhandled errors. Python CI [967](https://github.com/ekkus93/pdf2audiobook/actions/runs/45940103587) passed 3.11/3.12/3.13 with 2,866 passed/6 skipped each. Desktop CI [122](https://github.com/ekkus93/pdf2audiobook/actions/runs/45940103649) passed, including the end-to-end walkthrough. | None |
