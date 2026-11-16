"""OpenAI-compatible chat provider: the public class, assembled from the mixins.

`OpenAICompatibleProvider` is one class, built from four mixins by topic: server discovery
(`provider_server`), capacity checks (`provider_capacity`), the request loop
(`provider_request`) and usage settlement (`provider_usage`). Tests and `llm/__init__`
import the names from here."""

from __future__ import annotations

import os
from typing import Any, Callable

import httpx

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.provider_base import (
    MAX_VISUAL_REVIEW_PAGES as MAX_VISUAL_REVIEW_PAGES,
)
from pdf2audiobook.llm.provider_base import _loopback as _loopback
from pdf2audiobook.llm.provider_base import validate_endpoint as validate_endpoint
from pdf2audiobook.llm.provider_capacity import CapacityMixin
from pdf2audiobook.llm.provider_request import RequestMixin
from pdf2audiobook.llm.provider_server import ServerMixin
from pdf2audiobook.llm.provider_usage import UsageMixin
from pdf2audiobook.llm.usage import AttemptOutcome


class OpenAICompatibleProvider(ServerMixin, CapacityMixin, RequestMixin, UsageMixin):
    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        allow_remote: bool,
        api_key: str | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        temperature: float = 0.1,
        max_retries: int = 3,
        max_context_tokens: int | None = None,
        max_output_tokens: int = 1024,
    ):
        self.provider = provider
        self.timeout = timeout
        self.base_url = validate_endpoint(base_url, allow_remote)
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.max_context_tokens = max_context_tokens
        self.max_output_tokens = max_output_tokens
        self._unsupported_parameters: set[str] = set()
        self._json_mode_unsupported = False
        self._remote_content_warned_scopes: set[str] = set()
        self._served_context: int | None = None
        self.request_count = 0
        self.last_usage: dict[str, int] = {}
        self.total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self._attempt_started: Callable[[], int] | None = None
        self.require_output_cap = False
        self._attempt_settled: Callable[[int, dict | None, AttemptOutcome], None] | None = None
        self._client = httpx.Client(
            # Only slow responses should wait this long; an unreachable server fails fast.
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    def __enter__(self) -> "OpenAICompatibleProvider":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self._client.close()

    def set_attempt_accounting(
        self,
        started: Callable[[], int],
        settled: Callable[[int, dict | None, AttemptOutcome], None],
    ) -> None:
        """Attach per-HTTP-attempt accounting supplied by the cache wrapper."""
        self._attempt_started = started
        self._attempt_settled = settled

    def _provider_label(self) -> str:
        """A provider name safe for error messages."""
        return (
            self.provider if self.provider in ("openai", "ollama", "llama-server") else "provider"
        )


def create_provider(
    settings: Settings, *, transport: httpx.BaseTransport | None = None
) -> OpenAICompatibleProvider:
    if not settings.llm.enabled:
        raise LLMError("LLM disabled by configuration")
    selected = settings.llm.provider.replace("-", "_")
    choice = getattr(settings.llm, selected)
    remote_consent = settings.llm.allow_remote_content
    if selected == "openai":
        if not remote_consent:
            raise LLMError("OpenAI requires explicit --allow-remote-content")
        base_url = "https://api.openai.com/v1"
        api_key = os.getenv(choice.api_key_env or "OPENAI_API_KEY")
        if not api_key:
            raise LLMError("OpenAI API key environment variable is missing")
    else:
        base_url = choice.base_url or ""
        api_key = os.getenv(choice.api_key_env) if choice.api_key_env else None
    return OpenAICompatibleProvider(
        provider=selected,
        base_url=base_url,
        model=choice.model,
        allow_remote=remote_consent,
        api_key=api_key,
        transport=transport,
        temperature=settings.llm.temperature,
        timeout=choice.timeout_seconds,
        max_retries=settings.llm.max_retries,
        max_context_tokens=settings.llm.max_context_tokens,
        max_output_tokens=settings.llm.max_output_tokens,
    )
