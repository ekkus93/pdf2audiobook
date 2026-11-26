# Voices and speech

[Home](../../README.md) · [All guides](README.md)

Create your [configuration file](configuration.md) before adding the TOML settings below.

- [Kitten voices](#kitten-voices)
- [Piper and other settings](#piper-and-other-settings)

## Kitten voices

Kitten has eight voices, and all three Kitten models (`mini`, the default, plus `micro` and
`nano`) offer the same ones. The default voice is **Jasper**. Each name links to a short sample
made with the `mini` model at normal speed; all eight read the same sentence:

| Voice | Kitten voice ID | Sample |
|---|---|---|
| Bella | `expr-voice-2-f` (female) | [Bella.mp3](../audio/voices/Bella.mp3?raw=true) |
| Jasper (default) | `expr-voice-2-m` (male) | [Jasper.mp3](../audio/voices/Jasper.mp3?raw=true) |
| Luna | `expr-voice-3-f` (female) | [Luna.mp3](../audio/voices/Luna.mp3?raw=true) |
| Bruno | `expr-voice-3-m` (male) | [Bruno.mp3](../audio/voices/Bruno.mp3?raw=true) |
| Rosie | `expr-voice-4-f` (female) | [Rosie.mp3](../audio/voices/Rosie.mp3?raw=true) |
| Hugo | `expr-voice-4-m` (male) | [Hugo.mp3](../audio/voices/Hugo.mp3?raw=true) |
| Kiki | `expr-voice-5-f` (female) | [Kiki.mp3](../audio/voices/Kiki.mp3?raw=true) |
| Leo | `expr-voice-5-m` (male) | [Leo.mp3](../audio/voices/Leo.mp3?raw=true) |

Use the name, not the ID, wherever pdf2audiobook asks for a voice. To choose one:

- **One run:** `uv run pdf2audiobook convert book.pdf --voice Luna` (add `--speed 1.1` to read
  faster, or `--tts-model micro` for a smaller model).
- **Every run:** set it in `~/.config/pdf2audiobook/config.toml`:

  ~~~toml
  [tts.kitten]
  model = "mini"
  voice = "Luna"
  speed = 1.0
  ~~~

- **One book:** a `tts.profiles` entry matched by file name (below).
- **One chapter:** the "Speaker voice ID" field on the [review page](getting-started.md#step-4-review-the-chapters-in-your-browser).
- **One passage:** a `[[voice:Leo]]` marker in the chapter text (see dialogue, below).

To regenerate the samples, for example after a Kitten upgrade, run
`uv run python scripts/voice_samples.py` (it needs the `kitten` extra and FFmpeg). Kitten's
output varies slightly between runs, so every run rewrites all eight files.

## Piper and other settings

Kitten is the default TTS provider. Piper can be selected when its CLI and a voice model are
installed separately; configure the ONNX model path in TOML:

~~~toml
[tts]
provider = "piper"

[tts.piper]
model_path = "/path/to/en_US-lessac-medium.onnx"
voice = "0" # optional multi-speaker ID
speed = 1.0
~~~

Then run `uv run pdf2audiobook convert book.pdf --no-llm --tts-provider piper`. Piper is not
installed or downloaded by the default project environment.

Use `tts.profiles` to select a voice and speed by exact PDF filename stem:

~~~toml
[tts.profiles."My Book"]
provider = "kitten"
kitten_model = "mini"
voice = "Jasper"
speed = 1.05

[tts.pronunciations]
"Māori" = "Mow-ree"
~~~

Pronunciation replacements apply only to speech output; they must be a single token. Source chapter
text remains unchanged and progress ranges still point to the original words.

For dialogue, edit an approved chapter text file and put `[[voice:VOICE_ID]]` on its own line
between blank lines before the paragraph that voice should narrate. For example:

~~~text
The narrator introduces the scene.

[[voice:OtherVoice]]

“We should leave,” she said.
~~~

The marker is omitted from speech; that voice continues until another marker or the end of the
chapter. The chapter's configured voice is used before the first marker. Markers require blank-line
paragraph boundaries, and their source offsets remain in the narration progress record.

## Clone a local voice

Full KittenTTS 2 supports a recording-based voice selection through `--tts-model kitten2
--clone-voice`. Other models retain built-in voices. Follow the [voice cloning guide](voice-cloning.md)
for explicit model setup, recording limits, transcripts, desktop controls and acceptance status.

## Kitten 2 temperature

Full KittenTTS 2 (`kitten2`) chooses each stretch of audio by sampling, so now and then it can say
a word that is not in the text, repeat a word, or run on. Its sampling temperature controls how
freely it samples. pdf2audiobook keeps it low by default, at `0.2`, so narration stays close to
the text. The model's own `stable` preset uses `0.8`. A higher value can sound more expressive and
makes slips more likely. Values from `0.05` to `1.5` are accepted.

The setting applies to Kitten 2 only, for built-in and cloned voices alike. The smaller Kitten
models (`mini`, `micro`, `nano`) do not sample and ignore it, and so does Piper.

- **One run:** `--tts-temperature 0.3` on `convert`, `batch` or `resynthesize`.
- **Every run:** `temperature = 0.3` under `[tts.kitten]`, or the
  `PDF2AUDIOBOOK_TTS_KITTEN_TEMPERATURE` environment variable.
- **One book:** `temperature = 0.3` in its `[tts.profiles."<file name>"]` entry.

A command-line flag takes precedence over the environment variable, which takes precedence over
the config file. `config show` lists a temperature you set as unused when Kitten 2 is not
selected, and `doctor --json` reports the value in use as `tts_temperature`.

The temperature is part of Kitten 2's audio identity. Changing it regenerates Kitten 2 audio the
next time a book is converted, and keeps the chapter analysis and approvals. Converting again at the
same value reuses the audio already made. Kitten 2 audio made before this setting existed was
rendered at the preset's `0.8`, so it is regenerated once.

A low temperature makes slips less likely but does not rule them out. Use
[audio verification](audio-verification.md) to find chapters that were misread.
