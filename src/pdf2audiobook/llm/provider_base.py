"""Shared pieces of the OpenAI-compatible provider (see `provider.py`): the endpoint check,
the per-request state, the output-size limit, and the attribute declarations the provider
mixins use. Nothing here makes a request."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any, Callable, Literal
from urllib.parse import urlparse

import httpx

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.usage import AttemptOutcome

MAX_VISUAL_REVIEW_PAGES = 12


def _loopback(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_endpoint(url: str, allow_remote: bool) -> str:
    # Direct adapter callers may bypass Pydantic configuration. urllib raises
    # ValueError for malformed IPv6 brackets and invalid/out-of-range ports.
    # Never surface an untrusted endpoint or parser diagnostic in an error.
    if not isinstance(url, str) or not url.strip():
        raise LLMError("Invalid LLM endpoint URL or port")
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port
    except (ValueError, TypeError):
        raise LLMError("Invalid LLM endpoint URL or port") from None
    if port == 0:
        raise LLMError("Invalid LLM endpoint URL or port")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LLMError("LLM endpoint may not contain credentials, query or fragment")
    if parsed.scheme == "https" and host:
        if not _loopback(host) and not allow_remote:
            raise LLMError("Remote LLM content upload requires --allow-remote-content")
        return url.rstrip("/")
    if parsed.scheme == "http" and _loopback(host):
        return url.rstrip("/")
    raise LLMError("Non-loopback LLM endpoint must use HTTPS and explicit remote consent")


_ResponseAction = Literal["json_mode_fallback", "rejected_parameter", "retry", "final"]


@dataclass
class _Attempt:
    """One HTTP attempt's ledger reservation, cleared once it is settled."""

    call_id: int | None


@dataclass
class _RequestState:
    """The payload and retry state shared by every attempt of one request."""

    payload: dict
    format_fallback_used: bool
    retry_count: int = 0


class ProviderState:
    """The attributes and cross-mixin methods every provider mixin may use (declared only)."""

    provider: str
    timeout: float
    base_url: str
    model: str
    temperature: float
    max_retries: int
    max_context_tokens: int | None
    max_output_tokens: int
    require_output_cap: bool
    request_count: int
    last_usage: dict[str, int]
    total_usage: dict[str, int]
    _unsupported_parameters: set[str]
    _json_mode_unsupported: bool
    _remote_content_warned_scopes: set[str]
    _served_context: int | None
    _attempt_started: Callable[[], int] | None
    _attempt_settled: Callable[[int, dict | None, AttemptOutcome], None] | None
    _client: httpx.Client

    def _model(self) -> str:
        raise NotImplementedError

    def _ollama_served_context(self, model: str) -> int:
        raise NotImplementedError

    def validate_request_capacity(self, *, instructions: str, document_text: str) -> None:
        raise NotImplementedError

    def validate_served_capacity(self, *, instructions: str, document_text: str) -> None:
        raise NotImplementedError

    @staticmethod
    def _image_token_reserve(image_data: bytes) -> int:
        raise NotImplementedError

    def _require_cap(self, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def _provider_label(self) -> str:
        raise NotImplementedError

    def _finish_attempt(
        self,
        attempt: _Attempt,
        usage: dict | None = None,
        *,
        outcome: AttemptOutcome = "settled",
    ) -> AttemptOutcome:
        raise NotImplementedError

    def _prepare_usage(self, raw_usage: object) -> dict[str, int]:
        raise NotImplementedError

    def _aggregate_usage(self) -> None:
        raise NotImplementedError

    def _settle_error_usage(self, attempt: _Attempt, response: httpx.Response) -> AttemptOutcome:
        raise NotImplementedError

    def _settle_non_retryable(self, attempt: _Attempt, response: httpx.Response) -> AttemptOutcome:
        raise NotImplementedError
