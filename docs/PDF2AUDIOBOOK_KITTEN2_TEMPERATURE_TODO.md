# PDF2Audiobook Kitten 2 Temperature TODO

**Status:** Proposed
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

- [ ] 1.1 Add `temperature` to the Kitten settings: a provisional default of `0.3` and the range `[0.05, 1.5]`, with NaN and infinity rejected. Add a profile field, `PDF2AUDIOBOOK_TTS_KITTEN_TEMPERATURE` and `--tts-temperature` on `convert`, `batch` and `verify-audio`.
- [ ] 1.2 Tests: the default; flag over environment over config over default; a profile override; the range bounds; a content-free range error.
- [ ] 1.3 `config show`: list an explicitly set temperature in `_unused_settings` when the model is not Kitten 2. `doctor`: report `tts_temperature`, with `null` for other models. Update the `config-show` and `doctor` contract schemas and their tests.

## 2. Pass it to the model (K2)

- [ ] 2.1 Carry the value in the clone worker's request. Pass `temperature=` to `model.generate()` for built-in and cloned voices, keeping `preset="stable"`, `seed=0`, `normalize=False` and `use_emotion=False`.
- [ ] 2.2 Tests: a fake model records the `temperature` keyword for both request kinds, and the Kitten 0.8 provider's `generate()` call is unchanged.

## 3. Identity (K3)

- [ ] 3.1 Add the temperature to the Kitten 2 generation identity (`GENERATION` and the `kitten2-model-v1` identity), so it reaches chunk keys, progress identity, chapter fingerprints and clone sidecars.
- [ ] 3.2 Tests:
  - a different temperature gives a new Kitten 2 chapter fingerprint, and the `mini` fingerprint is unchanged;
  - a re-run at the same value makes no synthesis calls;
  - a new value re-synthesizes only Kitten 2 chapters;
  - a recorded identity without `temperature` does not match;
  - the analysis manifest bytes stay the same.

## 4. Privacy (K4)

- [ ] 4.1 Run the marker-based privacy tests, and add one showing the new range error and `doctor` field carry no book or reference content.

## 5. Choose the default (K5)

- [ ] 5.1 Fetch Kitten 2 locally (`pdf2audiobook tts fetch kitten2`). Read `decode_presets.stable` from its `config.json` and record the preset's temperature, `top_k`, `top_p` and `min_p` in the ledger.
- [ ] 5.2 Narrate the same sample chapters at the preset's value and at the candidates (for example `0.5`, `0.3` and `0.2`), using the same voice and seed. For each, run `verify-audio` with Whisper and record the word error rate, inserted and repeated words, and flagged chunks. Counts only, never committed.
- [ ] 5.3 Ask the user to listen to each candidate's sample. Choose the lowest value that does not add flagged chunks, stalls, repetition or flat delivery. Set it as the default and record the choice and the user's verdict in the ledger.

## 6. Documentation

- [ ] 6.1 README: the setting, its default, that it applies only to Kitten 2, and the expressiveness trade-off.
- [ ] 6.2 Maintainer guide: where the value enters the identity, and that changing the default regenerates Kitten 2 audio.
- [ ] 6.3 Voice Cloning Specification §3 and §7: a dated note pointing to this specification.

## 7. Finish

- [ ] 7.1 Run `/verify`, and mypy on Python 3.12 and 3.13. Record the pass and skip counts.
- [ ] 7.2 Review the final diff against K1–K5 and record any unresolved limitations below.

## Unresolved limitations

(Filled in by 7.2.)

## Progress ledger

| Date | Master SHA | Completed tasks | Tests/CI | Blockers |
| --- | --- | --- | --- | --- |
