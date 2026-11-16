"""The content-addressed response cache, the served-model identity, and saved provider capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pdf2audiobook.errors import LLMError
from pdf2audiobook.jsonio import load_bounded_json
from pdf2audiobook.llm.cache_base import (
    _MAX_CACHED_LLM_JSON_BYTES,
    _MAX_CACHED_LLM_JSON_DEPTH,
    CacheState,
)
from pdf2audiobook.workspace import digest_bytes, fingerprint, write_json


class CacheStoreMixin(CacheState):
    def _resolve_served_identity(self) -> None:
        """Key the cache by the served model when the provider resolves one."""
        resolve_model = getattr(self.provider, "resolve_model", None)
        if callable(resolve_model):
            resolved_model = resolve_model()
            if not isinstance(resolved_model, str) or not resolved_model:
                raise LLMError("LLM provider returned an invalid model identity")
            if self._resolved_model != resolved_model:
                self.identity = fingerprint(self._base_identity, "served-model", resolved_model)
                self._resolved_model = resolved_model

    def _request_key(self, instructions: str, document_text: str, image_data: bytes | None) -> str:
        """The content-addressed cache key of one request."""
        if image_data is None:
            return fingerprint("llm-json-cache-v1", self.identity, instructions, document_text)
        return fingerprint(
            "llm-json-image-cache-v1",
            self.identity,
            instructions,
            document_text,
            digest_bytes(image_data),
        )

    def _cached_response(self, key: str, target: Path) -> dict[str, Any] | None:
        """Return a valid cached response and count the hit, or None on a miss."""
        if not self.enabled:
            return None
        entry = load_bounded_json(
            target,
            max_bytes=_MAX_CACHED_LLM_JSON_BYTES,
            max_depth=_MAX_CACHED_LLM_JSON_DEPTH,
        )
        if (
            isinstance(entry, dict)
            and entry.get("schema_version") == 1
            and entry.get("fingerprint") == key
            and isinstance(entry.get("response"), dict)
        ):
            self.hits += 1
            self._write_usage()
            self._note_request(cached=True)
            response: dict[str, Any] = entry["response"]
            return response
        return None

    def _capability_path(self) -> Path:
        return (
            self.cache_dir
            / "provider-capabilities"
            / (fingerprint("unsupported-parameters-v1", self.identity) + ".json")
        )

    def _load_capabilities(self) -> tuple[set[str], bool]:
        data = load_bounded_json(self._capability_path(), max_bytes=4096, max_depth=4)
        values = data.get("unsupported", []) if isinstance(data, dict) else []
        if not isinstance(values, list):
            values = []
        allowed = {"max_tokens", "max_completion_tokens", "temperature"}
        unsupported = {value for value in values if isinstance(value, str) and value in allowed}
        json_mode_unsupported = isinstance(data, dict) and data.get("json_mode_unsupported") is True
        return unsupported, json_mode_unsupported

    def _save_unsupported_parameters(self) -> None:
        values = getattr(self.provider, "_unsupported_parameters", None)
        if not isinstance(values, set):
            return
        allowed = sorted(
            value
            for value in values
            if value in {"max_tokens", "max_completion_tokens", "temperature"}
        )
        json_mode_unsupported = getattr(self.provider, "_json_mode_unsupported", False) is True
        if not allowed and not json_mode_unsupported:
            return
        path = self._capability_path()
        current = load_bounded_json(path, max_bytes=4096, max_depth=4)
        value = {"schema_version": 1, "unsupported": allowed}
        if json_mode_unsupported:
            value["json_mode_unsupported"] = True
        if current != value:
            write_json(path, value)
