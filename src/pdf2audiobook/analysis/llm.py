"""LLM proposals: deciding whether to ask, running the requests, and collecting the answers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pdf2audiobook.analysis.cleanup import _deterministic_fallback
from pdf2audiobook.analysis.state import _AnalysisRun, _AnalysisState
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import (
    propose_llm_classification,
    propose_llm_contents_boundaries,
    propose_llm_narration,
)
from pdf2audiobook.llm.equations import propose_llm_equation_readings
from pdf2audiobook.models import (
    DocumentBlock,
)
from pdf2audiobook.pdf import ExtractedDocument
from pdf2audiobook.progress_display import ProgressHandle

if TYPE_CHECKING:
    from pdf2audiobook.llm.cache import CachedLLMProvider


def _llm_analysis_requested(settings: Settings) -> bool:
    """Whether the LLM is on and any LLM analysis task is selected."""
    return settings.llm.enabled and (
        settings.llm.structure
        or settings.llm.contents
        or settings.llm.cleanup
        or settings.llm.classification
        or settings.llm.narration
        or settings.llm.vision
        or settings.reading.process_equations
    )


def _cached_llm_worker(run: _AnalysisRun, provider: Any) -> CachedLLMProvider:
    """Wrap the provider in the book's request cache and budget ledger."""
    settings = run.settings
    folder = run.folder
    return run.services.CachedLLMProvider(
        provider,
        cache_dir=folder / ".cache" / "llm",
        identity=run.services._llm_cache_identity(settings),
        enabled=settings.cache.enabled and settings.general.resume,
        max_requests=settings.llm.max_requests,
        max_reported_tokens=settings.llm.max_reported_tokens,
        max_estimated_cost_usd=settings.llm.max_estimated_cost_usd,
        input_cost_usd_per_million_tokens=(settings.llm.input_cost_usd_per_million_tokens),
        output_cost_usd_per_million_tokens=(settings.llm.output_cost_usd_per_million_tokens),
        usage_report=folder / "reports" / "llm_usage.json",
        ledger_path=folder / "reports" / "llm_budget.sqlite3",
    )


def _run_llm_tasks(
    run: _AnalysisRun,
    worker: CachedLLMProvider,
    source_blocks: list[DocumentBlock],
    state: _AnalysisState,
) -> None:
    """Run each selected LLM task; every result is a proposal or advisory report."""
    settings = run.settings
    folder = run.folder
    warnings = state.warnings
    if settings.llm.vision:
        from pdf2audiobook.llm.vision import review_visual_pages

        visual_review = review_visual_pages(run.source, worker)
        run.services.write_json(folder / "reports" / "vision_review.json", visual_review)
        if visual_review["pages"] or visual_review["warnings"]:
            warnings.append("Vision review suggestions are untrusted; inspect vision_review.json")
    if settings.llm.structure:
        state.llm_ids, heading_warnings = run.services.detect_llm_headings(
            source_blocks,
            worker,
            chunk_tokens=settings.llm.chunk_tokens,
            decisions=state.llm_decisions,
        )
        # Keep deterministic footnote-policy warnings in the audit.
        # Replacing the list also corrupts the fallback warning prefix.
        warnings.extend(heading_warnings)
    if settings.llm.contents:
        content_heading_ids, content_warnings = propose_llm_contents_boundaries(
            source_blocks,
            worker,
            chunk_tokens=settings.llm.chunk_tokens,
            decisions=state.llm_decisions,
        )
        state.llm_ids.update(content_heading_ids)
        warnings.extend(content_warnings)
    if settings.llm.cleanup:
        suggestions, edit_warnings = run.services.propose_llm_cleanup(
            source_blocks,
            worker,
            decisions=state.llm_decisions,
            chunk_tokens=settings.llm.chunk_tokens,
        )
        state.edits.extend(suggestions)
        warnings.extend(edit_warnings)
    if settings.llm.classification:
        classified, class_warnings = propose_llm_classification(
            source_blocks,
            worker,
            chunk_tokens=settings.llm.chunk_tokens,
            decisions=state.llm_decisions,
        )
        warnings.extend(class_warnings)
        run.services.write_json(
            folder / "reports" / "classification_suggestions.json",
            {
                "schema_version": 1,
                "requires_manual_review": True,
                "labels": [item.model_dump() for item in classified],
            },
        )
    if settings.llm.narration:
        spoken_suggestions, spoken_warnings = propose_llm_narration(
            source_blocks,
            worker,
            chunk_tokens=settings.llm.chunk_tokens,
            decisions=state.llm_decisions,
        )
        warnings.extend(spoken_warnings)
        # Deliberately separate from approved CleanupEdits and chapter
        # texts. This report is advisory and never changes audio.
        run.services.write_json(
            folder / "reports" / "narration_suggestions.json",
            {
                "schema_version": 1,
                "requires_manual_review": True,
                "suggestions": [item.model_dump() for item in spoken_suggestions],
            },
        )
    if settings.reading.process_equations:
        # Pending edits only: nothing changes narration until a person
        # accepts it with ``pdf2audiobook edits accept``.
        equation_edits, equation_warnings = propose_llm_equation_readings(
            source_blocks,
            worker,
            chunk_tokens=settings.llm.chunk_tokens,
            decisions=state.llm_decisions,
        )
        state.edits.extend(equation_edits)
        warnings.extend(equation_warnings)


def _llm_proposals(run: _AnalysisRun, extracted: ExtractedDocument, state: _AnalysisState) -> None:
    """Gather LLM proposals, falling back to deterministic analysis when allowed.

    Writes the LLM cleanup audit and decision reports either way.
    """
    settings = run.settings
    original_warning_count = len(state.warnings)
    llm_progress: ProgressHandle | None = None
    try:
        if _llm_analysis_requested(settings):
            # Only anchored proposals are accepted. OCR cleanup requires manual approval.
            source_blocks = [block for block in extracted.blocks if block.id not in state.omitted]
            with run.services.create_provider(settings) as provider:
                worker = _cached_llm_worker(run, provider)
                if run.progress is not None and run.progress.enabled:
                    llm_progress = run.progress.stage("Analyzing with the LLM", None, "request")
                    worker.progress = llm_progress
                _run_llm_tasks(run, worker, source_blocks, state)
    except LLMError:
        if not settings.llm.fallback_to_deterministic:
            raise
        _deterministic_fallback(run, state, original_warning_count)
    if llm_progress is not None:
        llm_progress.close()
    for decision in state.llm_decisions:
        decision.provider = settings.llm.provider
    run.services.write_json(
        run.folder / "reports" / "llm_cleanup_audit.json",
        {
            "schema_version": 2,
            "requires_manual_review": True,
            "decisions": [
                item.model_dump() for item in state.llm_decisions if item.task == "cleanup"
            ],
        },
    )
    run.services.write_json(
        run.folder / "reports" / "llm_decisions.json",
        {
            "schema_version": 1,
            "requires_manual_review": True,
            "decisions": [item.model_dump() for item in state.llm_decisions],
        },
    )
