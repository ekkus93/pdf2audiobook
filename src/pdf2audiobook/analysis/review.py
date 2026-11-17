"""Chapter review gating and writing the analysis files."""

from __future__ import annotations

import logging
from pathlib import Path

from pdf2audiobook.analysis.state import _AnalysisRun, _AnalysisState
from pdf2audiobook.document.structure import (
    chapter_has_speakable_text,
    place_footnotes,
)
from pdf2audiobook.models import (
    BookManifest,
    Chapter,
)
from pdf2audiobook.pdf import ExtractedDocument
from pdf2audiobook.review_reasons import REVIEW_REASON_CODES


def _chapter_review(
    run: _AnalysisRun,
    extracted: ExtractedDocument,
    chapters: list[Chapter],
    state: _AnalysisState,
    chapter_warnings: list[str],
) -> None:
    """Flag empty chapters and add chapter, footnote and settings warnings."""
    settings = run.settings
    warnings = state.warnings
    for chapter in chapters:
        speakable = chapter_has_speakable_text(
            extracted.blocks,
            chapter.start_block,
            chapter.end_block,
            {i: "" for i in state.omitted},
        )
        if not speakable:
            state.review_reasons.add("empty_chapter")
            chapter.warnings.append("No speakable text after accepted cleanup; review manually")
            warnings.append(
                f"Chapter {chapter.number} has no speakable text after cleanup; review before synthesis"
            )
    warnings.extend(chapter_warnings)
    if state.footnotes and settings.pdf.footnotes in {"inline", "end"}:
        relocated = kept = 0
        for chapter in chapters:
            _, moved, stayed = place_footnotes(
                extracted.blocks[chapter.start_block : chapter.end_block], settings.pdf.footnotes
            )
            relocated += moved
            kept += stayed
        if settings.pdf.footnotes == "end":
            warnings.append(
                f"Narrating {relocated} classified footnote(s) at the end of their chapter; "
                "source blocks are unchanged"
            )
        else:
            warnings.append(
                f"Narrating {relocated} classified footnote(s) after the paragraph holding "
                f"their anchor; {kept} without a unique anchor keep their PDF position"
            )
    if settings.llm.enabled and not settings.llm.structure:
        warnings.append("LLM structure analysis disabled in settings")


def _write_analysis(
    run: _AnalysisRun,
    extracted: ExtractedDocument,
    chapters: list[Chapter],
    state: _AnalysisState,
) -> Path:
    """Write the manifest, chapter texts and stage fingerprints."""
    settings = run.settings
    manifest = BookManifest(
        schema_version=3,
        input_sha256=run.book_hash,
        title=extracted.title,
        author=extracted.author,
        source_path=str(run.source.resolve()),
        spans=extracted.spans,
        blocks=extracted.blocks,
        edits=state.edits,
        chapters=chapters,
        analysis_fingerprint=run.analysis_key,
        warnings=extracted.warnings + state.warnings,
        review_required=[code for code in REVIEW_REASON_CODES if code in state.review_reasons],
    )
    run.services.render_chapter_texts(
        manifest, run.folder, settings.pdf.footnotes, commit_manifest=True
    )
    run.services.write_json(
        run.folder / "reports" / "analysis_fingerprints.json",
        {"schema_version": 1, "stages": run.stage_fingerprints},
    )
    manifest_warnings = len(extracted.warnings + state.warnings)
    if manifest_warnings:
        run.services.log_event(
            "review_warning", level=logging.WARNING, stage="analysis", count=manifest_warnings
        )
    run.services.log_event(
        "stage_completed", level=logging.INFO, stage="analysis", count=len(chapters)
    )
    return run.manifest_path
