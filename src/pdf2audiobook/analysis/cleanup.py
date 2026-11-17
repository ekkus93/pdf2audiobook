"""Deterministic cleanup of the extracted text, and its fallback when the LLM isn't used."""

from __future__ import annotations

from pdf2audiobook.analysis.state import _AnalysisRun, _AnalysisState
from pdf2audiobook.analysis_state import (
    _preserve_rejected_deterministic_edits,
)
from pdf2audiobook.document.structure import (
    footnote_anchor_edits,
    footnote_omit_edits,
)
from pdf2audiobook.pdf import ExtractedDocument


def _deterministic_cleanup(run: _AnalysisRun, extracted: ExtractedDocument) -> _AnalysisState:
    """Apply pagination cleanup and the footnote policy as audited edits."""
    settings = run.settings
    pagination_warnings: list[str] = []
    review_reasons = set(getattr(extracted, "review_reasons", []))
    edits = run.services.pagination_cleanup(
        extracted.blocks,
        extracted.page_sizes,
        settings.pdf,
        page_labels=getattr(extracted, "page_labels", None),
        warnings=pagination_warnings,
        review_reasons=review_reasons,
    )
    # Only explicitly selected omit mode can remove a high-confidence note.
    # Source spans/blocks remain intact and every exclusion is audited.
    footnotes = [block for block in extracted.blocks if block.kind == "footnote"]
    if settings.pdf.footnotes == "omit":
        edits.extend(footnote_omit_edits(extracted.blocks))
    if footnotes and settings.pdf.footnotes in {"inline", "end", "omit"}:
        # Once notes are handled, their anchor digits ("world.5") would only
        # be read aloud as numbers. Removal is per anchor, audited, reversible.
        edits.extend(
            footnote_anchor_edits(
                extracted.blocks, {edit.block_id for edit in edits if edit.accepted}
            )
        )
    _preserve_rejected_deterministic_edits(run.existing_manifest, edits)
    omitted = {edit.block_id for edit in edits if edit.accepted and not edit.replacement}
    warnings: list[str] = pagination_warnings
    if footnotes and settings.pdf.footnotes == "omit":
        warnings.append(
            f"Excluded {len(footnotes)} conservatively classified footnote "
            "block(s) under explicit omit policy; inspect audited cleanup edits"
        )
    return _AnalysisState(
        edits=edits,
        omitted=omitted,
        footnotes=footnotes,
        warnings=warnings,
        review_reasons=review_reasons,
    )


def _deterministic_fallback(
    run: _AnalysisRun, state: _AnalysisState, original_warning_count: int
) -> None:
    """Discard every LLM result and write empty advisory reports."""
    settings = run.settings
    folder = run.folder
    # Fail closed to deterministic analysis: no partial model proposals,
    # rejected decisions or uncertain chapter boundaries may be retained.
    state.llm_ids.clear()
    state.edits = [edit for edit in state.edits if edit.provider != "llm"]
    state.llm_decisions.clear()
    state.warnings = state.warnings[:original_warning_count] + [
        "LLM provider failed; explicit deterministic fallback used"
    ]
    run.services.write_json(
        folder / "reports" / "classification_suggestions.json",
        {
            "schema_version": 1,
            "requires_manual_review": True,
            "labels": [],
        },
    )
    if settings.llm.vision:
        run.services.write_json(
            folder / "reports" / "vision_review.json",
            {
                "schema_version": 1,
                "prompt_version": "visual-review-v1",
                "requires_manual_review": True,
                "pages": [],
                "warnings": ["Visual review skipped after explicit deterministic fallback"],
            },
        )
    run.services.write_json(
        folder / "reports" / "narration_suggestions.json",
        {
            "schema_version": 1,
            "requires_manual_review": True,
            "suggestions": [],
        },
    )
