"""Shared pieces of the cache wrapper (see `cache.py`): the size bounds for cached JSON, and the
attribute and cross-part method declarations the cache mixins rely on. Nothing here makes a request."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from pdf2audiobook.llm.budget import BookLLMBudgetLedger

_MAX_CACHED_LLM_JSON_BYTES = 2 * 1024 * 1024

_MAX_CACHED_LLM_JSON_DEPTH = 64


class CacheState:
    """Attributes and cross-part methods every cache mixin may use (declared, not implemented)."""

    provider: Any
    cache_dir: Path
    identity: str
    _base_identity: str
    _resolved_model: str | None
    enabled: bool
    max_requests: int | None
    usage_report: Path | None
    max_reported_tokens: int | None
    max_estimated_cost_usd: float | None
    input_cost_usd_per_million_tokens: float | None
    output_cost_usd_per_million_tokens: float | None
    _temporary_ledger: tempfile.TemporaryDirectory[str] | None
    _ledger_closed: bool
    ledger: BookLLMBudgetLedger | None
    usage_verified: bool
    hits: int
    misses: int
    requests_started: int
    progress: Any
    _expected_requests: int
    _stage: str
    _seconds: dict[str, list[float]]
    _completion_tokens: dict[str, list[int]]
    _slow_warned: set[str]

    def _cached_response(self, key: str, target: Path) -> dict[str, Any] | None:
        raise NotImplementedError

    def _check_verified_usage(self, reply: Any) -> dict[str, Any]:
        raise NotImplementedError

    def _complete_json_call(
        self, *, instructions: str, document_text: str, image_data: bytes | None
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _load_capabilities(self) -> tuple[set[str], bool]:
        raise NotImplementedError

    def _note_request(self, *, cached: bool) -> None:
        raise NotImplementedError

    def _observe(self, seconds: float, error: Exception | None = None) -> None:
        raise NotImplementedError

    def _request_key(self, instructions: str, document_text: str, image_data: bytes | None) -> str:
        raise NotImplementedError

    def _request_upper_bounds(
        self, instructions: str, document_text: str, image_data: bytes | None
    ) -> tuple[int, str | None]:
        raise NotImplementedError

    def _reserve_budget(
        self, key: str, upper_bound_tokens: int, upper_bound_usd: str | None
    ) -> tuple[int | None, bool]:
        raise NotImplementedError

    def _resolve_served_identity(self) -> None:
        raise NotImplementedError

    def _save_unsupported_parameters(self) -> None:
        raise NotImplementedError

    def _write_usage(self) -> None:
        raise NotImplementedError
