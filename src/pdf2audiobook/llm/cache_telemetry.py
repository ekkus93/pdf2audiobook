"""Per-request telemetry: progress, the request log and the slow-request warning. Logs counters only, never content."""

from __future__ import annotations

import logging

from pdf2audiobook.llm.cache_base import CacheState
from pdf2audiobook.llm.usage import valid_usage_count
from pdf2audiobook.logging import log_event


class CacheTelemetryMixin(CacheState):
    def expect_requests(self, count: int, stage: str) -> None:
        """Announce how many requests a stage will make so progress can show a total."""
        if self.progress is None or count <= 0:
            return
        self._expected_requests += count
        self.progress.set_total(self._expected_requests)
        self.progress.set_detail(stage)
        self._stage = stage

    def _observe(self, seconds: float, error: Exception | None = None) -> None:
        """Log one finished request without any content, and warn once per stage when slow."""
        usage = getattr(self.provider, "last_usage", None)
        usage = usage if isinstance(usage, dict) else {}
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        fields: dict[str, object] = {
            "stage": self._stage or "unknown",
            "seconds": round(seconds, 1),
        }
        if valid_usage_count(prompt):
            fields["prompt_tokens"] = prompt
        if valid_usage_count(completion):
            fields["completion_tokens"] = completion
        if error is not None:
            reason = getattr(error, "reason", None)
            log_event(
                "llm_request_failed",
                level=logging.DEBUG,
                reason=reason if isinstance(reason, str) else type(error).__name__,
                **fields,
            )
            return
        log_event("llm_request", level=logging.DEBUG, **fields)
        stage = str(fields["stage"])
        previous = self._seconds.setdefault(stage, [])
        tokens = self._completion_tokens.setdefault(stage, [])
        long_wait = len(previous) >= 5 and seconds > max(120.0, 4 * sum(previous) / len(previous))
        long_answer = (
            valid_usage_count(completion)
            and len(tokens) >= 5
            and completion > max(4000, 4 * sum(tokens) / len(tokens))
        )
        if (long_wait or long_answer) and stage not in self._slow_warned:
            self._slow_warned.add(stage)
            log_event("llm_slow_request", level=logging.WARNING, **fields)
        previous.append(seconds)
        if valid_usage_count(completion):
            tokens.append(completion)

    def _note_request(self, *, cached: bool) -> None:
        if self.progress is not None:
            self.progress.advance(1, cached=cached)
