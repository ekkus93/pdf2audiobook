"""Usage settlement: ledger reservations per HTTP attempt and the provider's usage totals."""

from __future__ import annotations

import json

import httpx

from pdf2audiobook.llm.provider_base import ProviderState, _Attempt
from pdf2audiobook.llm.usage import AttemptOutcome, valid_usage_count


class UsageMixin(ProviderState):
    def _finish_attempt(
        self,
        attempt: _Attempt,
        usage: dict | None = None,
        *,
        outcome: AttemptOutcome = "settled",
    ) -> AttemptOutcome:
        """Settle an attempt's ledger reservation once; later calls do nothing."""
        if attempt.call_id is not None and self._attempt_settled is not None:
            current_id = attempt.call_id
            attempt.call_id = None
            self._attempt_settled(current_id, usage, outcome)
        return outcome

    def _prepare_usage(self, raw_usage: object) -> dict[str, int]:
        """Record the valid, non-overflowing usage counters of one response."""
        self.last_usage = {}
        if isinstance(raw_usage, dict):
            for field in self.total_usage:
                count = raw_usage.get(field)
                if valid_usage_count(count) and count <= (2**63 - 1) - self.total_usage[field]:
                    self.last_usage[field] = count
        return self.last_usage

    def _aggregate_usage(self) -> None:
        """Add the last response's usage to the provider totals."""
        for field, count in self.last_usage.items():
            self.total_usage[field] += count

    def _settle_error_usage(self, attempt: _Attempt, response: httpx.Response) -> AttemptOutcome:
        """Settle a rejected response: billed if it reports usage, else rejected."""
        try:
            error_payload = response.json()
        except (ValueError, json.JSONDecodeError):
            error_payload = None
        usage = error_payload.get("usage") if isinstance(error_payload, dict) else None
        settlement_usage = self._prepare_usage(usage) if isinstance(usage, dict) else None
        result = self._finish_attempt(
            attempt,
            settlement_usage,
            outcome="settled" if isinstance(usage, dict) else "rejected",
        )
        if isinstance(usage, dict):
            self._aggregate_usage()
        return result

    def _settle_non_retryable(self, attempt: _Attempt, response: httpx.Response) -> AttemptOutcome:
        """Settle a final unsuccessful response; client errors may carry usage."""
        if 400 <= response.status_code < 500 and response.status_code not in (408, 429):
            return self._settle_error_usage(attempt, response)
        return self._finish_attempt(attempt)
