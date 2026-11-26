# PDF2Audiobook Kitten 2 Temperature Specification

**Status:** Implemented 2026-11-26 (default 0.2; see the TODO for limitations)
**Date:** 2026-11-25
**Companion:** [Kitten 2 Temperature TODO](PDF2AUDIOBOOK_KITTEN2_TEMPERATURE_TODO.md)
**Baseline:** `master` at `f3c970f`
**Supplements:** [Voice Cloning Specification](PDF2AUDIOBOOK_VOICE_CLONING_SPEC.md) (§3 VC2 configuration, §6 VC5 synthesis, §7 VC6 identity)

## 1. Purpose and scope

Kitten TTS 2 (`--tts-model kitten2`) generates speech by sampling audio tokens, so it can speak words that are not in the text, repeat words or run on. kittenml 0.9.6's `generate()` takes a `temperature` (and `top_k`, `top_p`, `min_p`) on top of a named decoding preset. pdf2audiobook calls it only from `tts/clone_worker.py`, always with `preset="stable"` and `seed=0`, and passes no temperature, so the model's own preset value applies and the user cannot lower it.

This adds one setting, `tts.kitten.temperature`, defaulting to a low value, so Kitten 2 narration stays close to the text.

In scope: Kitten 2, for both built-in voices and cloned voices. Out of scope:
- Kitten 0.8 (`mini`, `micro`, `nano`): these models do not sample, and their `generate()` has no temperature. The setting does not apply to them.
- `top_k`, `top_p`, `min_p`, and other presets. They stay at the `stable` preset's values.
- Piper.
- The desktop app's settings screen (a follow-up, §6).

## 2. Requirements

### K1: The setting

- `[tts.kitten] temperature`, a float. When it is not set, the default is `0.2`, the low value chosen in K5 (amended 2026-11-26; the draft's provisional value was `0.3`). It must be finite and in `[0.05, 1.5]`; anything else is a `ConfigError` with a content-free message.
- An environment variable `PDF2AUDIOBOOK_TTS_KITTEN_TEMPERATURE` and a `--tts-temperature` flag on `convert`, `batch` and `resynthesize` (the commands that already take `--speed`; amended 2026-11-25, the draft named `verify-audio`), with the existing precedence: flag, then environment variable, then config file, then default.
- A `[tts.profiles.<name>]` profile may set `temperature`, like `speed`.
- `config show --json` reports the value and its source. When the selected model is not Kitten 2 and the value was set explicitly, it is listed in `_unused_settings`, the same way `cache.directory` is.
- `doctor --json` reports `"tts_temperature"`: the effective value when the model is Kitten 2, otherwise `null`.

**Acceptance:** Settings tests cover the default, each source in precedence order, a profile override, the range bounds (including NaN and infinity), and the unused-setting report for `mini`. The `config-show` and `doctor` contract schemas and their tests are updated.

### K2: Passing it to the model

- The clone worker passes `temperature=<value>` to `model.generate()` for built-in voices (`generate_builtin`) and cloned voices. It keeps `preset="stable"`, `seed=0`, `normalize=False` and `use_emotion=False`.
- The value reaches the worker through its existing request, not through the environment.
- Kitten 0.8 synthesis is unchanged and never receives a temperature.

**Acceptance:** A worker test with a fake model records the `temperature` keyword for both request kinds. A test shows the Kitten 0.8 provider's `generate()` call is unchanged.

### K3: Identity, resume and caching

- The temperature becomes part of the Kitten 2 model identity in `tts/selection.py`, renamed `kitten2-model-v2`. That identity feeds the chunk-cache keys, progress identity and chapter fingerprints, for built-in and cloned voices alike. Chapter sidecars record it as `rendering_inputs.kitten2_temperature`, only when Kitten 2 is selected.
- The recorded clone reference identity (`GENERATION` and the reference digests) does not change. It describes the reference recording, not how it is decoded. (Amended 2026-11-25: the draft also put the temperature in `GENERATION`; the model identity already covers every key that needs it.)
- Changing the value regenerates the affected Kitten 2 audio and nothing else. The same value reuses the existing audio.
- Audio made before this change was keyed by `kitten2-model-v1`, and its sidecars have no `kitten2_temperature`, so neither matches. Existing Kitten 2 audio is regenerated once after upgrading. This is intended: it was made at the preset's own temperature, not the new default.
- The Kitten 0.8 and Piper identities do not change, so their finished audio is not regenerated.
- The analysis fingerprint and manifest do not change.

**Acceptance:** Tests show that a temperature change gives a new chapter fingerprint for Kitten 2 and an unchanged one for `mini`. A conversion re-run at the same value makes no synthesis calls; at a new value it re-synthesizes only Kitten 2 chapters. The analysis manifest bytes stay the same.

### K4: Privacy and output

- No new error, log or `--json` field carries book text, reference audio paths, transcripts or digests.
- `--json` output stays parseable.

**Acceptance:** The existing marker-based privacy tests pass. The range error is checked to be content-free.

### K5: Choosing the default

The default must be low enough to keep narration close to the text, without the problems very low sampling temperatures can cause in autoregressive speech: flat delivery, stalls and repetition loops.

- Read the `stable` preset's own `temperature` from the fetched model's `config.json` (`decode_presets.stable`) and record it. The default must not be higher than that value.
- Run a local comparison with the real model (never committed, counts only). Narrate the same sample chapters at the preset's value and at two or three lower candidates (for example `0.5`, `0.3` and `0.2`). Use the same voice and seed. Score each with `verify-audio` (Whisper), recording the word error rate, the inserted and repeated words, and the number of chunks flagged.
- Pick the lowest candidate that does not raise the flagged-chunk count or add audible stalls, repetition or flat delivery. A person listens to each candidate's sample. Record the chosen value, the numbers and the listening verdict in the TODO ledger.

**Acceptance:** The ledger names the preset value, the candidates, each candidate's verification counts, and the user's listening verdict. The default in code matches the recorded choice.

## 3. Identity summary

| Item | Changes? |
|---|---|
| Kitten 2 chunk keys, chapter fingerprints, clone sidecars | Yes, they include the temperature |
| Existing Kitten 2 audio | Regenerated once after upgrading |
| Kitten 0.8 (`mini`, `micro`, `nano`) and Piper identities | No |
| Analysis fingerprint and manifest | No |

## 4. Documentation

- README: the setting, its default, that it applies only to Kitten 2, and that lower values keep narration closer to the text at some cost to expressiveness.
- Maintainer guide: where the value enters the generation identity, and that changing the default regenerates Kitten 2 audio.
- Voice Cloning Specification §3 and §7: a dated note pointing here.

## 5. Known limitations

- Lowering the temperature reduces how often Kitten 2 speaks words that are not in the text. It does not prevent it. `verify-audio` is still the check for misread chunks.
- `top_k`, `top_p` and `min_p` stay at the preset's values, so they also affect the result.

## 6. Follow-up (not in this round)

- A temperature control in the desktop app's voice settings, through the config contract.

## 7. Validation

- Write each requirement's tests first and run them against the parent commit. Record the failing test IDs in the ledger.
- Run `/verify`, and mypy on Python 3.12 and 3.13.
- Desktop checks run only if `desktop/` changes. Updating the contract schema in `desktop/contracts/` counts as a change.
- Check CI after each push.
