# PDF2Audiobook: installation, usage and maintainer guide

This guide documents the **current Python CLI implementation**, not a promise of
production-quality recognition or narration. Read
[`PDF2AUDIOBOOK_SPEC.md`](PDF2AUDIOBOOK_SPEC.md) for normative requirements and
[`PDF2AUDIOBOOK_TODO.md`](PDF2AUDIOBOOK_TODO.md) for incomplete acceptance.

## Prerequisites and reproducible development environment

Python 3.11+, [uv](https://docs.astral.sh/uv/), FFmpeg and (for scanned PDFs)
Tesseract with the requested language data are required. On Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg tesseract-ocr tesseract-ocr-eng
uv python install 3.11
uv sync --extra dev
uv run pdf2audiobook doctor --json
```

For other OCR languages, install the corresponding system package (for example
`tesseract-ocr-fra` for French) and set `pdf.ocr_language` or
`PDF2AUDIOBOOK_OCR_LANGUAGE`. Check the `ocr_missing_languages` field from
`doctor --json` before converting a scan. FFmpeg must be on `PATH`.

For actual speech synthesis, install the optional Kitten package:

```bash
uv sync --extra dev --extra kitten
uv run pdf2audiobook doctor
```

Kitten model weights may be downloaded on first synthesis; allow disk space and
network access for that first run. Supported aliases are `mini`, `micro` and
`nano`, mapped in `src/pdf2audiobook/tts/__init__.py`; a full model ID can
also be selected. The default voice is `Jasper`. The actual model/voice must
be available to the installed Kitten version. Offline CI mocks Kitten; it does
**not** validate the real model's audio quality or download path.

The project uses `uv sync` to manage `.venv`; do not manually install
dependencies into the system interpreter. The committed `uv.lock` pins the
default, `dev` and `kitten` dependency graphs; install with
`uv sync --locked --extra dev` and regenerate deliberately with `uv lock`
when changing dependencies, as a separate, tested change.

## CLI workflows

Inspect PDF metadata, page labels, geometry, bookmarks and per-page text-layer
counts (characters and images only, no book text; `image_only_pages` hints at
OCR needs) without TTS:

```bash
uv run pdf2audiobook inspect book.pdf --json
uv run pdf2audiobook config show --sources --json
uv run pdf2audiobook doctor --json
```

Analyze with no LLM and review the resulting manifest/chapter text before
synthesis. For books with no confident chapter boundaries, review the
single-chapter output and explicitly opt in:

```bash
uv run pdf2audiobook analyze book.pdf --no-llm --output ./audiobooks --json
uv run pdf2audiobook convert book.pdf --no-llm --dry-run --json
uv run pdf2audiobook convert book.pdf --no-llm --allow-single-chapter
```

Convert only a selected chapter or an inclusive, 1-based chapter range:

```bash
uv run pdf2audiobook convert book.pdf --no-llm --chapter 2 --voice Jasper --speed 1.1
uv run pdf2audiobook convert book.pdf --no-llm --chapter-range 2:5 --bitrate 128k
uv run pdf2audiobook convert book.pdf --no-llm --chapter 2 --force
uv run pdf2audiobook convert book.pdf --no-llm --no-resume
```

`--dry-run` can still write analysis files and invoke OCR, but does not
synthesize audio. `--force` regenerates selected MP3s. `--no-resume` bypasses
the existing analysis/audio reuse path; **neither option authorizes overwriting
manually approved analysis**. Preserve a backup and use a different `--output`
directory if a new analysis would invalidate approved edits.

To use OCR explicitly, set `--ocr always` or `--ocr never`; `auto` uses
embedded text when usable and OCR otherwise. A PDF password is read from a
named environment variable, not a command-line password argument:

```bash
export BOOK_PASSWORD='replace-with-private-password'
uv run pdf2audiobook inspect encrypted.pdf --pdf-password-env BOOK_PASSWORD
uv run pdf2audiobook analyze scanned.pdf --no-llm --ocr always
```

Avoid storing passwords or copyrighted source text in shared logs.

### Optional local and remote LLMs

The built-in default provider is Ollama at `http://127.0.0.1:11434/v1`
with model `qwen3.5:9b`. Start the service and ensure that model is installed
before using model-assisted analysis:

```bash
ollama pull qwen3.5:9b
ollama serve
uv run pdf2audiobook analyze book.pdf --llm-provider ollama --llm-model qwen3.5:9b
```

Ollama silently drops the start of a prompt longer than the context it
serves (a plain `qwen3.5:9b` pull is served with 4096 tokens), so before the
first uncached request the adapter loads the model with an empty prompt, reads
its `context_length` from `/api/ps`, and refuses any request whose
conservative byte bound plus output reserve exceeds the smaller of that and
`llm.max_context_tokens`. Use a variant with a larger `num_ctx` (for example a
Modelfile with `PARAMETER num_ctx 131072`) or lower `llm.chunk_tokens`. Fully
cached reruns do not contact Ollama.

For a local OpenAI-compatible `llama-server` listening on loopback:

```bash
uv run pdf2audiobook analyze book.pdf --llm-provider llama-server \
  --llm-model auto --llm-url http://127.0.0.1:8080/v1
```

For OpenAI, book text is transmitted to an external service **only after
explicit remote-content consent**. Review the book's rights and privacy
requirements first; set the API key only in the environment:

```bash
export OPENAI_API_KEY='replace-with-private-key'
uv run pdf2audiobook analyze book.pdf --llm-provider openai \
  --allow-remote-content
```

Non-loopback plain HTTP is prohibited even with consent. Local `--no-llm`
is available for deterministic analysis, and no provider is required for
`inspect`, `doctor` or `config show`. LLM heading and OCR-cleanup
suggestions are untrusted proposals; source anchors are validated and
non-deterministic cleanup edits remain unapproved until reviewed. A cleanup
proposal is kept for review only when every change is a known OCR glyph
confusion (`b00k`, `tlie`, `rn`/`m`, ligatures, long s) or a split/joined
word; rewording, tense, case, quote style, punctuation and completing a
hyphenated word from the next line are rejected as `not_ocr_correction`.

## Configuration and precedence

On Linux, the optional default configuration file is
`~/.config/pdf2audiobook/config.toml` (or under `XDG_CONFIG_HOME`).
An explicit `--config FILE` selects a different file, while `--no-config`
ignores TOML. Configuration precedence is CLI > `PDF2AUDIOBOOK_*`
environment > TOML > built-in defaults, including explicit boolean `false`.

Example TOML (contains no secrets):

```toml
[general]
output_dir = "./audiobooks"
resume = true

[pdf]
ocr = "auto"
ocr_language = "eng"
ocr_dpi = 300
remove_page_numbers = true
# warn: keep PDF position; inline: after the anchoring paragraph;
# end: after the chapter body; omit: audited exclusion
footnotes = "warn"

[chapters]
min_boundary_confidence = 0.75
allow_single_chapter = false

[llm]
enabled = false
provider = "ollama"
allow_remote_content = false
structure = true
cleanup = true

[llm.ollama]
model = "qwen3.5:9b"
base_url = "http://127.0.0.1:11434/v1"

[tts]
provider = "kitten"
bitrate = "128k"
sample_rate = 24000
pause_ms = 250

[tts.kitten]
model = "mini"
voice = "Jasper"
speed = 1.0
```

Use `uv run pdf2audiobook config show --sources --json` to see the
effective values and their provenance. Provider key configuration stores
**environment variable names**, not secret values. Examples of supported
environment overrides include `PDF2AUDIOBOOK_LLM_ENABLED=false`,
`PDF2AUDIOBOOK_OCR_LANGUAGE=fra`,
`PDF2AUDIOBOOK_LLM_PROVIDER=llama-server`, and
`PDF2AUDIOBOOK_ALLOW_REMOTE_CONTENT=false`.

## Workspace, review and cache contracts

The analysis directory is
`<output_dir>/<source-stem>-<first-10-hex-of-input-SHA256>/`. Important files:

- `manifest.json`: versioned `BookManifest` with immutable source spans,
  ordered blocks, proposed/accepted cleanup edits, chapter boundaries and
  warnings.
- `chapters/001.txt` and subsequent chapter text: derived from the manifest.
- `coverage.json`: chapter/prose coverage audit produced by the renderer.
- `*.mp3` and adjacent `*.cache.json`: final audio and fingerprint/hash
  records.
- `.cache/ocr/` and `.cache/tts/`: page recognition and checksum-validated
  WAV chunks; `.cache/tts/progress/` contains text-free synthesis ledgers.

Inspect `manifest.json`, `coverage.json`, warnings and chapter text against
the original PDF before listening or distributing. The schema currently
**rejects** unsupported versions; it does not auto-migrate manifests.
Manifest schema v2 is required after the review-fixes release. Existing v1
workspaces are intentionally rejected; re-run `analyze` with a fresh output
directory to create a v2 workspace.
Extraction/analysis fingerprint v19 invalidates prior analysis after safer OCR,
pagination, heading and line-wrap classification. Existing v2 workspaces are
re-analyzed on resume; manually approved workspaces remain protected, so use a
fresh output directory when intentionally replacing approved analysis.
The per-book LLM budget ledger schema v2 adds an `unbilled` state and reads v1
ledgers in place; ambiguous sent requests remain unresolved until reviewed with
the `budget` command.
LLM decision auditing writes `reports/llm_decisions.json`; the cleanup audit is
schema v2 and stores only sanitized IDs, hashes and fixed summaries/reason codes.
`BookManifest.approved` and `Chapter.manually_approved` prevent accidental
destructive reanalysis. Only explicitly accepted, source-anchored
`CleanupEdit` entries affect derived text. OCR and pagination heuristics can
still make mistakes, especially on multi-column layouts, footnotes, tables,
captions and mathematical content.

## Architecture and extension points

The executable `pdf2audiobook` maps to `pdf2audiobook.cli:app`
(`src/pdf2audiobook/cli.py`). Modules and their boundaries:

1. `config.py`: strict Pydantic TOML/env/CLI settings, provenance and
   validation; `errors.py` and `logging.py` provide domain diagnostics and
   privacy-safe structured events.
2. `pdf.py` and `reading_order.py`: `DocumentExtractor` protocol with the
   default `PyMuPDFExtractor`; PyMuPDF inspection, embedded/OCR extraction,
   provenance, geometry and conservative column-order decisions.
3. `models.py` and `document/structure.py`: source-aligned models,
   pagination edits, chapter proposals, coverage checks and chapter rendering.
4. `llm/__init__.py`: `LLMProvider` protocol and OpenAI-compatible HTTP
   transport, endpoint validation, structured proposals and deterministic
   proposal verification. PDF text is untrusted user content, not instructions.
5. `tts/__init__.py`: `TTSProvider` protocol and lazily loaded Kitten
   adapter; `audio/__init__.py`: `AudioEncoder` protocol, source-aligned
   chunks, WAV validation, PCM assembly, FFmpeg MP3 encoding (`encode_mp3`)
   and ID3 metadata.
6. `workspace.py`: SHA-256 identities and atomic JSON writes;
   `pipeline.py`: analysis, approved-edit protection, stage fingerprints,
   chapter selection, resumable synthesis and output checksums.

Typical call path:
`cli.analyze -> pipeline.analyze_book -> pdf.extract_pdf ->
document.structure -> optional llm -> workspace.write_manifest`.
Conversion additionally calls `pipeline.convert_book -> tts.KittenProvider` or
`tts.PiperProvider` ->
audio.synthesize_chunks -> audio.encode_mp3`. The TTS model is not loaded
for an up-to-date cached MP3. `analyze_book`/`convert_book` accept
`extractor=`, `tts_provider=` and `encoder=` replacements; an injected adapter
is folded into the analysis, chunk and MP3 cache identities so it never reuses
artifacts made by the defaults.

**Change safety:** Preserve raw spans/blocks and the one-time prose-coverage
invariant. Introduce schema versions or migrations deliberately; update
analysis/audio fingerprints when changing derived semantics. Keep the LLM
transport consent gate and the separation between untrusted model proposals
and accepted edits. Verify output reuse by fingerprint **and** file checksum,
not by filename or progress-ledger status alone. Test provider failures with
mock transports and audio with synthetic signals before real-model acceptance.

## Development, CI and troubleshooting

```bash
uv lock --check
uv sync --locked --extra dev
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev mypy
uv run --extra dev pytest -q
uv run --extra dev pdf2audiobook --help
uv run --extra dev pdf2audiobook doctor --json
```

Ruff formatting is enforced repository-wide. Mypy checks the explicit `[tool.mypy].files` list in
`pyproject.toml`; add every new module there. Third-party libraries that print
to stdout (PyMuPDF messages, kittenml's per-chunk echo) are silenced or routed
to stderr at their adapter so `--json` output stays parseable and narration
text never reaches logs.

`.github/workflows/ci.yml` runs these offline checks on `master`, installing
FFmpeg, Tesseract and English language data. The apt install is time-bounded,
retried against archive.ubuntu.com and served from an `actions/cache` of the
`.deb` files (bump the `apt-…-v1` key when the package list changes), because
the runners' regional mirror intermittently stalls for hours. It does **not** install Kitten
models, call external LLMs, or validate all real scanned-book layouts. Record
the exact commit SHA and Actions run when claiming CI acceptance. Before
marking a TODO complete, add a deterministic regression test or explicitly
document environment-dependent/manual acceptance evidence.

If OCR is missing or produces almost no text, check `doctor --json`, OCR
language packs and `--ocr` mode; inspect extracted source spans. If chapters
are unexpectedly merged or rejected, inspect `manifest.json` warnings,
`coverage.json` and confidence thresholds; use
`--allow-single-chapter` only after review. If a local LLM is unreachable,
verify the server URL/model and retry with `--no-llm` to isolate extraction.
If audio is stale, inspect the chapter's `*.cache.json` and rerun with
`--force`; checksum-invalid chunks should be regenerated. If a manually
approved manifest blocks reanalysis, preserve it and use a new output
directory. If FFmpeg or Kitten is unavailable, install the missing dependency
and check `doctor` before rerunning. Keep secrets and full book text out of
bug reports.

## Outstanding release gates

The TODO remains authoritative: capable-model
LLM, llama-server and consented OpenAI acceptance, human listening review of
real Kitten audio, and real-book/difficult-scan special-material qualification
are still outstanding. Documentation and offline CI
passing do not close these gates.
