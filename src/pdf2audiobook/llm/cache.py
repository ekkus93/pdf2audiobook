"""Atomic content-addressed cache for LLM JSON responses (always revalidated by callers)."""

import json
from pathlib import Path
from typing import Any

from pdf2audiobook.errors import LLMError
from pdf2audiobook.workspace import fingerprint, write_json


class CachedLLMProvider:
    def __init__(
        self, provider: Any, *, cache_dir: Path, identity: str, enabled: bool = True,
        max_requests: int | None = None, usage_report: Path | None = None,
    ):
        self.provider = provider
        self.cache_dir = cache_dir
        self.identity = identity
        self.enabled = enabled
        self.max_requests = max_requests
        self.usage_report = usage_report
        self.hits = 0
        self.misses = 0
        self.requests_started = 0

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
        write_json(self.usage_report, {
            "schema_version": 1,
            "cache_hits": self.hits,
            "cache_misses": self.misses,
            "requests_started": self.requests_started,
            "max_requests": self.max_requests,
            "provider_reported_tokens": safe_usage,
            "scope": "current_analysis_run",
        })

    def complete_json(self, *, instructions: str, document_text: str) -> dict[str, Any]:
        key = fingerprint("llm-json-cache-v1", self.identity, instructions, document_text)
        target = self.cache_dir / f"{key}.json"
        if self.enabled and target.is_file():
            try:
                if target.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError("oversized LLM cache")
                entry = json.loads(target.read_text(encoding="utf-8"))
                if (
                    isinstance(entry, dict)
                    and entry.get("schema_version") == 1
                    and entry.get("fingerprint") == key
                    and isinstance(entry.get("response"), dict)
                ):
                    self.hits += 1
                    self._write_usage()
                    return entry["response"]
            except (OSError, ValueError, UnicodeError, TypeError):
                pass
        self.misses += 1
        if self.max_requests is not None and self.requests_started >= self.max_requests:
            self._write_usage()
            raise LLMError("LLM request budget exhausted; increase llm.max_requests")
        # Count before the call: even a failed request can incur provider charges.
        self.requests_started += 1
        self._write_usage()
        try:
            reply = self.provider.complete_json(
                instructions=instructions, document_text=document_text,
            )
        finally:
            self._write_usage()
        if not isinstance(reply, dict):
            raise ValueError("LLM cache requires a JSON-object response")
        if self.enabled:
            write_json(target, {"schema_version": 1, "fingerprint": key, "response": reply})
        return reply
