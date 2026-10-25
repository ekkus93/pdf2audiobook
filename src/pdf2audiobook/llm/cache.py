"""Atomic content-addressed cache for LLM JSON responses (always revalidated by callers)."""

import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.budget import BookLLMBudgetLedger
from pdf2audiobook.workspace import digest_bytes, fingerprint, write_json

# Cached provider output is untrusted even when its content-addressed filename
# matches. Bound the read independently of an earlier stat() to handle races.
_MAX_CACHED_LLM_JSON_BYTES = 2 * 1024 * 1024
_MAX_CACHED_LLM_JSON_DEPTH = 64


def _bounded_cache_json_structure(value: Any) -> bool:
    """Check nested containers iteratively: CPython JSON may accept very deep input."""
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if not isinstance(item, (dict, list)):
            continue
        if depth >= _MAX_CACHED_LLM_JSON_DEPTH:
            return False
        children = item.values() if isinstance(item, dict) else item
        pending.extend((child, depth + 1) for child in children)
    return True


def _reject_nonstandard_json_constant(_value: str) -> None:
    raise ValueError("Nonstandard JSON numeric constant")


def _finite_json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Nonfinite JSON number")
    return number


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
        self.enabled = enabled
        self.max_requests = max_requests
        self.usage_report = usage_report
        self.max_reported_tokens = max_reported_tokens
        self.max_estimated_cost_usd = max_estimated_cost_usd
        self.input_cost_usd_per_million_tokens = input_cost_usd_per_million_tokens
        self.output_cost_usd_per_million_tokens = output_cost_usd_per_million_tokens
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
            not isinstance(prompt, int)
            or isinstance(prompt, bool)
            or not isinstance(completion, int)
            or isinstance(completion, bool)
            or prompt < 0
            or completion < 0
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
            if not self.usage_verified or not isinstance(count, int):
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
                if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
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
                "scope": "current_analysis_run",
                "book_totals": self.ledger.totals() if self.ledger is not None else None,
            },
        )

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
            try:
                if target.is_file():
                    # A cache entry may grow between stat and read; enforce the
                    # byte ceiling on the actual read, not only filesystem metadata.
                    with target.open("rb") as cached:
                        payload = cached.read(_MAX_CACHED_LLM_JSON_BYTES + 1)
                    if len(payload) > _MAX_CACHED_LLM_JSON_BYTES:
                        raise ValueError("oversized LLM cache")
                    entry = json.loads(
                        payload,
                        parse_constant=_reject_nonstandard_json_constant,
                        parse_float=_finite_json_float,
                    )
                    if (
                        isinstance(entry, dict)
                        and entry.get("schema_version") == 1
                        and entry.get("fingerprint") == key
                        and isinstance(entry.get("response"), dict)
                        and _bounded_cache_json_structure(entry)
                    ):
                        self.hits += 1
                        self._write_usage()
                        return entry["response"]
            except (OSError, ValueError, UnicodeError, TypeError, RecursionError):
                # Corrupt, hostile or inaccessible cache files are cache misses.
                pass
        self.misses += 1
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
        reservation = None
        if self.ledger is None:
            self._check_usage_budget()
            if self.max_requests is not None and self.requests_started >= self.max_requests:
                self._write_usage()
                raise LLMError("LLM request budget exhausted; increase llm.max_requests")
        else:
            reservation = self.ledger.reserve(
                request_hash=key,
                provider_hash=self.identity,
                max_requests=self.max_requests,
                max_tokens=self.max_reported_tokens,
                max_usd=self.max_estimated_cost_usd,
            )
        # A failed response can still incur charges. Never reuse stale usage.
        if hasattr(self.provider, "last_usage"):
            self.provider.last_usage = {}
        self.requests_started += 1
        self._write_usage()
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
        finally:
            last = getattr(self.provider, "last_usage", None)
            # A total-token counter alone cannot prove a request's cost.
            # Require complete, internally consistent signed counters before
            # using provider aggregates to authorize additional budget spend.
            self.usage_verified = (
                isinstance(last, dict)
                and all(
                    isinstance(last.get(field), int)
                    and not isinstance(last[field], bool)
                    and 0 <= last[field] <= 2**63 - 1
                    for field in ("prompt_tokens", "completion_tokens", "total_tokens")
                )
                and last["total_tokens"] >= last["prompt_tokens"] + last["completion_tokens"]
            )
            if self.ledger is not None and reservation is not None:
                self.ledger.settle(
                    reservation,
                    usage=last,
                    input_rate=self.input_cost_usd_per_million_tokens,
                    output_rate=self.output_cost_usd_per_million_tokens,
                )
            self._write_usage()
        if not isinstance(reply, dict):
            raise ValueError("LLM cache requires a JSON-object response")
        if not _bounded_cache_json_structure(reply):
            raise LLMError("LLM response exceeds supported JSON nesting depth")
        if self.ledger is not None:
            self.ledger.check_spend(
                max_tokens=self.max_reported_tokens,
                max_usd=self.max_estimated_cost_usd,
            )
        else:
            self._check_usage_budget(postflight=True)
        if self.enabled:
            write_json(target, {"schema_version": 1, "fingerprint": key, "response": reply})
        return reply
