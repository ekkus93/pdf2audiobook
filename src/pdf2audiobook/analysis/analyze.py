"""The analysis of one book: the steps in order, under the workspace lock."""

from __future__ import annotations

from pathlib import Path

from pdf2audiobook.analysis.cleanup import _deterministic_cleanup
from pdf2audiobook.analysis.hand_edits import _merge_hand_edits
from pdf2audiobook.analysis.llm import _llm_proposals
from pdf2audiobook.analysis.review import _chapter_review, _write_analysis
from pdf2audiobook.analysis.start import _extract, _reuse_existing_analysis, _start_analysis
from pdf2audiobook.analysis.state import AnalysisServices
from pdf2audiobook.config import Settings
from pdf2audiobook.document.narration import FIGURE_TEXT_OMIT_REASON
from pdf2audiobook.pdf import DocumentExtractor
from pdf2audiobook.progress_display import ProgressReporter


def _analyze_book_locked(
    source: Path,
    settings: Settings,
    *,
    extractor: DocumentExtractor | None = None,
    progress: ProgressReporter | None = None,
    services: AnalysisServices,
) -> Path:
    """Run every analysis step in order; the caller holds the workspace lock.

    Steps: start (hash and fingerprints), reuse of an existing analysis,
    extraction, deterministic cleanup, LLM proposals, chapter proposal, the
    hand-edit merge, chapter review, then the manifest and reports.
    """
    run = _start_analysis(source, settings, extractor, progress, services)
    if _reuse_existing_analysis(run):
        return run.manifest_path
    extracted = _extract(run)
    state = _deterministic_cleanup(run, extracted)
    _llm_proposals(run, extracted, state)
    # Whether figure text is narrated must not move chapter boundaries: under
    # pdf.figure_text = omit the paper's 12 chapters became 1, because leaving its
    # figure labels out shifted the body size the heading test compares against.
    figure_omitted = {
        edit.block_id for edit in state.edits if edit.reason == FIGURE_TEXT_OMIT_REASON
    }
    chapter_proposal = services.propose_chapters(
        extracted.blocks,
        state.omitted - figure_omitted,
        extracted.toc,
        run.settings.chapters,
        extra_heading_ids=state.llm_ids,
    )
    chapters, chapter_warnings = chapter_proposal
    state.review_reasons.update(getattr(chapter_proposal, "review_reasons", set()))
    _merge_hand_edits(run, extracted, chapters, state.warnings)
    _chapter_review(run, extracted, chapters, state, chapter_warnings)
    return _write_analysis(run, extracted, chapters, state)
