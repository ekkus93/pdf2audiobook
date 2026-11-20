# Local voice cloning

[Home](../../README.md) · [All guides](README.md)

Voice cloning is an optional English narration mode for the CLI and desktop app. It requires
**full KittenTTS 2**, selected as `kitten2`. The existing default `mini`, other 0.8 models, and
Piper retain their built-in voices and cannot clone a recording.

## Set up the local model

```bash
uv sync --locked --extra kitten --extra dev
uv run pdf2audiobook tts models --json
uv run pdf2audiobook tts fetch kitten2
```

Review the sources, pinned revisions, download size and destination before confirming. For
unattended setup, use `tts fetch kitten2 --yes --json`. About 1.6 GB of model/decoder artifacts
are downloaded once into `$XDG_CACHE_HOME/pdf2audiobook/tts/kitten2/`, or `~/.cache/` when unset.
Optional Python dependencies require additional space. Fetch checks SHA-256 and resumes by
reusing verified whole files; interrupted partial files are discarded.

The isolated worker currently requires a POSIX environment; Windows users retain the
existing non-clone CLI behavior. Linux is the desktop target.

Inference uses the local Torch backend (CUDA when available, otherwise CPU), packed `emb4`
weights, and the pinned default decoder. Allow several GiB of working memory plus other apps;
CPU loading and generation can be slow, particularly with paging. Preparation allows up to 15
minutes; each inference request is bounded to five minutes. An overloaded CPU may need a shorter
book chunk or more available resources. Cancellation stops the isolated worker independently.

The SDK code has an Apache 2.0 license; model terms are separate. Review the
[KittenTTS 2 model license](https://huggingface.co/KittenML/kitten-tts-2/blob/c93cb7c271baa51d9ae8204d5277988906f235a2/LICENSE.md)
and the [external decoder repository](https://huggingface.co/ResembleAI/chatterbox-turbo/tree/749d1c1a46eb10492095d68fbcf55691ccf137cd).
Use a recording you are authorized to use.

## Prepare a recording

Choose a local WAV, FLAC or MP3 containing one clear speaker: **5–30 seconds**, at most **10 MiB**,
with audible speech and little background sound. The engine captures an immutable mono 24 kHz
PCM snapshot. Explicit symlinks to regular files are accepted; URLs, pipes and directories are
rejected. Relative reference paths resolve from the CLI's working directory; native pickers
provide absolute paths.

Supply a UTF-8 `.txt` transcript of the recording, up to **64 KiB**. These words condition the
voice; they are never appended to book narration. Without a transcript, only an already installed
and downloaded local Whisper model is used:

```bash
uv sync --locked --extra kitten --extra asr-whisper --extra dev
uv run pdf2audiobook asr fetch whisper
```

No model download or SDK automatic transcription is permitted during synthesis.
`voices` uses offline metadata for the eight original voices of official Kitten aliases;
custom models without a known offline catalog report no list and retain their configured voice. Startup,
configuration validation, model discovery and dry-run do not run TTS or ASR inference.

## CLI conversion and repair

```bash
uv run pdf2audiobook convert book.pdf --no-llm \
  --tts-model kitten2 --clone-voice --reference-audio /voices/speaker.wav \
  --reference-text-file /voices/speaker.txt

uv run pdf2audiobook batch ./books --tts-model kitten2 --clone-voice \
  --reference-audio /voices/speaker.wav --reference-text-file /voices/speaker.txt

uv run pdf2audiobook resynthesize ./workspace/manifest.json --chapter 2 \
  --tts-model kitten2 --clone-voice --reference-audio /voices/speaker.wav \
  --reference-text-file /voices/speaker.txt
```

Use `convert ... --dry-run --json` to validate media and selection and inspect readiness without
loading a model. Missing prerequisites are reported separately from invalid media. Cloning
conflicts with an explicit `--voice`, selected chapter `voice_id` overrides, and paragraph voice
markers. Overrides in unselected chapters do not block the run. Speed and existing pronunciation,
pause, chapter-range and narration processing still apply.

To disable inherited cloning, pass `--no-clone-voice`. Switching existing cloned audio to a
built-in voice during repair requires this explicit choice; omitted references never trigger a
silent fallback.

## Shared defaults and desktop controls

Initialize a missing configuration with `pdf2audiobook --init`. Existing files are preserved.
Add these sections to the shared TOML file:

```toml
[tts.kitten]
model = "kitten2"

[tts.voice_clone]
enabled = true
reference_audio = "/voices/speaker.wav"
reference_text_file = "/voices/speaker.txt"

[tts.profiles.BookFilenameStem]
clone_voice = true
kitten_model = "kitten2"
reference_audio = "/voices/another.wav"
reference_text_file = "/voices/another.txt"
```

Precedence is explicit CLI options, matching filename-stem profile, environment, global TOML,
then defaults. Environment variables are `PDF2AUDIOBOOK_CLONE_VOICE`,
`PDF2AUDIOBOOK_REFERENCE_AUDIO` and `PDF2AUDIOBOOK_REFERENCE_TEXT_FILE`. Replacing a recording
clears a lower-priority transcript, so it cannot accidentally use another speaker's words.
Stored paths remain inactive when cloning is disabled.

In desktop book options or **Speak again**, choose **Voice source → Clone a voice (KittenTTS 2)**,
pick a recording, and supply a transcript file or type its words. Model setup shows the download
plan before starting a cancelable run. **Settings → Voice defaults** can prepare shared defaults
in the TOML editor; review them and click **Save configuration** to persist paths. Typed transcript
drafts stay in memory, survive navigation and failed runs within the session, and are never saved
as defaults. Choosing a different recording clears the previous transcript.

## Privacy, resume and release checks

Private snapshots and transcript drafts use restricted temporary storage and are removed after
completion or cancellation. Startup removes marked abandoned jobs while preserving active jobs.
Reference paths are redacted in diagnostics and command Details; backend prints and errors are
sanitized. No microphone permission, browser inference or remote-content upload is added.

Audio identity includes canonical audio/transcript digests, model/decoder revisions, preparation,
backend versions and generation settings. Moving identical reference content preserves identity;
changing it invalidates affected speech while keeping chapter analysis and approvals. Sidecars
contain these hashes/settings, never raw audio, transcript text or conditioning embeddings.

Valid finished MP3s remain playable, packable and inspectable without the original reference or
cloning SDK. Resuming a finished conversion also needs no cloning SDK while the reference is
still present: a valid recorded identity is reused. New or stale audio still needs the reference
and SDK. ASR checking assesses narration words; it cannot establish speaker similarity. Repairs
stage replacements and keep previous audio as backups. See the [feature backlog](../PDF2AUDIOBOOK_VOICE_CLONING_TODO.md) for real CPU,
accelerator, listening, continuity and resource acceptance gates; software tests alone do not
establish voice quality.
