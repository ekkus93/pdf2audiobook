# PDF2Audiobook: LLM budget and live-provider acceptance (2026-10-17)

## P3.06 implementation evidence

- A content-addressed per-book JSON response cache uses source/prompt/provider/settings fingerprints.
- `reports/llm_budget.sqlite3` records every uncached request reservation before network execution. SQLite transactions serialize concurrent reservations, and records persist across process restarts.
- `llm.max_requests`, `llm.max_reported_tokens`, and `llm.max_estimated_cost_usd` are enforced per book workspace. Rates must be explicitly configured for dollar estimates.
- Provider-reported usage is captured even when the model returns malformed JSON. A request that exceeds the limit is recorded and its response is not cached.
- Unresolved requests after crashes or missing usage fail closed for token/dollar budgets. Previously unpriced requests block enabling a cost budget without reconciliation.
- `reports/llm_usage.json` includes current-run counters and persistent book totals without plaintext document content.
- Verified by Python CI run 39024049500 at exact head `2e3dce8565245f9b1979363cecd0c8977f884f06`.

**Scope and limitations:** Budgets are per output workspace, not provider-account-wide. A single completion or HTTP retry can incur charges before the application sees usage. Cost values are estimates based on operator-supplied rates, not authoritative billing.

## P3.08 implementation and manual acceptance

The opt-in synthetic-only runner is available at `python -m pdf2audiobook.llm.smoke`.
Offline safety/contract tests passed in Python CI run 39023954435 at exact head `f7e9a88e38684660d550abf8a5102f913d773f01`.

Real-model acceptance remains open. On a host with the relevant services or API credentials, run the explicit commands in README, record provider/model, model-serving version, output, reported token usage, latency and whether the JSON contract succeeded. Do not include credentials or copyrighted book text in evidence.

## Checklist reconciliation

P3.06 has implementation and offline CI evidence sufficient for its technical acceptance criteria. Its checkbox in `docs/PDF2AUDIOBOOK_TODO.md` still needs to be reconciled if not already checked on the current master. P3.08 remains unchecked until live backend evidence exists.
