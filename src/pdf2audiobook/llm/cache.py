"""The cache-and-budget wrapper around an LLM provider: `CachedLLMProvider`, assembled from its parts.

The class is built from four mixins by topic: progress and telemetry (`cache_telemetry`), the
response cache (`cache_store`), book budgets (`cache_budget`) and request handling (`cache_request`).
Pipeline and tests import `CachedLLMProvider` from here."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.budget import BookLLMBudgetLedger
from pdf2audiobook.llm.cache_base import _MAX_CACHED_LLM_JSON_BYTES as _MAX_CACHED_LLM_JSON_BYTES
from pdf2audiobook.llm.cache_base import _MAX_CACHED_LLM_JSON_DEPTH as _MAX_CACHED_LLM_JSON_DEPTH
from pdf2audiobook.llm.cache_budget import CacheBudgetMixin
from pdf2audiobook.llm.cache_request import CacheRequestMixin
from pdf2audiobook.llm.cache_store import CacheStoreMixin
from pdf2audiobook.llm.cache_telemetry import CacheTelemetryMixin


class CachedLLMProvider(CacheTelemetryMixin, CacheStoreMixin, CacheBudgetMixin, CacheRequestMixin):
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
        self._ledger_closed = False
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
        # Optional progress handle; set by the caller that owns the display.
        self.progress: Any = None
        self._expected_requests = 0
        self._stage = ""
        # Typical request size differs by stage, so each stage is judged against itself.
        self._seconds: dict[str, list[float]] = {}
        self._completion_tokens: dict[str, list[int]] = {}
        self._slow_warned: set[str] = set()

    def __enter__(self) -> "CachedLLMProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Remove the temporary budget ledger, if this wrapper created one.

        Only a wrapper given a limit but no ``ledger_path`` creates one. After
        closing, a request that would need the budget is refused (a fresh ledger
        would forget what was spent); cache hits still work. Calling it again
        does nothing.
        """
        if self._temporary_ledger is not None:
            self._ledger_closed = True
            self._temporary_ledger.cleanup()

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
