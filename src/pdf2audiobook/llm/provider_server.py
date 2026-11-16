"""Server discovery: the served model, health, and the context length Ollama serves."""

from __future__ import annotations

import httpx

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.provider_base import ProviderState


class ServerMixin(ProviderState):
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
            raise LLMError(
                "Could not discover the served LLM models", error_reason="llm_unreachable"
            ) from None

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
                raise LLMError(
                    "Could not read the context length Ollama serves for the model",
                    error_reason="llm_unreachable",
                )
            self._served_context = min(lengths)
        return self._served_context
