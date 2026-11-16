"""Serving one request: bounds and capacity checks, the budget gate, sending it, and recording the result."""

from __future__ import annotations

import time
from typing import Any

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.cache_base import CacheState
from pdf2audiobook.llm.usage import verified_usage
from pdf2audiobook.workspace import write_json


class CacheRequestMixin(CacheState):
    def _check_request_bounds(
        self, instructions: str, document_text: str, image_data: bytes | None
    ) -> None:
        """Reject an oversized request, or an unsupported image, before anything else."""
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

    def _check_served_capacity(
        self, instructions: str, document_text: str, image_data: bytes | None
    ) -> None:
        """Check server-side limits; called only on a cache miss."""
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

    def _prepare_provider(self, attempt_accounting: bool) -> None:
        """Clear stale usage, restore known capability limits and count the request."""
        # A failed response can still incur charges. Never reuse stale usage.
        if hasattr(self.provider, "last_usage"):
            self.provider.last_usage = {}
        unsupported = getattr(self.provider, "_unsupported_parameters", None)
        json_mode_unsupported = getattr(self.provider, "_json_mode_unsupported", None)
        saved_unsupported, saved_json_mode_unsupported = self._load_capabilities()
        if isinstance(unsupported, set):
            unsupported.update(saved_unsupported)
        if isinstance(json_mode_unsupported, bool):
            self.provider._json_mode_unsupported = (
                json_mode_unsupported or saved_json_mode_unsupported
            )
        if not attempt_accounting:
            self.requests_started += 1
        self._write_usage()

    def _send_request(
        self,
        instructions: str,
        document_text: str,
        image_data: bytes | None,
        reservation: int | None,
    ) -> tuple[Any, float]:
        """Send the request, then always record usage and settle any reservation.

        Returns the reply and the monotonic time the request started.
        """
        request_error: Exception | None = None
        request_started = time.monotonic()
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
            self._observe(time.monotonic() - request_started, exc)
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
        return reply, request_started

    def _complete_json_call(
        self, *, instructions: str, document_text: str, image_data: bytes | None
    ) -> dict[str, Any]:
        """Serve a request from the cache, or send it under the book's budget.

        Fail-closed order: request bounds before the cache lookup (so a hit
        never skips the oversized-request rejection), then on a miss the
        budget bounds, server limits and reservation before the request, and
        verified usage after it.
        """
        self._resolve_served_identity()
        self._check_request_bounds(instructions, document_text, image_data)
        key = self._request_key(instructions, document_text, image_data)
        target = self.cache_dir / f"{key}.json"
        cached = self._cached_response(key, target)
        if cached is not None:
            return cached
        self.misses += 1
        upper_bound_tokens, upper_bound_usd = self._request_upper_bounds(
            instructions, document_text, image_data
        )
        self._check_served_capacity(instructions, document_text, image_data)
        reservation, attempt_accounting = self._reserve_budget(
            key, upper_bound_tokens, upper_bound_usd
        )
        self._prepare_provider(attempt_accounting)
        reply, request_started = self._send_request(
            instructions, document_text, image_data, reservation
        )
        reply = self._check_verified_usage(reply)
        if self.enabled:
            write_json(target, {"schema_version": 1, "fingerprint": key, "response": reply})
        self._observe(time.monotonic() - request_started)
        self._note_request(cached=False)
        return reply
