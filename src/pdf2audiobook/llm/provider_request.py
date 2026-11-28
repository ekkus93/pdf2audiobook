"""The chat request loop: payload, retries, JSON-mode and parameter fallbacks, and answer decoding."""

from __future__ import annotations

import base64
import json
import re
import sys
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from pdf2audiobook.errors import LLMAnswerCutOff, LLMError
from pdf2audiobook.llm.provider_base import (
    MAX_VISUAL_REVIEW_PAGES,
    ProviderState,
    _Attempt,
    _loopback,
    _RequestState,
    _ResponseAction,
)


class RequestMixin(ProviderState):
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

    def complete_json(self, *, instructions: str, document_text: str) -> dict[str, Any]:
        return self._complete_json_request(
            instructions=instructions,
            document_text=document_text,
            user_content=document_text,
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
                error_reason="llm_output_cap",
            )
        try:
            decoded = json.loads(message)
        except ValueError:
            if truncated:
                raise LLMAnswerCutOff() from None
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
        unreachable = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
        raise LLMError(
            f"{label} LLM transport failure",
            unbilled=unreachable,
            error_reason="llm_unreachable" if unreachable else None,
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
