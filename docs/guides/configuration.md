# Configuration

[Home](../../README.md) · [All guides](README.md)

Use a TOML file for recurring settings and command flags for one-off changes. No config file
is required: omitted fields use built-in defaults. The [starter config](config.example.toml)
selects local Kitten speech and disables LLM assistance for an initial run.

- [Create your config file](#create-your-config-file)
- [Check the effective settings](#check-the-effective-settings)
- [Override settings](#override-settings)
- [Common settings](#common-settings)
- [Password-protected PDFs](#password-protected-pdfs)
- [Troubleshooting](#troubleshooting)

## Create your config file

The default path is `~/.config/pdf2audiobook/config.toml`. An absolute `XDG_CONFIG_HOME` changes
it to `$XDG_CONFIG_HOME/pdf2audiobook/config.toml`; a relative value is ignored.
From the repository root, copy the starter file without replacing an existing config:

```bash
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/pdf2audiobook"
mkdir -p "$config_dir"
cp -n docs/guides/config.example.toml "$config_dir/config.toml"
```

Use an absolute `XDG_CONFIG_HOME` or leave it unset before running those commands. Open
`config.toml` in your editor. For example, to change the voice, edit its existing table:

```toml
[tts.kitten]
model = "mini"
voice = "Luna"
speed = 1.05
```

Merge settings into existing tables rather than pasting a second `[tts.kitten]` or `[llm]`
header: TOML rejects duplicate tables. An output directory such as `./audiobooks` is relative
to the directory where you run the CLI.

## Check the effective settings

```bash
uv run pdf2audiobook config show --sources
uv run pdf2audiobook config show --sources --json
uv run pdf2audiobook doctor
```

`config show` validates the file and displays the merged values; `--sources` identifies each
value's origin. `doctor` checks installed programs, OCR languages and selected providers.
It does not synthesize audio or test an LLM request. For a local Ollama context check, use
`doctor --check-llm` after [setting up the model](llm.md#using-a-local-llm-ollama); this loads
the model.

## Override settings

Priority, highest first: **command flags → `PDF2AUDIOBOOK_*` environment variables → TOML →
built-in defaults**. Explicit `false` values override lower-priority `true` values.

Select another config with `--config FILE`, or skip the file with `--no-config`. These options
belong after the command (after `config show` for that subcommand), and cannot be combined:

```bash
uv run pdf2audiobook config show --config ./my-config.toml --sources
uv run pdf2audiobook convert book.pdf --config ./my-config.toml --no-llm
uv run pdf2audiobook config show --no-config --sources
```

`--no-config` still applies environment variables. An explicitly selected file must exist;
an absent default file is fine. Examples of supported environment overrides:

```bash
export PDF2AUDIOBOOK_OCR_LANGUAGE=eng
export PDF2AUDIOBOOK_TTS_VOICE=Luna
export PDF2AUDIOBOOK_LLM_ENABLED=false
```

`convert book.pdf --voice Jasper` overrides the environment's voice for that run. Paired
boolean flags such as `--llm/--no-llm` and `--resume/--no-resume` override settings only when
you supply a direction. `config show` reports its own effective configuration; it does not
include flags passed to a separate conversion command. Per-book and per-chapter voice
selection has additional rules; see [voices and speech](voices.md).

## Common settings

| TOML section | Settings and details |
|---|---|
| `[general]` | `output_dir`, `resume`, `progress`, `heartbeat_seconds`; see [progress](cli.md#progress-and-time-estimates) |
| `[pdf]` | `ocr` (`auto`, `always`, `never`), `ocr_language`, `footnotes` (`warn`, `inline`, `end`, `omit`), page-number cleanup |
| `[tts]`, `[tts.kitten]`, `[tts.piper]` | Provider, bitrate, sample rate, model, voice and speed; see [voices](voices.md) |
| `[tts.profiles."My Book"]`, `[tts.pronunciations]` | Per-book voice settings and spoken word replacements; see [examples](voices.md#piper-and-other-settings) |
| `[llm]`, `[llm.ollama]` | Enable assistance, select a model, set context/output limits and timeouts; see [LLM setup](llm.md) |
| `[llm.openai]`, `[llm.llama_server]` | Other providers; set `[llm] provider` to `"openai"` or `"llama-server"` |
| `[reading]` | Citation skipping and approved equation readings; see [citations and equations](editing-and-review.md#citations-and-equations) |
| `[audio]` | `cover_image` supplies default JPEG/PNG artwork, up to 5 MiB |

The starter config disables LLM assistance. To use Ollama, change `[llm] enabled` to `true`
and follow [the local LLM guide](llm.md#using-a-local-llm-ollama) to install and size the model.
Keep API keys in environment variables; provider `api_key_env` fields hold a variable name,
such as `"OPENAI_API_KEY"`. Remote book content requires explicit consent; see
[local and remote provider setup](llm.md#other-providers).

## Password-protected PDFs

Supply the **name of an environment variable**, not the password itself:

~~~bash
export BOOK_PDF_PASSWORD='your PDF reader password'
uv run pdf2audiobook inspect encrypted.pdf --pdf-password-env BOOK_PDF_PASSWORD
uv run pdf2audiobook convert encrypted.pdf --no-llm --pdf-password-env BOOK_PDF_PASSWORD
~~~

You can also configure `[pdf] password_env = "BOOK_PDF_PASSWORD"` in TOML. Never commit the password
itself or pass it directly as a command-line argument. The raw password is neither persisted in the
manifest nor included in configuration diagnostics. The `doctor` command lists installed Tesseract
language packs and reports any missing languages requested by the configuration.

## Troubleshooting

- **Invalid TOML syntax:** check quotes, table headers and duplicate tables. Repeated settings
  should update the existing table.
- **Invalid configuration values:** check names and types. Unknown keys are rejected; for
  example, use `[llm.llama_server]` in TOML even though the provider value is `"llama-server"`.
- **A change has no effect:** inspect `config show --sources` for an environment override or
  unexpected file. Check flags used by the actual command too.
- **Equation processing needs the LLM:** leave `reading.process_equations` omitted when
  disabling the LLM, or set it to `false`. Explicit `true` requires LLM assistance.
- **Missing speech or OCR support:** follow [installation](getting-started.md#installation)
  and rerun `doctor`. Editing config does not install providers or model files.
