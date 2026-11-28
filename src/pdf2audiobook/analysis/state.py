"""Analysis state: the services a run is given, and the per-run and per-stage records."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pdf2audiobook.config import Settings
from pdf2audiobook.llm import (
    LLMDecision,
)
from pdf2audiobook.models import (
    BookManifest,
    Chapter,
    CleanupEdit,
    DocumentBlock,
)
from pdf2audiobook.pdf import DocumentExtractor
from pdf2audiobook.progress_display import ProgressReporter


@dataclass(frozen=True)
class AnalysisServices:
    """The analysis dependencies that tests patch on `pipeline`, looked up at call time."""

    CachedLLMProvider: Any
    _analysis_stage_fingerprints: Callable[..., Any]
    _llm_cache_identity: Callable[..., Any]
    _resolve_auto_llm_model: Callable[..., Any]
    create_provider: Callable[..., Any]
    detect_llm_headings: Callable[..., Any]
    digest_file: Callable[..., Any]
    extract_pdf: Callable[..., Any]
    log_event: Callable[..., Any]
    pagination_cleanup: Callable[..., Any]
    propose_chapters: Callable[..., Any]
    propose_llm_cleanup: Callable[..., Any]
    propose_llm_cleanup_and_narration: Callable[..., Any]
    read_manifest: Callable[..., Any]
    render_chapter_texts: Callable[..., Any]
    write_json: Callable[..., Any]


@dataclass
class _AnalysisRun:
    """Inputs and workspace paths for one locked analysis, fixed once it starts."""

    source: Path
    settings: Settings
    extractor: DocumentExtractor | None
    progress: ProgressReporter | None
    book_hash: str
    folder: Path
    manifest_path: Path
    stage_fingerprints: dict[str, str]
    analysis_key: str
    services: AnalysisServices
    existing_manifest: BookManifest | None = None
    hand_edited_chapters: list[Chapter] = field(default_factory=list)


@dataclass
class _AnalysisState:
    """Edits, warnings and review reasons gathered by the analysis steps.

    `warnings` starts as the pagination warnings and is appended to in step
    order; the deterministic fallback replaces it. `omitted` holds the ids of
    blocks removed by accepted deterministic edits.
    """

    edits: list[CleanupEdit]
    omitted: set[str]
    footnotes: list[DocumentBlock]
    warnings: list[str]
    review_reasons: set[str]
    llm_ids: set[str] = field(default_factory=set)
    llm_decisions: list[LLMDecision] = field(default_factory=list)
