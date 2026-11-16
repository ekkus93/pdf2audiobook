"""Option parsing shared by analyze, convert and batch."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import (
    ConfigError,
)


def _overrides(
    output: Path | None,
    ocr: str | None,
    no_llm: bool,
    llm_provider: str | None,
    llm_model: str | None,
    llm_url: str | None,
    allow_remote_content: bool | None,
    tts_model: str | None,
    voice: str | None,
    bitrate: str | None,
    resume: bool | None,
    allow_single_chapter: bool | None,
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    if output is not None:
        value.setdefault("general", {})["output_dir"] = str(output)
    if resume is not None:
        value.setdefault("general", {})["resume"] = resume
    if ocr is not None:
        value.setdefault("pdf", {})["ocr"] = ocr
    if llm_provider is not None:
        value.setdefault("llm", {})["provider"] = llm_provider
    if no_llm:
        value.setdefault("llm", {})["enabled"] = False
    if allow_remote_content is not None:
        value.setdefault("llm", {})["allow_remote_content"] = allow_remote_content
    if llm_model is not None or llm_url is not None:
        provider = (llm_provider or "ollama").replace("-", "_")
        section = value.setdefault("llm", {}).setdefault(provider, {})
        if llm_model is not None:
            section["model"] = llm_model
        if llm_url is not None:
            section["base_url"] = llm_url
    if bitrate:
        value.setdefault("tts", {})["bitrate"] = bitrate
    if allow_single_chapter is not None:
        value.setdefault("chapters", {})["allow_single_chapter"] = allow_single_chapter
    return value


def parse_chapter_range(value: str) -> tuple[int, int]:
    """Parse inclusive, human-friendly 1-based A:B chapter selection."""
    if re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", value) is None:
        raise ConfigError("chapter range must be 1-based A:B, e.g. 2:5")
    first, last = (int(value_part) for value_part in value.split(":"))
    if last < first:
        raise ConfigError("chapter range end must not precede start")
    return first, last


def _convert_overrides(
    preliminary: Settings,
    *,
    output: Path | None,
    ocr: str | None,
    pdf_password_env: str | None,
    llm_provider: str | None,
    llm_model: str | None,
    llm_url: str | None,
    llm_context_tokens: int | None,
    llm_output_tokens: int | None,
    process_citations: bool | None,
    process_equations: bool | None,
    allow_remote_content: bool | None,
    llm: bool | None,
    vision: bool | None,
    tts_provider: str | None,
    tts_model: str | None,
    voice: str | None,
    bitrate: str | None,
    speed: float | None,
    sample_rate: int | None,
    cover: Path | None,
    resume: bool | None,
    allow_single_chapter: bool | None,
) -> dict[str, Any]:
    """Turn `convert` options into settings overrides.

    `--llm-model` and `--llm-url` apply to the configured provider, and TTS
    model, voice and speed to the effective TTS provider.
    """
    provider = llm_provider or preliminary.llm.provider
    overrides = _overrides(
        output,
        ocr,
        llm is False,
        llm_provider,
        llm_model,
        llm_url,
        allow_remote_content,
        tts_model,
        voice,
        bitrate,
        resume,
        allow_single_chapter,
    )
    if llm_model is not None or llm_url is not None:
        selected = provider.replace("-", "_")
        if selected != "ollama" and llm_provider is None:
            overrides["llm"][selected] = overrides["llm"].pop("ollama")
    from pdf2audiobook.pipeline import tts_selection

    effective_tts_provider, _effective_voice, _effective_speed = tts_selection(
        preliminary, provider=tts_provider
    )
    tts_values = overrides.setdefault("tts", {})
    if tts_provider is not None:
        tts_values["provider"] = tts_provider
    if tts_model is not None:
        key = "model_path" if effective_tts_provider == "piper" else "model"
        section = "piper" if effective_tts_provider == "piper" else "kitten"
        tts_values.setdefault(section, {})[key] = tts_model
    if voice is not None:
        tts_values.setdefault(effective_tts_provider, {})["voice"] = voice
    if pdf_password_env is not None:
        overrides.setdefault("pdf", {})["password_env"] = pdf_password_env
    if llm is True:
        overrides.setdefault("llm", {})["enabled"] = True
    if llm_context_tokens is not None:
        overrides.setdefault("llm", {})["max_context_tokens"] = llm_context_tokens
    if llm_output_tokens is not None:
        overrides.setdefault("llm", {})["max_output_tokens"] = llm_output_tokens
    if process_citations is not None:
        overrides.setdefault("reading", {})["process_citations"] = process_citations
    if process_equations is not None:
        overrides.setdefault("reading", {})["process_equations"] = process_equations
    if vision is not None:
        overrides.setdefault("llm", {})["vision"] = vision
    if speed is not None:
        overrides.setdefault("tts", {}).setdefault(effective_tts_provider, {})["speed"] = speed
    if sample_rate is not None:
        overrides.setdefault("tts", {})["sample_rate"] = sample_rate
    if cover is not None:
        overrides.setdefault("audio", {})["cover_image"] = str(cover)
    return overrides


def _check_accept_review(accept_review: list[str]) -> None:
    """Allow only book-wide review reasons to be acknowledged from the command line."""
    from pdf2audiobook.review_reasons import BOOK_WIDE_REVIEW_REASON_CODES

    if "empty_chapter" in accept_review:
        raise ConfigError(
            "empty_chapter cannot be accepted globally; approve the chapter in the review UI"
        )
    if not set(accept_review) <= set(BOOK_WIDE_REVIEW_REASON_CODES):
        raise ConfigError(
            "Unknown --accept-review reason; choose from "
            + ", ".join(BOOK_WIDE_REVIEW_REASON_CODES)
        )
