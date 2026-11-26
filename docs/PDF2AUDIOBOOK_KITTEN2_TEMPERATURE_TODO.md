# PDF2Audiobook Kitten 2 Temperature TODO

**Status:** Complete 2026-11-26 (default 0.2); six limitations recorded below
**Date:** 2026-11-25
**Baseline:** `master` at `f3c970f`
**Specification:** [Kitten 2 Temperature Specification](PDF2AUDIOBOOK_KITTEN2_TEMPERATURE_SPEC.md) (K1–K5)

## Working rules

- Work in the order below. Write each task's tests first and run them against the parent commit, so the failing test IDs are recorded before the fix.
- Use `[x]` only when the implementation exists and its named tests pass. Otherwise mark the item partial in the ledger.
- One fix per commit. Conventional Commits with a scope, lowercase imperative subject, no body.
- Check CI after every push. A failed run blocks the next task until it is fixed or explained.
- Errors, logs and `--json` stay content-free. Fixtures are synthetic and CI stays offline. Never commit model weights, generated audio, reference recordings or private paths.

## 1. Setting (K1)

- [x] 1.1 Add `temperature` to the Kitten settings: a provisional default of `0.3` and the range `[0.05, 1.5]`, with NaN and infinity rejected. Add a profile field, `PDF2AUDIOBOOK_TTS_KITTEN_TEMPERATURE` and `--tts-temperature` on `convert`, `batch` and `resynthesize`.
- [x] 1.2 Tests: the default; flag over environment over config over default; a profile override; the range bounds; a content-free range error.
- [x] 1.3 `config show`: list an explicitly set temperature in `_unused_settings` when the model is not Kitten 2. `doctor`: report `tts_temperature`, with `null` for other models. Update the `config-show` and `doctor` contract schemas and their tests.

## 2. Pass it to the model (K2)

- [x] 2.1 Carry the value in the clone worker's request. Pass `temperature=` to `model.generate()` for built-in and cloned voices, keeping `preset="stable"`, `seed=0`, `normalize=False` and `use_emotion=False`.
- [x] 2.2 Tests: a fake model records the `temperature` keyword for both request kinds, and the Kitten 0.8 provider's `generate()` call is unchanged.

## 3. Identity (K3)

- [x] 3.1 Add the temperature to the Kitten 2 model identity (renamed `kitten2-model-v2`), so it reaches chunk keys, progress identity and chapter fingerprints, and record it in chapter sidecars as `rendering_inputs.kitten2_temperature` when Kitten 2 is selected.
- [x] 3.2 Tests:
  - a different temperature gives a new Kitten 2 chapter fingerprint, and the `mini` fingerprint is unchanged;
  - a re-run at the same value makes no synthesis calls;
  - a new value re-synthesizes only Kitten 2 chapters;
  - audio keyed by the old `kitten2-model-v1` identity, or a sidecar without `kitten2_temperature`, is not reused;
  - the analysis manifest bytes stay the same.

## 4. Privacy (K4)

- [x] 4.1 Run the marker-based privacy tests, and add one showing the new range error and `doctor` field carry no book or reference content.

## 5. Choose the default (K5)

- [x] 5.1 Fetch Kitten 2 locally (`pdf2audiobook tts fetch kitten2`). Read `decode_presets.stable` from its `config.json` and record the preset's temperature, `top_k`, `top_p` and `min_p` in the ledger.
- [x] 5.2 Narrate the same sample chapters at the preset's value and at the candidates (for example `0.5`, `0.3` and `0.2`), using the same voice and seed. For each, run `verify-audio` with Whisper and record the word error rate, inserted and repeated words, and flagged chunks. Counts only, never committed.
- [x] 5.3 Ask the user to listen to each candidate's sample. Choose the lowest value that does not add flagged chunks, stalls, repetition or flat delivery. Set it as the default and record the choice and the user's verdict in the ledger.

## 6. Documentation

- [x] 6.1 User guides (the README's user material now lives in `docs/guides`): the setting, its default, that it applies only to Kitten 2, and the expressiveness trade-off.
- [x] 6.2 Maintainer guide: where the value enters the identity, and that changing the default regenerates Kitten 2 audio.
- [x] 6.3 Voice Cloning Specification §3 and §7: a dated note pointing to this specification.

## 7. Finish

- [x] 7.1 Run `/verify`, and mypy on Python 3.12 and 3.13. Record the pass and skip counts.
- [x] 7.2 Review the final diff against K1–K5 and record any unresolved limitations below.

## Unresolved limitations

Recorded by the 7.2 review, 2026-11-26. None blocks the setting.

1. A low temperature makes Kitten 2 less likely to speak words that are not in the text, repeat words or run on. It does not prevent it. `verify-audio` remains the check for misread chunks.
2. `top_k`, `top_p` and `min_p` stay at the `stable` preset's values (50, 0.8, 0.0) and also shape the output. They are not configurable.
3. The default rests on a small sample: two chapters (about 2:17 each) of one technical paper, one built-in voice (Jasper), seed 0. Cloned voices and long-form or fiction narration were not compared with the real model. In that sample only two slips occurred in eight renders, so the counts alone do not separate 0.8, 0.5, 0.3 and 0.2. The choice of 0.2 rests on the spec's lowest-acceptable rule and the listening check.
4. The comparison ran locally. The main CI checks the setting only with stand-in models. The manual real-model workflow's clone tests now run at the 0.2 default, but nothing there compares temperatures or checks that one was applied.
5. The desktop app has no temperature control (spec §6 follow-up). Its TypeScript `doctor` type does not read `tts_temperature`. The contract test validates the CLI's `doctor` output against the updated schema.
6. Kitten 2 audio made before this change, or at another temperature, is regenerated once on its next conversion, as K3 intends.

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-25 | 377c1ec3f6545adb1c65868ace687bd00f575413 | Spec and TODO committed. | Docs only. Python CI run [954](https://github.com/ekkus93/pdf2audiobook/actions/runs/45711151801) and Desktop CI run [109](https://github.com/ekkus93/pdf2audiobook/actions/runs/45711151665) passed. | None |
| 2026-11-25 | 4d24dec71c0966673af340e9233ed1f96da69b30 | 1.1–4.1 (K1–K4): `tts.kitten.temperature` (default 0.3, range 0.05–1.5), env variable, `--tts-temperature` on `convert`, `batch` and `resynthesize`, profile field; `config show` unused report and `doctor` `tts_temperature`; both Kitten 2 paths send it to the model; `kitten2-model-v2` identity and `rendering_inputs.kitten2_temperature`. | Tests written first: 13 of 20 settings tests, 4 of 5 synthesis tests and 3 of 6 identity tests failed at the parent (the rest are guards that already held). Python CI [957](https://github.com/ekkus93/pdf2audiobook/actions/runs/45715727658) passed 3.11/3.12/3.13 with 2,866 passed/6 skipped each. Desktop CI [112](https://github.com/ekkus93/pdf2audiobook/actions/runs/45715727726) FAILED: the walkthrough's stand-in clone provider (`desktop/e2e/fake_clone.py`) did not accept `temperature`. Fixed below. | Fixed in `062fc8d` |
| 2026-11-25 | 062fc8d7078698d03c101cd5f6941272046ee44b | Walkthrough clone double accepts the temperature. | Python CI [958](https://github.com/ekkus93/pdf2audiobook/actions/runs/45717763039) passed 3.11/3.12/3.13 with 2,866 passed/6 skipped each. Desktop CI [113](https://github.com/ekkus93/pdf2audiobook/actions/runs/45717763001) passed. | Task 5 (default choice) and 6–7 |
| 2026-11-26 | 94b0bb58738cd10c1f5e719b7259af9d03ac4bfc | 5.1–5.3 (K5): the default is now 0.2. Preset (`config.json` `decode_presets.stable`): temperature 0.8, top_p 0.8, top_k 50, min_p 0.0 (expressive: 0.9, 0.9, 50, 0.0). Local real-model comparison, not committed: Attention paper chapters 4 and 9, built-in voice Jasper, seed 0, `stable` preset, at 0.8, 0.5, 0.3 and 0.2; scored with Whisper medium.en against the chapter text with citations removed. Word error rate ch4/ch9, Whisper-flagged chunks ch4/ch9, inserted or repeated words: 0.8: 1.1%/2.8%, 0/2, 1 inserted word (ch9); 0.5: 1.5%/2.4%, 1/2, none; 0.3: 1.1%/2.8%, 0/2, 1 repeated word (ch4); 0.2: 1.1%/3.1%, 0/2, none. No dropped or reordered text and no stalls at any value; all renders 2:16–2:18. Nearly all word errors are Whisper spelling (numerals, "paran", dropped commas, "dk"), common to every value; the ch9 flags are the title number and "dk" at every value. Listening verdict: 0.3 ch9 "sounded good", 0.3 ch4 "sounds good"; 0.2 ch9 "sounded natural", 0.2 ch4 "sounds natural". Chose 0.2, the lowest candidate with no added flags, stalls, repetition or flat delivery. Default and the tests that assume it updated. | Python CI [960](https://github.com/ekkus93/pdf2audiobook/actions/runs/45808759660) passed 3.11/3.12/3.13 with 2,866 passed/6 skipped each. Desktop CI [115](https://github.com/ekkus93/pdf2audiobook/actions/runs/45808760205) passed. | Tasks 6–7 |
| 2026-11-26 | 545156bb66aa3f71ea5e8e0531c2d3b3d1659a13 | 6.1–6.3: `docs/guides/voices.md` gains a "Kitten 2 temperature" section (default 0.2, range, Kitten 2 only, the slips-versus-expressiveness trade-off, flag, environment variable, config and profile, `config show` and `doctor` reports, regeneration on change), linked from the configuration, CLI and voice cloning guides. The maintainer guide's voice cloning contracts describe where the value enters identity and that changing the default regenerates Kitten 2 audio. Voice Cloning Specification §3 and §7 carry dated notes pointing to the temperature spec. | Docs only. Python CI [962](https://github.com/ekkus93/pdf2audiobook/actions/runs/45813545519) passed 3.11/3.12/3.13 with 2,866 passed/6 skipped each. Desktop CI [117](https://github.com/ekkus93/pdf2audiobook/actions/runs/45813545620) passed. | Task 7 |
| 2026-11-26 | (uncommitted) | 7.1–7.2: final local gate on `d725304` plus this TODO: lock check, locked sync, Ruff, format (521 files), mypy 110 modules on Python 3.11, 3.12 and 3.13, pytest 2,866 passed/6 skipped (skips: Kitten extra not installed, 3 real-ASR opt-ins, 2 real-clone opt-ins; FFmpeg present), CLI smoke. Review of the diff from `f3c970f` against K1–K5: K1 setting, range, environment variable, `convert`/`batch`/`resynthesize` flag, profile, `config show` unused report and `doctor` field (validated by `tests/test_desktop_contracts.py` against the updated schema; `config-show` needs no schema change, it already allows `_unused_settings`); K2 both worker requests carry it and Kitten 0.8 never does; K3 `kitten2-model-v2` and `rendering_inputs.kitten2_temperature`, clone reference identity, Kitten 0.8, Piper and analysis identities unchanged; K4 content-free range error and `doctor` output; K5 recorded above. Six limitations recorded. | Local only; CI pending. | None |
