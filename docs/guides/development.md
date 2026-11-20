# Development and validation

[Home](../../README.md) · [All guides](README.md)

See [installation](getting-started.md#installation) for environment setup and
[AGENTS.md](../../AGENTS.md) for contribution conventions. For development without speech
models, use `uv sync --locked --extra dev`. Include `--extra kitten` whenever you sync an
environment that also needs synthesis.

The committed `uv.lock` pins the default, `dev`, and optional `kitten` dependency graphs.
When changing dependencies, regenerate it with `uv lock` and review the diff.

- [Linting, type checking and tests](#linting-type-checking-and-tests)
- [Opt-in live LLM provider smoke tests](#opt-in-live-llm-provider-smoke-tests)

## Linting, type checking and tests

These are the same checks CI runs (`.github/workflows/ci.yml`). Run them all before committing:

~~~bash
uv lock --check                        # the lockfile matches pyproject.toml
uv run --extra dev ruff check .        # lint, including import sorting
uv run --extra dev ruff format --check . # formatting (use `ruff format .` to fix)
uv run --extra dev mypy                # type check the files listed in pyproject.toml
uv run --extra dev pytest -q -ra       # the full test suite, with a summary of skips
~~~

- **Formatting:** `uv run --extra dev ruff format .` rewrites files in place;
  `ruff check --fix .` fixes import order.
- **Type checking:** CI runs mypy once per Python version. To match it, also run
  `uv run --extra dev mypy --python-version 3.12` and `--python-version 3.13`. When you add a
  module under `src/`, add it to `[tool.mypy].files` in `pyproject.toml`.
- **One test file or test:** `uv run --extra dev pytest tests/test_review_ui.py -q`, or add
  `-k name` to select by name.
- **Skipped tests:** tests that need FFmpeg, Tesseract or Node skip when the program is missing.
  Read the `-ra` summary at the end of the run to see what was skipped and why.
- **No network:** the test suite never needs the network or a running LLM. Live LLM checks are
  separate and opt-in (see [the smoke tests](#opt-in-live-llm-provider-smoke-tests)).

CI also runs a CLI smoke test (`--help`, `config show --json`, `doctor --json`) and installs the
built wheel and sdist into a clean virtual environment.

## Opt-in live LLM provider smoke tests

These are **never run by offline CI**. Each command sends only a small synthetic
fixture (no PDF content) to the selected endpoint. The `--execute` switch is
required even for loopback servers:

~~~bash
uv run python -m pdf2audiobook.llm.smoke --provider ollama --model qwen3.5:9b --execute
uv run python -m pdf2audiobook.llm.smoke --provider llama-server --model auto --execute
~~~

For OpenAI, set `OPENAI_API_KEY` in the environment first and additionally
provide explicit remote-content consent:

~~~bash
uv run python -m pdf2audiobook.llm.smoke --provider openai --model gpt-4.1-mini --execute --allow-remote-content
~~~

Model identifiers are examples, not guarantees that those models are installed
or available. The runner returns a JSON success/error result with sanitized
provider details and usage metadata, but never echoes the synthetic request
body or credentials. Real backend acceptance remains pending until these
checks are executed against actual reachable services.

## Voice cloning acceptance

Offline coverage uses `tests/test_voice_cloning*.py`, shared JSON contracts, Rust bridge/lifecycle
fixtures and desktop clone controls. Native coverage uses the actual CLI and FFmpeg with an
explicit synthetic backend: `E2E_CLONE=1 npm --prefix desktop run e2e` (provide the app/driver
paths described in the desktop guide). This exercises selection, typed drafts, resume, repair,
cancellation and private-file cleanup without a real speaker or model.

Real-model tests remain opt-in. Install the optional Kitten dependencies, explicitly fetch the
model, and supply an authorized reference and its transcript outside the repository:

```bash
PDF2AUDIOBOOK_TEST_CLONE_REFERENCE=/private/speaker.wav \
PDF2AUDIOBOOK_TEST_CLONE_TRANSCRIPT=/private/speaker.txt \
PDF2AUDIOBOOK_TEST_CLONE_OUTPUT=/private/acceptance-audio \
uv run --extra kitten --extra dev pytest -q tests/test_voice_cloning_real.py
```

Set `PDF2AUDIOBOOK_TEST_CLONE_LONG_FORM=1` to also generate the longer, multi-chunk
continuity sample under the chosen output directory. It validates assembly and chunk completion;
listen separately for consistent speaker identity and transitions.

Without a transcript this needs an already ready local Whisper installation. No model is fetched
by the test. Repeat on CPU and an available supported accelerator; measure cold/warm runtime,
peak memory, stopping inference and selective repair. Listen to reference similarity and chunk
continuity, including a long-form book. Record actual results in the feature TODO and leave
unavailable hardware or listening checks open. ASR word accuracy cannot replace that review.

The Rust request builder also has an opt-in real-model bridge test. Set
`PDF2AUDIOBOOK_TEST_CLONE_CLI` to a CLI executable whose environment already contains the
optional dependencies, plus the reference/transcript variables above, then run
`cargo test --manifest-path desktop/src-tauri/Cargo.toml clone_bridge_real_model -- --ignored`.
It generates a text PDF, converts it, and checks warm reuse. This is separate from
`cargo test -- --ignored real_cli`, which uses synthetic speech for bridge coverage.
