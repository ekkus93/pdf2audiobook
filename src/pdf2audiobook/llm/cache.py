"""Atomic content-addressed cache for LLM JSON responses (always revalidated by callers)."""

import json
from pathlib import Path
from typing import Any

from pdf2audiobook.workspace import fingerprint, write_json


class CachedLLMProvider:
    def __init__(self, provider: Any, *, cache_dir: Path, identity: str, enabled: bool = True):
        self.provider = provider
        self.cache_dir = cache_dir
        self.identity = identity
        self.enabled = enabled
        self.hits = 0
        self.misses = 0

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
                    return entry["response"]
            except (OSError, ValueError, UnicodeError, TypeError):
                pass
        self.misses += 1
        reply = self.provider.complete_json(
            instructions=instructions, document_text=document_text,
        )
        if not isinstance(reply, dict):
            raise ValueError("LLM cache requires a JSON-object response")
        if self.enabled:
            write_json(target, {"schema_version": 1, "fingerprint": key, "response": reply})
        return reply
