# Audio verification and repair

[Home](../../README.md) · [All guides](README.md)

Use these optional checks after [converting a book](getting-started.md).

- [Checking the audio with speech recognition (optional)](#checking-the-audio-with-speech-recognition-optional)

## Checking the audio with speech recognition (optional)

After conversion you can have up to three independent speech recognizers listen to each
chapter and compare what they hear with the text that was sent to the voice. Where two or more
agree that something differs (an extra phrase, a missing one, a wrong word or number), the
chapter is flagged for you to listen to. Speech recognition is evidence, not proof: a flag
means "listen here", and no flag doesn't mean the audio is perfect (it says nothing about
naturalness, pronunciation of names, or clipping). Everything runs on your machine; no audio or
text is sent anywhere. See the
[audio verification specification](../PDF2AUDIOBOOK_AUDIO_VERIFICATION_SPEC.md) for details.

### Installing the speech recognizers

Nothing here is installed by default, and ordinary conversion never loads it. Install the
recognizers you want, then fetch their models:

~~~bash
uv sync --extra kitten --extra asr        # all three; or --extra asr-whisper / asr-wav2vec2 / asr-vosk
uv run pdf2audiobook asr list             # what is installed and downloaded, and where
uv run pdf2audiobook asr fetch            # asks before downloading; or name models: asr fetch whisper vosk
~~~

(`uv sync` makes the environment match exactly what you name, so list every extra you use, such
as `kitten`.)

| Model | Family | Download | Disk | Peak RAM (CPU) | Speed on CPU / NVIDIA GPU | License |
|---|---|---|---|---|---|---|
| `whisper` | OpenAI Whisper `medium.en` | 1.5 GB | 1.5 GB | about 7 GB | 0.77 / 0.04 x real time | MIT |
| `wav2vec2` | Meta `wav2vec2-base-960h` | 378 MB | 360 MB | about 2 GB | 0.04 / 0.001 x real time | Apache-2.0 |
| `vosk` | Vosk/Kaldi `en-us-0.22-lgraph` | 131 MB | 330 MB (archive kept, plus unpacked) | about 0.6 GB | 0.2 x real time (CPU only) | Apache-2.0 |

Speeds were measured on a 20-core machine with an RTX 4070 Ti SUPER; "0.77 x real time" means
about 46 minutes of compute for an hour of audio. Whisper on a CPU is the slow, memory-hungry
one: with less than 8 GB of RAM, verify with `--models wav2vec2 vosk` instead (a result from
fewer than three models is marked partial). The `asr-whisper` and `asr-wav2vec2` extras need
PyTorch, which the `kitten` extra already installs (about 4.4 GB with its CUDA libraries); on its
own `asr-vosk` adds about 25 MB. The code is MIT (`openai-whisper`), Apache-2.0
(`transformers`, `vosk`) and BSD/Apache (PyTorch); check the model licenses above before you
redistribute weights.

Supported: Linux on x86-64 is tested (Ubuntu 22.04); the extras resolve on Python 3.11, 3.12 and
3.13. Vosk publishes wheels for Linux, macOS and Windows and PyTorch runs on all three, but only
Linux is tested. A GPU is optional: Whisper and Wav2Vec2 use an NVIDIA GPU through PyTorch when
one is available, and the CPU otherwise.

**Network.** Only `pdf2audiobook asr fetch` downloads anything, and only after it has shown
each file, its size, its source and where it will be saved, and you have said yes (`--yes` skips
the question, for scripts). It fetches from `openaipublic.azureedge.net` (Whisper),
`huggingface.co` (Wav2Vec2, at a pinned revision) and `alphacephei.com` (Vosk), checks every
file's size and SHA-256 against pinned values, and keeps nothing that doesn't match. Models go
to `~/.cache/pdf2audiobook/asr` (or `$XDG_CACHE_HOME/pdf2audiobook/asr`); set
`PDF2AUDIOBOOK_ASR_DIR` to keep them elsewhere. To remove them, delete that folder. Conversion,
`asr list` and verification never use the network.

### Checking a converted book

~~~bash
uv run pdf2audiobook verify-audio ./audiobooks/BOOK/manifest.json             # every chapter
uv run pdf2audiobook verify-audio ./audiobooks/BOOK/manifest.json --chapter 3 --details
uv run pdf2audiobook verify-audio ./audiobooks/BOOK/manifest.json --models wav2vec2,vosk --json
uv run pdf2audiobook convert book.pdf --verify-audio                          # convert, then check
~~~

`verify-audio` decodes each chapter MP3 with FFmpeg, has each ready model transcribe it (one
model at a time), and compares every transcript with the narration that was actually sent to
the voice: the chapter text with your accepted edits, pronunciations and citation handling, as
recorded when the chapter was synthesized. Options: `--chapter N` (repeatable) or
`--chapter-range START:END`; `--models` to use a subset; `--device cpu|cuda` (default: the GPU if
there is one); `--keep-transcripts` to keep full transcripts in the report; `--details` to print
the expected and heard words (by default only times and kinds are printed). `convert
--verify-audio` checks just the chapters that conversion produced, after it has finished: a
mismatch adds the warning `audio_possible_mismatch` and an `audio_verification` summary to the
result, but never changes the exit code. It can't be combined with `--dry-run`.

Each chapter gets one of four results:

- `no_mismatch_detected`: no place where two or more models heard something different.
- `possible_mismatch`: at least two model families heard the same difference at the same place,
  such as an extra phrase, a missing sentence or a different word or number. "The same place"
  means within two words of the first difference found there, so a run of separate differences
  never adds up to agreement. Listen at the time shown; it is evidence, not proof.
- `model_disagreement`: only one model heard a difference there; usually that model's mistake
  (for example Vosk hearing "go" for an unusual name). Worth a listen only if you want to be
  thorough.
- `verification_unavailable`, with a reason: `audio_missing`, `audio_stale` (the MP3 or its
  text changed since synthesis), `narration_not_spoken` (the chapter text or a pronunciation
  changed since the chapter was spoken, so the audio isn't compared against text it doesn't
  contain; speak the chapter again first), `audio_undecodable` (FFmpeg couldn't read the MP3;
  the source is left alone), `no_models`, `unsupported_language` (only English voices are
  checked), or `cancelled`. Without FFmpeg, the report's `warnings` holds `ffmpeg_missing` and
  every chapter is `audio_undecodable`.

A result based on fewer than three models is marked `partial` (for example when one isn't
installed or fails on a chapter: a failing model abstains, it is never counted as a vote). A
model that isn't ready is listed with `model_not_installed` or `model_not_downloaded`. Small
transcription noise is ignored: differences of one short word, near-misses such as "boat" for
"boats", British and American spelling, compounds written as one word or two, and number
formats ("1987" is the same as "nineteen eighty seven"); a different number always counts.

`verify-audio` exits 0 whenever it ran, whatever it found; it exits non-zero only for errors (a
locked or unreadable book, an interruption: Ctrl+C exits 130 and keeps what had finished).
With `--json` it prints the book's whole verification state, also saved to
`reports/audio_verification.json` (`desktop/contracts/audio-verification.schema.json`):
`schema_version`, `created_at`, `completed_at` (null if interrupted), `keep_transcripts`, the
`models` with their pinned revisions and package versions, a `summary` of chapters by status,
and per chapter its `status`, `reason`, `partial`, the `audio_sha256` and `reference_sha256` it
was judged against (a later change to either makes the result stale), each model's `outcome`,
and its `flags`: `kind`, `confirmed`, the `models` that heard it, `expected`, `heard` per model,
a few words `before` and `after`, `start`/`end` in seconds, and `reviewed`. Results for chapters
you didn't check this time are kept from earlier runs.

**Privacy.** The report contains book text (the flagged excerpts, and full transcripts only with
`--keep-transcripts`), so it stays in the book's folder and is never logged or sent anywhere;
progress and errors hold no book text. Delete `reports/audio_verification.json` to remove it.

**Transcript retention.** Full transcripts are kept only by a run that says `--keep-transcripts`.
A run without it removes full transcripts from every chapter of the report it rewrites, including
chapters it didn't verify, and the report's `keep_transcripts` field is true only while some
chapter still holds transcripts. Reads (`audio-report show`, and the desktop app) never show full
transcripts, whichever run kept them; excerpts and vote metadata are always shown. A report
written before this rule still has its old transcripts until the next verification or review
mark rewrites it, and reads hide them from the start: no other migration is needed.

**Memory.** Chapter audio is streamed in windows of at most 30 seconds, with a search of the last
5 seconds of each window for the quietest moment to cut, so the audio held in memory at once is
about 1.9 MB (one window of 16 kHz float32 samples, plus a transient copy while a block is
added) however long the chapter is. The decoded 16 kHz WAV is kept in a temporary folder while
the chapter is checked and removed afterwards; it takes about 32 KB per second of audio on disk.
The recognizer's own memory is separate (see the table above).

**Limits.** Only English is supported. The models listen to the narration as text; they can't
tell whether it sounds natural, whether a name is pronounced the way you want, or whether there
is clipping or distortion. Accuracy was measured on synthetic Kitten speech (spec §13), not on
recordings.

**Reading the saved report later.** `audio-report show MANIFEST [--json]` prints the saved
report without loading any model, and lists the chapters whose result is out of date because
their audio, text, pronunciations or the pinned model revisions changed
(`desktop/contracts/audio-report.schema.json`: `report`, null before the first check, and
`stale`). After listening to a flagged passage that sounds right, mark it reviewed with
`audio-report dismiss MANIFEST --chapter N --flag I` (`I` counts from 0 in the chapter's `flags`;
`--undo` reverses it). That changes no audio or text, and the mark survives checking the same
audio again.

**In the desktop app** the same check is a switch in the book's options and an *Audio check*
panel with *Verify existing audio*, the flagged passages, *Listen*, *Sounds right* and *Speak
again…*; see [desktop/README.md](../../desktop/README.md#checking-the-audio).

### Fixing a flagged chapter

Nothing is changed automatically; you choose. First listen at the time shown. Then:

- **It sounds right:** leave it. A flag is evidence, not proof.
- **The voice slipped** (a garbled or repeated phrase): speak the chapter again, with the same or
  another voice or speed. Only that chapter is synthesized; analysis isn't repeated.

  ~~~bash
  uv run pdf2audiobook resynthesize ./audiobooks/BOOK/manifest.json --chapter 3
  uv run pdf2audiobook resynthesize ./audiobooks/BOOK/manifest.json --chapter 3 --voice Luna --speed 0.95
  ~~~

- **A word is pronounced wrongly** (a name, an abbreviation): add a pronunciation to
  `~/.config/pdf2audiobook/config.toml` and speak the chapter again:

  ~~~toml
  [tts.pronunciations]
  "Quill" = "Kwill"
  ~~~

- **The text itself is wrong** (an OCR error, a misread number): correct the chapter text as in
  [Editing chapter text](editing-and-review.md#editing-chapter-text) or on the [review page](getting-started.md#step-4-review-the-chapters-in-your-browser),
  then speak the chapter again.

`resynthesize` makes the new MP3 in `audio/.staging/` and replaces the chapter's MP3 only once
it is encoded and checked; the previous MP3 and its `.cache.json` are kept in `audio/.backup/`
(the three most recent per chapter). To go back, copy a backup pair over the chapter's MP3 and
`.cache.json`. If the chapter was verified before, it is verified again afterwards
(`--no-verify-audio` skips that); otherwise add `--verify-audio`. The cover art already in the
chapter's MP3 is kept unless you pass `--cover`. A chapter voice set on the review page wins over
`--voice` (the result then warns `chapter_voice_overrides_option`).

`resynthesize` repairs audio. It is not `regenerate-chapter`, which rewrites a chapter's *text
file* from the manifest after a conflict; that never touches audio. After changing a chapter's
text, pronunciations or voice, its earlier verification result is reported stale until you
verify again.
