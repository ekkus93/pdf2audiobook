"""Versioned source-aligned document and narration representations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    schema_version: int = 1
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
    approved: bool = False
    analysis_fingerprint: str | None = None

    @model_validator(mode="after")
    def check_version(self) -> "BookManifest":
        if self.schema_version != 1:
            raise ValueError("unsupported manifest schema version")
        return self
