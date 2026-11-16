"""Book-wide LLM budgets: upper bounds, reservations in the ledger, settlement checks and the usage report."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pdf2audiobook.errors import LLMError
from pdf2audiobook.jsonio import json_within_depth
from pdf2audiobook.llm.cache_base import _MAX_CACHED_LLM_JSON_DEPTH, CacheState
from pdf2audiobook.llm.usage import AttemptOutcome, valid_usage_count
from pdf2audiobook.workspace import write_json


class CacheBudgetMixin(CacheState):
    def _reported_cost_usd(self) -> float | None:
        usage = getattr(self.provider, "total_usage", {})
        if not self.usage_verified or not isinstance(usage, dict):
            return None
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        if (
            not valid_usage_count(prompt)
            or not valid_usage_count(completion)
            or self.input_cost_usd_per_million_tokens is None
            or self.output_cost_usd_per_million_tokens is None
        ):
            return None
        return float(
            (
                Decimal(prompt) * Decimal(str(self.input_cost_usd_per_million_tokens))
                + Decimal(completion) * Decimal(str(self.output_cost_usd_per_million_tokens))
            )
            / Decimal(1_000_000)
        )

    def _check_usage_budget(self, *, postflight: bool = False) -> None:
        if self.max_reported_tokens is not None:
            usage = getattr(self.provider, "total_usage", {})
            count = usage.get("total_tokens") if isinstance(usage, dict) else None
            if not self.usage_verified or not valid_usage_count(count):
                if self.requests_started:
                    raise LLMError("LLM token budget requires provider-reported usage")
            elif (
                count > self.max_reported_tokens
                if postflight
                else count >= self.max_reported_tokens
            ):
                raise LLMError(
                    "LLM reported token budget reached or exceeded", error_reason="budget_exhausted"
                )
        if self.max_estimated_cost_usd is not None:
            cost = self._reported_cost_usd()
            if cost is None:
                if self.requests_started:
                    raise LLMError("LLM cost budget requires verified usage and rates")
            elif (
                cost > self.max_estimated_cost_usd
                if postflight
                else cost >= self.max_estimated_cost_usd
            ):
                raise LLMError(
                    "LLM estimated cost budget reached or exceeded", error_reason="budget_exhausted"
                )

    def _write_usage(self) -> None:
        """Persist counters only, never book text, prompts, credentials or model output."""
        if self.usage_report is None:
            return
        usage = getattr(self.provider, "total_usage", {})
        safe_usage = {}
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                count = usage.get(key)
                if valid_usage_count(count):
                    safe_usage[key] = count
        write_json(
            self.usage_report,
            {
                "schema_version": 1,
                "cache_hits": self.hits,
                "cache_misses": self.misses,
                "requests_started": self.requests_started,
                "max_requests": self.max_requests,
                "max_reported_tokens": self.max_reported_tokens,
                "max_estimated_cost_usd": self.max_estimated_cost_usd,
                "estimated_cost_usd": self._reported_cost_usd(),
                "usage_verified": self.usage_verified,
                "provider_reported_tokens": safe_usage,
                "resolved_model": self._resolved_model or getattr(self.provider, "model", None),
                "scope": "current_analysis_run",
                "book_totals": self.ledger.totals() if self.ledger is not None else None,
            },
        )

    def _request_upper_bounds(
        self, instructions: str, document_text: str, image_data: bytes | None
    ) -> tuple[int, str | None]:
        """Bound a request's tokens, and its cost when prices are set.

        A budget requires a provider output cap; it is switched on here.
        """
        prompt_bound = len(instructions.encode("utf-8")) + len(document_text.encode("utf-8")) + 128
        if image_data is not None:
            # Compressed PNG bytes say nothing about vision cost: bound by the
            # decoded pixel tiles, and never below the encoded request size.
            pixel_reserve = getattr(self.provider, "_image_token_reserve", None)
            encoded = ((len(image_data) + 2) // 3) * 4 + len("data:image/png;base64,")
            prompt_bound += max(
                pixel_reserve(image_data) if callable(pixel_reserve) else 0, encoded
            )
        output_bound = getattr(self.provider, "max_output_tokens", None)
        if (self.max_reported_tokens is not None or self.max_estimated_cost_usd is not None) and (
            not isinstance(output_bound, int)
            or output_bound < 1
            or getattr(self.provider, "max_context_tokens", None) is None
        ):
            raise LLMError("A bounded output token cap is required under an LLM budget")
        if (
            self.max_reported_tokens is not None or self.max_estimated_cost_usd is not None
        ) and hasattr(self.provider, "require_output_cap"):
            self.provider.require_output_cap = True
        upper_bound_tokens = prompt_bound + (output_bound or 0)
        upper_bound_usd = None
        if (
            self.input_cost_usd_per_million_tokens is not None
            and self.output_cost_usd_per_million_tokens is not None
        ):
            upper_bound_usd = str(
                (
                    Decimal(prompt_bound) * Decimal(str(self.input_cost_usd_per_million_tokens))
                    + Decimal(output_bound or 0)
                    * Decimal(str(self.output_cost_usd_per_million_tokens))
                )
                / Decimal(1_000_000)
            )
        return upper_bound_tokens, upper_bound_usd

    def _check_remaining_budget(self, upper_bound_tokens: int, upper_bound_usd: str | None) -> None:
        """Refuse a request whose upper bound the remaining token or cost budget can't cover."""
        usage = getattr(self.provider, "total_usage", {})
        reported = usage.get("total_tokens", 0) if isinstance(usage, dict) else 0
        if self.max_reported_tokens is not None and reported + upper_bound_tokens > (
            self.max_reported_tokens
        ):
            raise LLMError("Per-book LLM token budget cannot cover the next request")
        if self.max_estimated_cost_usd is not None:
            if upper_bound_usd is None:
                raise LLMError("A bounded output token cap is required under an LLM budget")
            current_cost = self._reported_cost_usd() or 0.0
            if Decimal(str(current_cost)) + Decimal(upper_bound_usd) > Decimal(
                str(self.max_estimated_cost_usd)
            ):
                raise LLMError("Per-book LLM cost budget cannot cover the next request")

    def _reserve_ledger_call(
        self, key: str, upper_bound_tokens: int, upper_bound_usd: str | None
    ) -> int:
        """Reserve one call in the book ledger, recording usage if it is refused."""
        assert self.ledger is not None
        try:
            return self.ledger.reserve(
                request_hash=key,
                provider_hash=self.identity,
                max_requests=self.max_requests,
                max_tokens=self.max_reported_tokens,
                max_usd=self.max_estimated_cost_usd,
                upper_bound_tokens=upper_bound_tokens,
                upper_bound_usd=upper_bound_usd,
            )
        except LLMError:
            self._write_usage()
            raise

    def _install_attempt_accounting(
        self,
        set_accounting: Any,
        key: str,
        upper_bound_tokens: int,
        upper_bound_usd: str | None,
    ) -> None:
        """Let the provider reserve and settle the ledger once per attempt."""

        def start_attempt() -> int:
            call_id = self._reserve_ledger_call(key, upper_bound_tokens, upper_bound_usd)
            self.requests_started += 1
            self._write_usage()
            return call_id

        def settle_attempt(call_id: int, usage: dict | None, outcome: AttemptOutcome) -> None:
            assert self.ledger is not None
            if outcome == "unbilled":
                self.ledger.settle_unbilled(call_id)
            else:
                self.ledger.settle(
                    call_id,
                    usage=usage,
                    input_rate=self.input_cost_usd_per_million_tokens,
                    output_rate=self.output_cost_usd_per_million_tokens,
                    rejected=outcome == "rejected",
                )
            self._write_usage()

        set_accounting(start_attempt, settle_attempt)

    def _reserve_budget(
        self, key: str, upper_bound_tokens: int, upper_bound_usd: str | None
    ) -> tuple[int | None, bool]:
        """Check and reserve the budget for a request about to be sent.

        Returns the ledger reservation to settle after the call (None when the
        provider settles per attempt or there is no ledger) and whether the
        provider does its own per-attempt accounting.
        """
        if self._ledger_closed:
            raise LLMError("LLM request budget is closed; create a new provider wrapper")
        if self._temporary_ledger is not None:
            self._check_usage_budget()
            self._check_remaining_budget(upper_bound_tokens, upper_bound_usd)
        if self.ledger is None:
            # No ledger means no limit is set: any limit creates a temporary ledger.
            return None, False
        set_accounting = getattr(self.provider, "set_attempt_accounting", None)
        if callable(set_accounting):
            self._install_attempt_accounting(
                set_accounting, key, upper_bound_tokens, upper_bound_usd
            )
            return None, True
        return self._reserve_ledger_call(key, upper_bound_tokens, upper_bound_usd), False

    def _check_verified_usage(self, reply: Any) -> dict[str, Any]:
        """Validate the reply's shape and depth, then the spend after the call."""
        if not isinstance(reply, dict):
            raise ValueError("LLM cache requires a JSON-object response")
        if not json_within_depth(reply, _MAX_CACHED_LLM_JSON_DEPTH):
            raise LLMError("LLM response exceeds supported JSON nesting depth")
        if self.ledger is not None:
            self.ledger.check_spend(
                max_tokens=self.max_reported_tokens,
                max_usd=self.max_estimated_cost_usd,
            )
        if self._temporary_ledger is not None:
            # Preserve the direct wrapper's historical verified-usage gate as
            # well as the per-attempt reservation semantics of its ledger.
            self._check_usage_budget(postflight=True)
        elif self.ledger is None:
            self._check_usage_budget(postflight=True)
        return reply
