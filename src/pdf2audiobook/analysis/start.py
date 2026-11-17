"""Starting an analysis: reuse of an earlier analysis, footnote policy changes, and extraction."""

from __future__ import annotations

import logging
from pathlib import Path

from pdf2audiobook.analysis.state import AnalysisServices, _AnalysisRun
from pdf2audiobook.analysis_state import (
    _change_footnote_policy,
    _changed_analysis_stages,
)
from pdf2audiobook.chapter_selection import refresh_empty_chapter_reason
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import ExtractionError, InputError
from pdf2audiobook.models import (
    BookManifest,
    generated_chapter_fingerprint,
)
from pdf2audiobook.pdf import DocumentExtractor, ExtractedDocument
from pdf2audiobook.progress_display import ProgressReporter
from pdf2audiobook.workspace import fingerprint


def _start_analysis(
    source: Path,
    settings: Settings,
    extractor: DocumentExtractor | None,
    progress: ProgressReporter | None,
    services: AnalysisServices,
) -> _AnalysisRun:
    """Hash the source, resolve an automatic model and fingerprint each stage."""
    services.log_event("stage_started", level=logging.INFO, stage="analysis")

    # These exceptions can include private book names and absolute paths.
    # Avoid rendering user-supplied source identifiers in public diagnostics.
    try:
        if not source.is_file():
            raise InputError("PDF not found; check the input path and permissions")
        book_hash = services.digest_file(source)
    except OSError:
        raise InputError("Cannot access PDF; check the input path and permissions") from None
    settings = services._resolve_auto_llm_model(settings)
    root = Path(settings.general.output_dir).expanduser()
    folder = root / f"{source.stem}-{book_hash[:10]}"
    stage_fingerprints = services._analysis_stage_fingerprints(book_hash, settings, extractor)
    return _AnalysisRun(
        source=source,
        settings=settings,
        extractor=extractor,
        progress=progress,
        book_hash=book_hash,
        folder=folder,
        manifest_path=folder / "manifest.json",
        stage_fingerprints=stage_fingerprints,
        analysis_key=fingerprint(stage_fingerprints),
        services=services,
    )


def _switch_footnote_policy(run: _AnalysisRun, existing: BookManifest) -> bool:
    """Apply a footnote-policy-only change to an existing analysis in place.

    Returns True when the manifest was updated and analysis can stop.
    """
    from pdf2audiobook.chapter_artifacts import load_artifact_state

    settings = run.settings
    artifact_state = load_artifact_state(run.folder)
    if artifact_state is None or artifact_state["footnotes"] == settings.pdf.footnotes:
        return False
    previous_settings = settings.model_copy(deep=True)
    previous_settings.pdf.footnotes = artifact_state["footnotes"]
    previous_key = fingerprint(
        run.services._analysis_stage_fingerprints(run.book_hash, previous_settings, run.extractor)
    )
    if existing.analysis_fingerprint != previous_key:
        return False
    updated = _change_footnote_policy(existing, artifact_state["footnotes"], settings.pdf.footnotes)
    updated.analysis_fingerprint = run.analysis_key
    refresh_empty_chapter_reason(run.manifest_path, updated, persist=False)
    run.services.render_chapter_texts(
        updated, run.folder, settings.pdf.footnotes, commit_manifest=True
    )
    run.services.write_json(
        run.folder / "reports" / "analysis_fingerprints.json",
        {"schema_version": 1, "stages": run.stage_fingerprints},
    )
    return True


def _reuse_existing_analysis(run: _AnalysisRun) -> bool:
    """Decide whether an existing manifest is kept, updated or must be refused.

    Records the existing manifest and its hand-edited chapters on `run`.
    Returns True when the existing analysis stands and nothing more runs.
    Approved or protected content blocks a changed analysis.
    """
    settings = run.settings
    if not run.manifest_path.is_file():
        return False
    existing = run.services.read_manifest(run.manifest_path)
    run.existing_manifest = existing
    run.hand_edited_chapters = [
        chapter
        for chapter in existing.chapters
        if chapter.generated_fingerprint is not None
        and chapter.generated_fingerprint != generated_chapter_fingerprint(chapter)
    ]
    rejected_deterministic_edits = [
        edit for edit in existing.edits if edit.provider == "deterministic" and not edit.accepted
    ]
    same_input = existing.input_sha256 == run.book_hash
    same_analysis = existing.analysis_fingerprint == run.analysis_key
    other_approved_content = (
        existing.approved
        or any(ch.manually_approved for ch in existing.chapters)
        or any(edit.accepted and edit.provider != "deterministic" for edit in existing.edits)
    )
    approved_content = other_approved_content or bool(rejected_deterministic_edits)
    if same_input and same_analysis and (settings.general.resume or approved_content):
        if approved_content and not settings.general.resume:
            run.services.log_event(
                "analysis_preserved",
                level=logging.WARNING,
                reason="unchanged_approved_analysis",
            )
        # Regenerate missing or stale derived texts without replacing user edits.
        run.services.render_chapter_texts(existing, run.folder, settings.pdf.footnotes)
        return True
    if same_input and not same_analysis and _switch_footnote_policy(run, existing):
        return True
    if approved_content:
        changed_stages = _changed_analysis_stages(run.folder, run.stage_fingerprints)
        if other_approved_content or not rejected_deterministic_edits:
            raise ExtractionError(
                "This workspace contains manually approved or protected chapter/cleanup edits. "
                "Changed analysis stage(s): "
                + ", ".join(changed_stages)
                + ". Use a new --output directory for changed analysis."
            )
    return False


def _extract(run: _AnalysisRun) -> ExtractedDocument:
    """Extract the book with the default or the supplied backend."""
    settings = run.settings
    progress = run.progress
    ocr_cache_dir = (run.folder / ".cache" / "ocr") if settings.cache.enabled else None
    if run.extractor is None:
        extracted = run.services.extract_pdf(
            run.source,
            settings.pdf,
            ocr_cache_dir=ocr_cache_dir,
            source_sha256=run.book_hash,
            progress=progress if progress is not None and progress.enabled else None,
        )
    else:
        extracted = run.extractor.extract(
            run.source, settings.pdf, ocr_cache_dir=ocr_cache_dir, source_sha256=run.book_hash
        )
    run.services.log_event(
        "stage_completed", level=logging.INFO, stage="extraction", count=len(extracted.blocks)
    )
    return extracted
