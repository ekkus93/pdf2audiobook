"""OpenAI-compatible provider transport and endpoint validation."""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import struct
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal
from urllib.parse import urlparse

import httpx

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.usage import AttemptOutcome, valid_usage_count

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


# What one chat-completions response means for the request loop.
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


class OpenAICompatibleProvider:
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

    def _require_cap(self, payload: dict[str, Any]) -> None:
        """Under a token or USD budget an uncapped request has no upper bound."""
        if (
            self.require_output_cap
            and "max_tokens" not in payload
            and "max_completion_tokens" not in payload
        ):
            raise LLMError(
                "Provider does not accept an output token cap, which an LLM budget needs"
            )

    def list_models(self) -> list[str]:
        """Use bounded /models discovery; never include raw server replies in errors."""
        try:
            response = self._client.get(f"{self.base_url}/models")
            response.raise_for_status()
            payload = response.json()
            models = payload["data"]
            if not isinstance(models, list):
                raise ValueError("invalid model list")
            names = [
                item["id"]
                for item in models
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
            ]
            return list(dict.fromkeys(names))
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            # Transport/parser diagnostics may include private server details.
            raise LLMError("Could not discover the served LLM models") from None

    def health(self) -> bool:
        """Check model discovery without uploading any document content."""
        try:
            return bool(self.list_models())
        except LLMError:
            return False

    def _model(self) -> str:
        return self.resolve_model()

    def resolve_model(self) -> str:
        """Resolve an automatic served-model alias before cache or budget identity."""
        if self.model == "auto":
            models = self.list_models()
            if len(models) != 1:
                raise LLMError("Automatic model selection requires exactly one served model")
            self.model = models[0]
        return self.model

    @staticmethod
    def _unsupported_json_mode(response: httpx.Response) -> bool:
        """Fallback only when the server specifically rejects JSON response_format."""
        if not 400 <= response.status_code < 500 or response.status_code in (408, 429):
            return False
        try:
            body = response.json()
            detail = body.get("error", body) if isinstance(body, dict) else ""
            if isinstance(detail, dict):
                detail = str(detail.get("message", "")) + " " + str(detail.get("param", ""))
            if not isinstance(detail, str):
                return False
        except (ValueError, TypeError):
            return False
        explanation = detail.casefold()
        return "response_format" in explanation and any(
            term in explanation
            for term in ("not support", "unsupported", "unrecognized", "unknown", "invalid")
        )

    @staticmethod
    def _unsupported_parameter(response: httpx.Response, parameter: str) -> bool:
        """Detect a specific provider rejection without exposing its error body."""
        if response.status_code != 400:
            return False
        try:
            body = response.json()
            detail = body.get("error", body) if isinstance(body, dict) else ""
            if isinstance(detail, dict):
                message = detail.get("message", "")
                param = detail.get("param", "")
            else:
                message, param = detail, ""
            if not isinstance(message, str) or not isinstance(param, str):
                return False
        except (ValueError, TypeError):
            return False
        explanation = message.casefold()
        if any(
            term in explanation for term in ("context length", "context window", "too many tokens")
        ):
            return False
        escaped = re.escape(parameter.casefold())
        unsupported_pattern = (
            rf"(?:unsupported|not supported|does not support|doesn't support|"
            rf"unrecognized|not recognized|unknown|invalid)\s+(?:parameter\s*[:=]?\s*)?{escaped}\b"
            rf"|(?:parameter\s*[:=]?\s*)?\b{escaped}\b\s+(?:is\s+)?(?:unsupported|not supported|"
            rf"not recognized|unrecognized)"
        )
        return bool(re.search(unsupported_pattern, explanation)) and (
            param == parameter or parameter in explanation
        )

    def validate_request_capacity(self, *, instructions: str, document_text: str) -> None:
        """Check capacity before cache/ledger reservations or any book-text upload."""
        # Conservatively bound tokenized text by its UTF-8 byte length.
        # Reserve fixed chat-role overhead and generation capacity as well.
        # This is not a model-specific tokenizer; live qualification is still needed.
        if self.max_context_tokens is not None:
            if (
                self.max_output_tokens < 1
                or self.max_context_tokens < self.max_output_tokens + 128
                or len(instructions.encode("utf-8"))
                + len(document_text.encode("utf-8"))
                + self.max_output_tokens
                + 128
                > self.max_context_tokens
            ):
                raise LLMError("LLM request exceeds configured context and output reserve")

    def _ollama_served_context(self, model: str) -> int:
        """Return the context length Ollama actually serves for ``model``.

        Ollama silently drops the start of a prompt (including the system
        instructions) that exceeds it, so the configured budget alone is unsafe.
        """
        if self._served_context is None:
            root = self.base_url.removesuffix("/v1")
            names = {model, model if ":" in model else f"{model}:latest"}
            lengths: list[int] = []
            try:
                # An empty prompt only loads the model; no book text is sent.
                self._client.post(
                    f"{root}/api/generate", json={"model": model, "prompt": "", "stream": False}
                ).raise_for_status()
                # Model loading above may be slow; listing what is loaded must not be.
                response = self._client.get(f"{root}/api/ps", timeout=10.0)
                response.raise_for_status()
                for item in response.json()["models"]:
                    length = item.get("context_length")
                    if (
                        names & {item.get("name"), item.get("model")}
                        and isinstance(length, int)
                        and not isinstance(length, bool)
                        and length > 0
                    ):
                        lengths.append(length)
            except (httpx.HTTPError, KeyError, ValueError, TypeError, AttributeError):
                lengths = []
            if not lengths:
                raise LLMError("Could not read the context length Ollama serves for the model")
            self._served_context = min(lengths)
        return self._served_context

    def validate_served_capacity(self, *, instructions: str, document_text: str) -> None:
        """Check a request against the server's real context before uploading it."""
        if self.provider != "ollama":
            return
        served = self._ollama_served_context(self._model())
        limit = min(served, self.max_context_tokens or served)
        if (
            len(instructions.encode("utf-8"))
            + len(document_text.encode("utf-8"))
            + self.max_output_tokens
            + 128
            > limit
        ):
            raise LLMError(
                "LLM request exceeds the context length the Ollama server serves; "
                "lower llm.chunk_tokens or use a model with a larger num_ctx"
            )

    def complete_json(self, *, instructions: str, document_text: str) -> dict[str, Any]:
        return self._complete_json_request(
            instructions=instructions,
            document_text=document_text,
            user_content=document_text,
        )

    @staticmethod
    def _image_token_reserve(image_data: bytes) -> int:
        if (
            not isinstance(image_data, bytes)
            or len(image_data) < 24
            or len(image_data) > 4 * 1024 * 1024
            or image_data[:8] != b"\x89PNG\r\n\x1a\n"
            or image_data[12:16] != b"IHDR"
        ):
            raise LLMError("Vision request requires a valid PNG image no larger than 4 MiB")
        width, height = struct.unpack(">II", image_data[16:24])
        if not width or not height or width > 4096 or height > 4096 or width * height > 4_000_000:
            raise LLMError("Vision image dimensions exceed the supported limit")
        # Four tokens per 32px tile plus a fixed image/message allowance is a
        # deliberately conservative bound for high-resolution visual patches.
        return ((width * height + 1023) // 1024) * 4 + 256

    def validate_image_capacity(
        self, *, instructions: str, document_text: str, image_data: bytes
    ) -> None:
        reserve = self._image_token_reserve(image_data)
        self.validate_request_capacity(
            instructions=instructions,
            document_text=document_text + (" " * reserve),
        )

    def validate_served_image_capacity(
        self, *, instructions: str, document_text: str, image_data: bytes
    ) -> None:
        reserve = self._image_token_reserve(image_data)
        self.validate_served_capacity(
            instructions=instructions,
            document_text=document_text + (" " * reserve),
        )

    def complete_json_with_image(
        self,
        *,
        instructions: str,
        document_text: str,
        image_data: bytes,
    ) -> dict[str, Any]:
        reserve = self._image_token_reserve(image_data)
        budget_text = document_text + (" " * reserve)
        data_url = "data:image/png;base64," + base64.b64encode(image_data).decode("ascii")
        return self._complete_json_request(
            instructions=instructions,
            document_text=budget_text,
            user_content=[
                {"type": "text", "text": document_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
            vision=True,
        )

    def _build_payload(self, instructions: str, user_content: str | list[dict[str, Any]]) -> dict:
        """Build the chat request with JSON mode and the output cap when available."""
        # The book is untrusted data; never send it as system instructions or as tools.
        payload = {
            "model": self._model(),
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.temperature,
        }
        if not self._json_mode_unsupported:
            payload["response_format"] = {"type": "json_object"}
        # Do not silently drop the response cap for an incompatible provider.
        if self.max_context_tokens is not None:
            parameter = (
                "max_completion_tokens"
                if "max_tokens" in self._unsupported_parameters
                else "max_tokens"
            )
            payload[parameter] = self.max_output_tokens
        for parameter in self._unsupported_parameters:
            payload.pop(parameter, None)
        self._require_cap(payload)
        if self.provider == "ollama":
            # Reasoning models (e.g. qwen3.5) otherwise spend the whole output
            # cap on hidden thinking and return empty content. Answers are
            # schema-validated JSON, so hidden reasoning adds no safety.
            payload["reasoning_effort"] = "none"
        return payload

    def _warn_remote_upload(self, model: object, *, vision: bool) -> None:
        """Warn once per data scope before the first upload to a remote provider."""
        # A remote-content opt-in must be accompanied by a visible warning
        # before the first upload, not only after analysis has completed.
        scope_key = "page-images" if vision else "book-text"
        if (
            not _loopback(urlparse(self.base_url).hostname)
            and scope_key not in self._remote_content_warned_scopes
        ):
            safe_provider = json.dumps(str(self.provider)[:80], ensure_ascii=True)
            safe_model = json.dumps(str(model)[:80], ensure_ascii=True)
            scope = (
                f"up to {MAX_VISUAL_REVIEW_PAGES} rendered PDF page images"
                if vision
                else "the whole book in bounded analysis windows"
            )
            print(
                f"Warning: uploading PDF-derived {'page image' if vision else 'book text'} to remote LLM "
                f"provider {safe_provider}, model {safe_model}; "
                f"data scope: {scope}.",
                file=sys.stderr,
            )
            self._remote_content_warned_scopes.add(scope_key)

    def _provider_label(self) -> str:
        """A provider name safe for error messages."""
        return (
            self.provider if self.provider in ("openai", "ollama", "llama-server") else "provider"
        )

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

    def _classify_response(
        self, response: httpx.Response, request: _RequestState
    ) -> tuple[_ResponseAction, str | None]:
        """Decide what one response means, with the rejected parameter if any."""
        if self._unsupported_json_mode(response) and not request.format_fallback_used:
            return "json_mode_fallback", None
        rejected_parameter = next(
            (
                parameter
                for parameter in ("max_tokens", "max_completion_tokens", "temperature")
                if parameter in request.payload
                and parameter not in self._unsupported_parameters
                and self._unsupported_parameter(response, parameter)
            ),
            None,
        )
        if rejected_parameter is not None:
            return "rejected_parameter", rejected_parameter
        # Ollama reports an aborted generation ("token repeat limit
        # reached") as HTTP 500; a resample usually succeeds.
        if (
            response.status_code in (429, 500, 502, 503, 504)
            and request.retry_count < self.max_retries
        ):
            return "retry", None
        return "final", None

    def _fall_back_from_json_mode(
        self, attempt: _Attempt, response: httpx.Response, request: _RequestState
    ) -> None:
        """Retry without JSON mode after the server rejects it."""
        # Older OpenAI-compatible local servers sometimes lack JSON mode.
        # Output is still schema-validated by callers after decoding.
        self._settle_error_usage(attempt, response)
        self._json_mode_unsupported = True
        request.payload.pop("response_format")
        request.format_fallback_used = True

    def _drop_rejected_parameter(
        self, attempt: _Attempt, parameter: str, request: _RequestState
    ) -> None:
        """Retry without a rejected parameter, keeping an output cap when possible."""
        self._finish_attempt(attempt, outcome="rejected")
        request.payload.pop(parameter, None)
        self._unsupported_parameters.add(parameter)
        if (
            parameter == "max_tokens"
            and "max_completion_tokens" not in self._unsupported_parameters
        ):
            request.payload["max_completion_tokens"] = self.max_output_tokens
        self._require_cap(request.payload)

    def _back_off(self, attempt: _Attempt, request: _RequestState) -> None:
        """Settle a retryable response and wait before the next attempt."""
        self._finish_attempt(attempt)
        time.sleep(min(0.2 * (2**request.retry_count), 2.0))
        request.retry_count += 1

    def _accept_response(self, attempt: _Attempt, response: httpx.Response) -> dict[str, Any]:
        """Settle a final response's usage, then decode its JSON object answer."""
        if not response.is_success:
            self._settle_non_retryable(attempt, response)
        response.raise_for_status()
        reply = response.json()
        # Provider usage is billable even when generated JSON is malformed.
        # Account for it before attempting to parse or validate the content.
        usage = reply.get("usage", {}) if isinstance(reply, dict) else {}
        settlement_usage = self._prepare_usage(usage)
        self._finish_attempt(attempt, settlement_usage)
        self._aggregate_usage()
        choice = reply["choices"][0]
        message = choice["message"]["content"]
        truncated = choice.get("finish_reason") == "length"
        if truncated and not (isinstance(message, str) and message.strip()):
            raise LLMError(
                "LLM output cap reached before any answer; raise "
                "llm.max_output_tokens or disable model reasoning",
                reason="output_cap",
            )
        try:
            decoded = json.loads(message)
        except ValueError:
            if truncated:
                raise LLMError(
                    "LLM answer was cut off at the output cap; raise llm.max_output_tokens",
                    reason="output_cap",
                ) from None
            raise
        if not isinstance(decoded, dict):
            raise LLMError("Model response must be a JSON object")
        self.request_count += 1
        return decoded

    def _handle_transport_error(
        self, attempt: _Attempt, exc: httpx.TransportError, request: _RequestState
    ) -> None:
        """Settle a transport failure, then return to retry or raise a safe error."""
        self._finish_attempt(
            attempt,
            outcome=(
                "unbilled"
                if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
                else "settled"
            ),
        )
        if request.retry_count < self.max_retries:
            time.sleep(min(0.2 * (2**request.retry_count), 2.0))
            request.retry_count += 1
            return
        label = self._provider_label()
        if isinstance(exc, httpx.TimeoutException) and not isinstance(exc, httpx.ConnectTimeout):
            setting = (
                f"llm.{self.provider.replace('-', '_')}.timeout_seconds"
                if label != "provider"
                else "the LLM timeout_seconds setting"
            )
            raise LLMError(
                f"{label} LLM transport failure: request timed out after "
                f"{self.timeout:g} s; increase {setting}"
            ) from None
        raise LLMError(
            f"{label} LLM transport failure",
            unbilled=isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)),
        ) from None

    def _complete_json_request(
        self,
        *,
        instructions: str,
        document_text: str,
        user_content: str | list[dict[str, Any]],
        vision: bool = False,
    ) -> dict[str, Any]:
        """Send one JSON request, dispatching on each attempt's typed outcome.

        Every attempt reserves a ledger call (when accounting is attached) and
        settles it exactly once: on success, retry, parameter rejection, JSON
        mode fallback, final error, transport failure or unexpected error.
        """
        # Never expose the previous request's usage when this attempt fails before
        # receiving a billable response. Accounted aggregate usage is unchanged.
        self.last_usage = {}
        self.validate_request_capacity(instructions=instructions, document_text=document_text)
        self.validate_served_capacity(instructions=instructions, document_text=document_text)
        payload = self._build_payload(instructions, user_content)
        self._warn_remote_upload(payload["model"], vision=vision)
        request = _RequestState(payload, format_fallback_used=self._json_mode_unsupported)
        while True:
            attempt = _Attempt(
                self._attempt_started() if self._attempt_started is not None else None
            )
            try:
                response = self._client.post(f"{self.base_url}/chat/completions", json=payload)
                action, parameter = self._classify_response(response, request)
                if action == "json_mode_fallback":
                    self._fall_back_from_json_mode(attempt, response, request)
                    continue
                if action == "rejected_parameter":
                    assert parameter is not None
                    self._drop_rejected_parameter(attempt, parameter, request)
                    continue
                if action == "retry":
                    self._back_off(attempt, request)
                    continue
                return self._accept_response(attempt, response)
            except httpx.TransportError as exc:
                self._handle_transport_error(attempt, exc, request)
                continue
            except LLMError:
                self._finish_attempt(attempt)
                raise
            except (httpx.HTTPError, ValueError, IndexError, KeyError, TypeError):
                self._finish_attempt(attempt)
                # Never print raw response bodies, exception chains or untrusted
                # provider labels: an API can echo book text or secrets.
                raise LLMError(
                    f"{self._provider_label()} LLM request or JSON decoding failed"
                ) from None
            except Exception:
                self._finish_attempt(attempt)
                raise


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
