"""Atomic content-addressed cache for LLM JSON responses (always revalidated by callers)."""

import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from pdf2audiobook.errors import LLMError
from pdf2audiobook.jsonio import json_within_depth, load_bounded_json
from pdf2audiobook.llm.budget import BookLLMBudgetLedger
from pdf2audiobook.llm.usage import AttemptOutcome, valid_usage_count, verified_usage
from pdf2audiobook.workspace import digest_bytes, fingerprint, write_json

# Cached provider output is untrusted even when its content-addressed filename
# matches. Bound the read independently of an earlier stat() to handle races.
_MAX_CACHED_LLM_JSON_BYTES = 2 * 1024 * 1024
_MAX_CACHED_LLM_JSON_DEPTH = 64


class CachedLLMProvider:
    def __init__(
        self,
        provider: Any,
        *,
        cache_dir: Path,
        identity: str,
        enabled: bool = True,
        max_requests: int | None = None,
        usage_report: Path | None = None,
        max_reported_tokens: int | None = None,
        max_estimated_cost_usd: float | None = None,
        input_cost_usd_per_million_tokens: float | None = None,
        output_cost_usd_per_million_tokens: float | None = None,
        ledger_path: Path | None = None,
    ):
        self.provider = provider
        self.cache_dir = cache_dir
        self.identity = identity
        self._base_identity = identity
        self._resolved_model: str | None = None
        self.enabled = enabled
        self.max_requests = max_requests
        self.usage_report = usage_report
        self.max_reported_tokens = max_reported_tokens
        self.max_estimated_cost_usd = max_estimated_cost_usd
        self.input_cost_usd_per_million_tokens = input_cost_usd_per_million_tokens
        self.output_cost_usd_per_million_tokens = output_cost_usd_per_million_tokens
        self._temporary_ledger: tempfile.TemporaryDirectory[str] | None = None
        if ledger_path is None and any(
            limit is not None
            for limit in (max_requests, max_reported_tokens, max_estimated_cost_usd)
        ):
            self._temporary_ledger = tempfile.TemporaryDirectory(prefix="pdf2audiobook-llm-budget-")
            ledger_path = Path(self._temporary_ledger.name) / "llm_budget.sqlite3"
        self.ledger = BookLLMBudgetLedger(ledger_path) if ledger_path else None
        self.usage_verified = False
        self.hits = 0
        self.misses = 0
        self.requests_started = 0

    def list_models(self) -> list[str]:
        """Forward capability discovery without reading or sending book content."""
        discover = getattr(self.provider, "list_models", None)
        if not callable(discover):
            raise LLMError("LLM provider does not support model discovery")
        models = discover()
        if not isinstance(models, list) or not all(isinstance(model, str) for model in models):
            raise LLMError("Invalid LLM provider model discovery response")
        return models

    def health(self) -> bool:
        """Forward the underlying provider's bounded availability probe."""
        probe = getattr(self.provider, "health", None)
        return bool(probe()) if callable(probe) else False

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
                raise LLMError("LLM reported token budget reached or exceeded")
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
                raise LLMError("LLM estimated cost budget reached or exceeded")

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

    def _capability_path(self) -> Path:
        return (
            self.cache_dir
            / "provider-capabilities"
            / (fingerprint("unsupported-parameters-v1", self.identity) + ".json")
        )

    def _load_unsupported_parameters(self) -> set[str]:
        data = load_bounded_json(self._capability_path(), max_bytes=4096, max_depth=4)
        values = data.get("unsupported", []) if isinstance(data, dict) else []
        if not isinstance(values, list):
            return set()
        allowed = {"max_tokens", "max_completion_tokens", "temperature"}
        return {value for value in values if isinstance(value, str) and value in allowed}

    def _save_unsupported_parameters(self) -> None:
        values = getattr(self.provider, "_unsupported_parameters", None)
        if not isinstance(values, set):
            return
        allowed = sorted(
            value
            for value in values
            if value in {"max_tokens", "max_completion_tokens", "temperature"}
        )
        path = self._capability_path()
        current = load_bounded_json(path, max_bytes=4096, max_depth=4)
        value = {"schema_version": 1, "unsupported": allowed}
        if current != value:
            write_json(path, value)

    def complete_json(self, *, instructions: str, document_text: str) -> dict[str, Any]:
        return self._complete_json_call(
            instructions=instructions, document_text=document_text, image_data=None
        )

    def complete_json_with_image(
        self, *, instructions: str, document_text: str, image_data: bytes
    ) -> dict[str, Any]:
        return self._complete_json_call(
            instructions=instructions, document_text=document_text, image_data=image_data
        )

    def _complete_json_call(
        self, *, instructions: str, document_text: str, image_data: bytes | None
    ) -> dict[str, Any]:
        resolve_model = getattr(self.provider, "resolve_model", None)
        if callable(resolve_model):
            resolved_model = resolve_model()
            if not isinstance(resolved_model, str) or not resolved_model:
                raise LLMError("LLM provider returned an invalid model identity")
            if self._resolved_model != resolved_model:
                self.identity = fingerprint(self._base_identity, "served-model", resolved_model)
                self._resolved_model = resolved_model
        # Reject known oversized requests before reserving a book-budget call.
        # Such requests cannot incur a charge and must not poison the ledger
        # with a false "unknown" charge. Apply this to cache hits as well.
        preflight = getattr(self.provider, "validate_request_capacity", None)
        if callable(preflight):
            preflight(instructions=instructions, document_text=document_text)
        image_preflight = getattr(self.provider, "validate_image_capacity", None)
        if image_data is not None:
            if callable(image_preflight):
                image_preflight(
                    instructions=instructions,
                    document_text=document_text,
                    image_data=image_data,
                )
            elif not callable(getattr(self.provider, "complete_json_with_image", None)):
                raise LLMError("LLM provider does not support image requests")
        if image_data is None:
            key = fingerprint("llm-json-cache-v1", self.identity, instructions, document_text)
        else:
            key = fingerprint(
                "llm-json-image-cache-v1",
                self.identity,
                instructions,
                document_text,
                digest_bytes(image_data),
            )
        target = self.cache_dir / f"{key}.json"
        if self.enabled:
            entry = load_bounded_json(
                target,
                max_bytes=_MAX_CACHED_LLM_JSON_BYTES,
                max_depth=_MAX_CACHED_LLM_JSON_DEPTH,
            )
            if (
                isinstance(entry, dict)
                and entry.get("schema_version") == 1
                and entry.get("fingerprint") == key
                and isinstance(entry.get("response"), dict)
            ):
                self.hits += 1
                self._write_usage()
                return entry["response"]
        self.misses += 1
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
        # Server-side limits need the server, so check them only on a miss:
        # a fully cached rerun must not require a running provider.
        served = getattr(self.provider, "validate_served_capacity", None)
        served_image = getattr(self.provider, "validate_served_image_capacity", None)
        if image_data is not None and callable(served_image):
            served_image(
                instructions=instructions,
                document_text=document_text,
                image_data=image_data,
            )
        elif callable(served):
            served(instructions=instructions, document_text=document_text)
        if self._temporary_ledger is not None:
            self._check_usage_budget()
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
        reservation = None
        attempt_accounting = False
        if self.ledger is None:
            self._check_usage_budget()
            if self.max_requests is not None and self.requests_started >= self.max_requests:
                self._write_usage()
                raise LLMError("LLM request budget exhausted; increase llm.max_requests")
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
        else:
            set_accounting = getattr(self.provider, "set_attempt_accounting", None)
            if callable(set_accounting):
                attempt_accounting = True

                def start_attempt() -> int:
                    assert self.ledger is not None
                    try:
                        call_id = self.ledger.reserve(
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
                    self.requests_started += 1
                    self._write_usage()
                    return call_id

                def settle_attempt(
                    call_id: int, usage: dict | None, outcome: AttemptOutcome
                ) -> None:
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
            else:
                try:
                    reservation = self.ledger.reserve(
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
        # A failed response can still incur charges. Never reuse stale usage.
        if hasattr(self.provider, "last_usage"):
            self.provider.last_usage = {}
        unsupported = getattr(self.provider, "_unsupported_parameters", None)
        if isinstance(unsupported, set):
            unsupported.update(self._load_unsupported_parameters())
        if not attempt_accounting:
            self.requests_started += 1
        self._write_usage()
        request_error: Exception | None = None
        try:
            if image_data is None:
                reply = self.provider.complete_json(
                    instructions=instructions,
                    document_text=document_text,
                )
            else:
                reply = self.provider.complete_json_with_image(
                    instructions=instructions,
                    document_text=document_text,
                    image_data=image_data,
                )
        except Exception as exc:
            request_error = exc
            raise
        finally:
            self._save_unsupported_parameters()
            last = getattr(self.provider, "last_usage", None)
            # A total-token counter alone cannot prove a request's cost.
            # Require complete, internally consistent signed counters before
            # using provider aggregates to authorize additional budget spend.
            self.usage_verified = verified_usage(last) is not None
            if self.ledger is not None and reservation is not None:
                if isinstance(request_error, LLMError) and request_error.unbilled:
                    self.ledger.settle_unbilled(reservation)
                else:
                    self.ledger.settle(
                        reservation,
                        usage=last,
                        input_rate=self.input_cost_usd_per_million_tokens,
                        output_rate=self.output_cost_usd_per_million_tokens,
                    )
            self._write_usage()
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
        if self.enabled:
            write_json(target, {"schema_version": 1, "fingerprint": key, "response": reply})
        return reply
