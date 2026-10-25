"""Versioned source-aligned document and narration representations."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceSpan(StrictModel):
    id: str
    page_index: int = Field(ge=0)
    page_label: str | None = None
    text: str
    bbox: tuple[float, float, float, float] | None = None
    origin: Literal["embedded", "ocr"] = "embedded"
    font: str | None = None
    font_size: float | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class DocumentBlock(StrictModel):
    id: str
    span_ids: list[str] = Field(default_factory=list)
    text: str
    page_index: int = Field(ge=0)
    kind: Literal[
        "heading", "paragraph", "list", "table", "footnote", "caption", "equation", "unknown"
    ] = "unknown"
    bbox: tuple[float, float, float, float] | None = None
    font_size: float | None = None
    order: int = Field(default=0, ge=0)


class CleanupEdit(StrictModel):
    block_id: str
    original: str
    replacement: str
    reason: str
    confidence: float = Field(ge=0, le=1)
    accepted: bool = False
    provider: str = "deterministic"


class Chapter(StrictModel):
    id: str
    number: int = Field(ge=1)
    title: str
    start_block: int = Field(ge=0)
    end_block: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    manually_approved: bool = False
    voice_id: str | None = None
    generated_fingerprint: str | None = None
    generated_title: str | None = None
    generated_start_block: int | None = None
    generated_end_block: int | None = None
    generated_voice_id: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("voice_id")
    @classmethod
    def validate_voice_id(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or len(value) > 128):
            raise ValueError("chapter voice_id must be nonempty and at most 128 characters")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def check_range(self) -> "Chapter":
        if self.end_block <= self.start_block:
            raise ValueError("chapter end_block must exceed start_block")
        return self


class NarrationChunk(StrictModel):
    id: str
    chapter_id: str
    number: int = Field(ge=1)
    text_hash: str
    audio_path: str | None = None
    status: Literal["pending", "completed", "failed"] = "pending"


class BookManifest(StrictModel):
    schema_version: Literal[3]
    input_sha256: str
    title: str
    author: str | None = None
    source_path: str
    blocks: list[DocumentBlock] = Field(default_factory=list)
    spans: list[SourceSpan] = Field(default_factory=list)
    edits: list[CleanupEdit] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    chunks: list[NarrationChunk] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    review_required: list[str] = Field(default_factory=list)
    review_acknowledged: list[str] = Field(default_factory=list)
    approved: bool = False
    analysis_fingerprint: str | None = None


def generated_chapter_fingerprint(chapter: Chapter) -> str:
    """Hash analysis-generated chapter identity fields for edit detection."""
    return _chapter_fingerprint(
        chapter.title, chapter.start_block, chapter.end_block, chapter.voice_id
    )


def generated_baseline_fingerprint(chapter: Chapter) -> str:
    """Hash the stored generated_* baseline after a controlled neighbour move."""
    return _chapter_fingerprint(
        chapter.generated_title if chapter.generated_title is not None else chapter.title,
        chapter.generated_start_block
        if chapter.generated_start_block is not None
        else chapter.start_block,
        chapter.generated_end_block
        if chapter.generated_end_block is not None
        else chapter.end_block,
        chapter.generated_voice_id,
    )


def _chapter_fingerprint(title: str, start: int, end: int, voice_id: str | None) -> str:
    payload = json.dumps(
        [title, start, end, voice_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
