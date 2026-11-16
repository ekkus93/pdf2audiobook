"""Capacity checks before any book text leaves the machine: text and image token budgets."""

from __future__ import annotations

import struct

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.provider_base import ProviderState


class CapacityMixin(ProviderState):
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
                raise LLMError(
                    "LLM request exceeds configured context and output reserve",
                    error_reason="llm_context_too_small",
                )

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
                "lower llm.chunk_tokens or use a model with a larger num_ctx",
                error_reason="llm_context_too_small",
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
