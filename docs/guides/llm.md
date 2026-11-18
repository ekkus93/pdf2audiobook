# LLM assistance

[Home](../../README.md) · [All guides](README.md)

Start with [configuration setup](configuration.md) to create your TOML file. LLM assistance
uses local Ollama by default; `--no-llm` runs without a model. If you copied the starter config,
change `[llm] enabled` to `true` or pass `--llm` when following the examples below.

- [Using a local LLM (Ollama)](#using-a-local-llm-ollama)
- [Other providers](#other-providers)
- [Explicit fallback when a local LLM is unavailable](#explicit-fallback-when-a-local-llm-is-unavailable)
- [LLM response cache and privacy](#llm-response-cache-and-privacy)
- [Optional LLM token and dollar limits](#optional-llm-token-and-dollar-limits)
- [LLM context and completion capacity](#llm-context-and-completion-capacity)
- [LLM request timeout](#llm-request-timeout)
- [Optional visual review](#optional-visual-review)

## Using a local LLM (Ollama)

LLM assistance is on by default and uses Ollama on `127.0.0.1`. Book text never leaves your
machine unless you choose a remote provider and pass `--allow-remote-content`.

1. Install [Ollama](https://ollama.com) and pull a model, for example `ollama pull qwen3.5:9b`.
2. **Give the model a large enough context.** Before uploading any text, pdf2audiobook asks Ollama
   what context the model really serves, and refuses the run if a request would not fit ("LLM
   request exceeds the context length the Ollama server serves"). A plain model tag often has
   a small default context, so create a variant with a larger `num_ctx`:

   ~~~bash
   printf 'FROM qwen3.5:9b\nPARAMETER num_ctx 262144\n' > Modelfile
   ollama create qwen35-256k -f Modelfile
   ~~~

3. **Allow room for reasoning.** Thinking models such as qwen3.5 spend output tokens on reasoning
   before they answer. The default cap of 1024 is too small for them ("LLM answer was cut off at
   the output cap"); use 32768.
4. Convert with those settings:

   ~~~bash
   uv run pdf2audiobook --heartbeat 60 convert book.pdf \
     --llm-model qwen35-256k:latest --llm-context-tokens 262144 --llm-output-tokens 32768
   ~~~

   The book is sent in windows of about 4,000 bytes (`llm.chunk_tokens`), never all at once.
   Each window also needs room for the output cap, so the served context must be larger than
   the output cap plus the window. `--heartbeat 60` prints a status line every minute. As a
   rough guide, a 15-page paper took about 100 requests and 7 minutes on a 16 GB GPU.

5. **Approve the LLM's proposals.** Proposed cleanups and equation readings are stored as
   *pending* edits and are not used until you accept them:

   ~~~bash
   uv run pdf2audiobook edits list audiobooks/BOOK/manifest.json
   uv run pdf2audiobook edits accept audiobooks/BOOK/manifest.json --all
   ~~~

   Then run `convert` again to regenerate the affected chapters. See
   [Citations and equations](editing-and-review.md#citations-and-equations).

Put settings you use every time in `~/.config/pdf2audiobook/config.toml` instead of repeating the
flags; `uv run pdf2audiobook config show --sources` shows the effective settings and where each
came from:

~~~toml
[llm]
enabled = true
max_context_tokens = 262144
max_output_tokens = 32768

[llm.ollama]
model = "qwen35-256k:latest"
~~~

For consented non-loopback endpoints, a one-time stderr warning identifies the provider,
selected model, and current analysis block-window scope before uploading book text.
Local loopback analysis does not emit the remote-upload warning. See the
[specification](../PDF2AUDIOBOOK_SPEC.md) for privacy and audit requirements.

## Other providers

For a local OpenAI-compatible `llama-server` listening on loopback:

```bash
uv run pdf2audiobook analyze book.pdf --llm --llm-provider llama-server \
  --llm-model auto --llm-url http://127.0.0.1:8080/v1
```

To save that selection, merge these settings into your config:

```toml
[llm]
enabled = true
provider = "llama-server"

[llm.llama_server]
model = "auto"
base_url = "http://127.0.0.1:8080/v1"
```

For OpenAI, set `OPENAI_API_KEY` in your shell or secret manager, then explicitly consent
to sending book text:

```bash
uv run pdf2audiobook analyze book.pdf --llm --llm-provider openai --allow-remote-content
```

Keep the key out of TOML: `[llm.openai] api_key_env = "OPENAI_API_KEY"` names the environment
variable to read. Remote endpoints require consent and HTTPS; non-loopback plain HTTP is
prohibited even with consent. No provider is needed for `inspect`, `doctor` or `config show`.
The [development guide](development.md#opt-in-live-llm-provider-smoke-tests) describes opt-in
checks with synthetic fixtures.

## Explicit fallback when a local LLM is unavailable

By default, LLM provider errors stop analysis with a typed diagnostic; the program
does **not** silently switch providers or downgrade analysis. For an offline-only
workflow, use `--no-llm`. To allow automatic deterministic fallback *only when
a configured LLM request fails*, set the following in your config file:

~~~toml
[llm]
fallback_to_deterministic = true
~~~

Alternatively set `PDF2AUDIOBOOK_LLM_FALLBACK_TO_DETERMINISTIC=true`.
The fallback discards partial model suggestions, preserves original book text
and unrelated review warnings, and records the fallback in the manifest.
Boundary confidence still requires review where applicable. A remote provider
continues to require explicit `--allow-remote-content` consent.

## LLM response cache and privacy

LLM analysis responses are cached locally under each book workspace at
`.cache/llm/`, with keys derived from the full request, prompt and provider
identity. Cache hits still pass the same deterministic source/ID verification
as fresh provider responses. Malformed or mismatched records are not trusted.
`--no-resume` disables cache reuse; turning off the cache in configuration
does likewise. Cache files can contain model-generated text derived from the
book and should be protected like the original PDF. Optional per-book request,
provider-reported token and estimated dollar limits are enforced through the
persistent budget ledger described below.

## Optional LLM token and dollar limits

Boolean CLI overrides accept either direction and default to unset, so
configuration still applies unless you pass a flag. The paired forms include
`--llm/--no-llm`, `--allow-remote-content/--no-allow-remote-content`,
`--vision/--no-vision`, `--allow-single-chapter/--no-allow-single-chapter`,
`--resume/--no-resume` and (for `batch`) `--recursive/--no-recursive`.

Set the following in your TOML config under `[llm]`:

~~~toml
[llm]
max_requests = 12
max_reported_tokens = 20000
max_estimated_cost_usd = 0.15
input_cost_usd_per_million_tokens = 2.00
output_cost_usd_per_million_tokens = 8.00
~~~

The prices above are **illustrative only**, not actual or verified provider pricing.
Supply rates for your selected provider/model if enabling the dollar limit.
You may also set `PDF2AUDIOBOOK_LLM_MAX_REPORTED_TOKENS` and
`PDF2AUDIOBOOK_LLM_MAX_ESTIMATED_COST_USD` through environment variables.

These checks use token counts returned by the provider and stop subsequent
requests after the limit is reached. A request can exceed the budget before
its response is received; the over-budget response is rejected and not cached.
Per-book accounting persists in `reports/llm_budget.sqlite3`, including
across process restarts and `--no-resume` runs in the same book workspace.
SQLite reservations serialize concurrent budgeted requests. Cached responses
do not create new ledger charges. `reports/llm_usage.json` includes both
current-run counters and persistent book totals; neither report stores book
text, prompts, responses, or credentials.

Every HTTP attempt, including retries and compatibility fallbacks, has its own
ledger row and counts toward `max_requests`. Sent or ambiguous requests without
trustworthy usage are recorded as `unknown`; their recorded worst-case token
and cost bounds count against configured budgets. A token or dollar budget
fails closed if an older open row has no recorded bound. `budget show` displays
request IDs, statuses and accounting without prompts or book text. After
checking provider billing evidence, settle an unknown request with its actual
usage or confirm that it was unbilled:

~~~sh
uv run pdf2audiobook budget resolve REQUEST_ID --output ./audiobooks/BOOK \
  --tokens PROMPT:COMPLETION --confirm
uv run pdf2audiobook budget resolve REQUEST_ID --output ./audiobooks/BOOK \
  --unbilled --confirm
~~~

Changing configured prices does not retroactively reprice earlier calls;
each row retains the operator-supplied rates in effect at that time. A
rejected provider request still counts toward `max_requests`, but does not
consume token or cost budget when it reports no usage. Only connection
failures proven to happen before the request was sent are automatically
settled as unbilled.

**Important:** a single completion can exceed its budget before usage is
reported; that response is rejected but may still be billed. Internal HTTP
retries can also incur charges not reported by the provider. Dollar totals
are estimates, not authoritative provider billing. Do not rely on these
limits as guaranteed provider-side spending caps.

## LLM context and completion capacity

The LLM adapter checks each request before uploading book content, reserving
space for model output as well as instructions and document records. Configure:

~~~toml
[llm]
max_context_tokens = 16384
chunk_tokens = 4000
max_output_tokens = 1024
~~~

`max_context_tokens` can also be set for one run with `--llm-context-tokens N` on `analyze` and
`convert` (for example `--llm-context-tokens 262144` for a 256k model); it must stay above
`chunk_tokens` plus the output reserve.

`max_output_tokens` can also be set for one run with `--llm-output-tokens N` on `analyze` and
`convert` (reasoning models may need 32768 or more), and with
`PDF2AUDIOBOOK_LLM_MAX_OUTPUT_TOKENS`. The adapter sends this value as
`max_tokens` and fails closed if a server rejects the parameter; it must
not retry without the cap. Existing JSON-mode fallback preserves the cap.
Input estimation uses a conservative UTF-8-byte count plus reserved chat
overhead, **not** model-specific tokenization. Oversized requests are rejected
before cache retrieval or SQLite budget reservations, so a locally rejected
request does not leave a false unresolved provider charge. Changing the output
cap also invalidates earlier LLM response-cache identities. Operators must verify actual
context windows and `max_tokens` support against their selected live model.
These checks do not guarantee that a misconfigured server honors its limit.

## LLM request timeout

Each LLM request waits for a response for `timeout_seconds` per provider. Ollama defaults to
300 seconds (5 minutes), since local models can be slow on modest hardware; OpenAI and
llama-server default to 60 seconds. Connecting always fails after at most 10 seconds, so an
unreachable server is reported quickly.

~~~toml
[llm.ollama]
timeout_seconds = 600
~~~

`PDF2AUDIOBOOK_LLM_TIMEOUT_SECONDS` overrides the selected provider's value (the valid range is
greater than 0 up to 3600). A timed-out request is retried up to `llm.max_retries` times, so the
worst-case wait for one request is `timeout_seconds × (max_retries + 1)`. If it still fails the
error names the setting to raise. Listing the model's served context (`/api/ps`) always uses its
own 10-second limit. The timeout does not change analysis or cache identities. `config show` and
`doctor --json` report the effective value.

## Optional visual review

Set `llm.vision = true` (or `PDF2AUDIOBOOK_LLM_VISION=true`) to render up to 12 pages with detected
images, vector art, or likely multi-column layouts for review-only descriptions. Use `--vision` for
a one-command opt-in. Visual suggestions are saved in `reports/vision_review.json`; they do not
change chapter text or narration. Select a vision-capable model. Remote page images follow the same
explicit consent and HTTPS rules as other book content.
