"""Inspectably staged PDF analysis and resumable audio generation."""

from __future__ import annotations

import logging
import os as os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pdf2audiobook.analysis_state import (
    _change_footnote_policy,
    _changed_analysis_stages,
    _hand_edit_conflict,
    _match_edited_chapter,
    _preserve_rejected_deterministic_edits,
)
from pdf2audiobook.audio import (
    AudioEncoder,
    audio_output_path,
    encode_mp3,
    read_cover_image,
    read_synthesis_progress,
    synthesize_chunks,
    unspeakable_pause_ranges,
    voice_marker_ids,
)
from pdf2audiobook.audio.freshness import valid_mp3_sidecar as valid_mp3_sidecar
from pdf2audiobook.chapter_selection import (
    ChapterSelection as ChapterSelection,
)
from pdf2audiobook.chapter_selection import (
    prepare_chapter_selection as _prepare_chapter_selection,
)
from pdf2audiobook.chapter_selection import (
    refresh_empty_chapter_reason as refresh_empty_chapter_reason,
)
from pdf2audiobook.chapter_selection import (
    select_chapters as select_chapters,
)
from pdf2audiobook.config import Settings
from pdf2audiobook.conversion import ConversionServices
from pdf2audiobook.conversion import _convert_analyzed_book as _run_conversion
from pdf2audiobook.document.structure import (
    chapter_has_speakable_text,
    footnote_anchor_edits,
    footnote_omit_edits,
    pagination_cleanup,
    place_footnotes,
    propose_chapters,
    render_chapter_texts,
    validate_chapter_coverage,
)
from pdf2audiobook.errors import (
    ExtractionError,
    InputError,
    LLMError,
    WorkspaceLockedError,
)
from pdf2audiobook.llm import (
    LLMDecision,
    create_provider,
    detect_llm_headings,
    propose_llm_classification,
    propose_llm_cleanup,
    propose_llm_contents_boundaries,
    propose_llm_narration,
)
from pdf2audiobook.llm.cache import CachedLLMProvider
from pdf2audiobook.llm.equations import propose_llm_equation_readings
from pdf2audiobook.logging import log_event
from pdf2audiobook.models import (
    BookManifest,
    Chapter,
    CleanupEdit,
    DocumentBlock,
    generated_baseline_fingerprint,
    generated_chapter_fingerprint,
)
from pdf2audiobook.pdf import DocumentExtractor, ExtractedDocument, extract_pdf
from pdf2audiobook.progress_display import (
    ProgressHandle,
    ProgressReporter,
    bind_workspace,
    current_reporter,
)
from pdf2audiobook.review_reasons import (
    REVIEW_REASON_CODES,
)
from pdf2audiobook.tts import KittenProvider, PiperProvider, TTSProvider
from pdf2audiobook.tts.selection import (
    _model_file_digest as _model_file_digest,
)
from pdf2audiobook.tts.selection import (
    _tts_model_identity as _tts_model_identity,
)
from pdf2audiobook.tts.selection import (
    chapter_voice as chapter_voice,
)
from pdf2audiobook.tts.selection import (
    settings_for_book_tts as settings_for_book_tts,
)
from pdf2audiobook.tts.selection import (
    tts_selection as tts_selection,
)
from pdf2audiobook.workspace import (
    digest_bytes,
    digest_file,
    fingerprint,
    read_manifest,
    workspace_lock,
    write_json,
)
from pdf2audiobook.workspace import write_manifest as write_manifest


def _llm_cache_identity(settings: Settings) -> str:
    """Include response-cap settings in the model-specific request cache namespace."""
    selected = getattr(settings.llm, settings.llm.provider.replace("-", "_"))
    return fingerprint(
        "llm-provider-v4",
        settings.llm.provider,
        selected.model,
        selected.base_url,
        settings.llm.temperature,
        settings.llm.max_context_tokens,
        settings.llm.chunk_tokens,
        settings.llm.max_output_tokens,
    )


def _resolve_auto_llm_model(settings: Settings) -> Settings:
    """Resolve a served model before analysis or request cache identities are computed."""
    selected = getattr(settings.llm, settings.llm.provider.replace("-", "_"))
    if not settings.llm.enabled or selected.model != "auto":
        return settings
    if not any(
        (
            settings.llm.structure,
            settings.llm.contents,
            settings.llm.cleanup,
            settings.llm.classification,
            settings.llm.narration,
            settings.llm.vision,
            settings.reading.process_equations,
        )
    ):
        return settings
    with create_provider(settings) as provider:
        resolve = getattr(provider, "resolve_model", None)
        if not callable(resolve):
            raise LLMError("LLM provider cannot resolve its automatic model")
        model = resolve()
    if not isinstance(model, str) or not model:
        raise LLMError("LLM provider returned an invalid automatic model")
    resolved = settings.model_copy(deep=True)
    getattr(resolved.llm, resolved.llm.provider.replace("-", "_")).model = model
    return resolved


def _analysis_stage_fingerprints(
    book_hash: str, settings: Settings, extractor: DocumentExtractor | None
) -> dict[str, str]:
    """Hash stage inputs separately while excluding operational policy limits."""
    llm_settings = settings.llm.model_dump(
        exclude={
            "openai",
            "ollama",
            "llama_server",
            "max_retries",
            "max_requests",
            "max_reported_tokens",
            "max_estimated_cost_usd",
            "input_cost_usd_per_million_tokens",
            "output_cost_usd_per_million_tokens",
            "allow_remote_content",
        }
    )
    chapter_settings = settings.chapters.model_dump(
        exclude={"allow_single_chapter", "min_boundary_confidence"}
    )
    llm_fingerprint = fingerprint("disabled")
    if settings.llm.enabled:
        selected = getattr(settings.llm, settings.llm.provider.replace("-", "_"))
        llm_fingerprint = fingerprint(
            llm_settings,
            settings.llm.provider,
            selected.model,
            selected.base_url,
        )
    return {
        "extraction": fingerprint(
            "analysis-v23",
            book_hash,
            settings.pdf.model_dump(),
            *(() if extractor is None else ("extractor", extractor.name)),
        ),
        "chapter-boundaries": fingerprint("chapter-detection-v5", chapter_settings),
        "llm-analysis": llm_fingerprint,
    }


def _progress_report_fields(
    progress: dict[str, object] | None,
) -> tuple[int | None, list[object] | None]:
    """Return report values, preserving unavailable progress as null fields."""
    mapping = progress.get("mapping") if progress is not None else None
    if not isinstance(mapping, list):
        return None, None
    pauses = [row for row in mapping if isinstance(row, dict) and row.get("kind") == "pause"]
    return len(pauses), mapping


def create_tts_provider(settings: Settings) -> TTSProvider:
    """Construct the selected TTS adapter in one place."""
    if settings.tts.provider == "piper":
        return PiperProvider(settings.tts.piper.model_path)
    return KittenProvider(settings.tts.kitten.model)


def _analysis_workspace_folder(source: Path, settings: Settings) -> Path:
    try:
        if not source.is_file():
            raise InputError("PDF not found; check the input path and permissions")
        book_hash = digest_file(source)
    except OSError:
        raise InputError("Cannot access PDF; check the input path and permissions") from None
    return Path(settings.general.output_dir).expanduser() / f"{source.stem}-{book_hash[:10]}"


def analyze_book(
    source: Path,
    settings: Settings,
    *,
    extractor: DocumentExtractor | None = None,
    progress: ProgressReporter | None = None,
) -> Path:
    """Analyze one book while holding its workspace lock for every write."""
    folder = _analysis_workspace_folder(source, settings)
    reporter = progress if progress is not None else current_reporter()
    bind_workspace(reporter, folder)
    try:
        with workspace_lock(folder, create=True):
            return _analyze_book_locked(source, settings, extractor=extractor, progress=reporter)
    except WorkspaceLockedError as exc:
        if str(exc) == "Could not lock the book workspace":
            raise ExtractionError("Could not create or update the output workspace") from None
        raise ExtractionError("Another conversion is already running for this book") from None


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


@dataclass
class _HandEditMerge:
    """State for carrying hand edits from the old manifest onto new chapters.

    `matches` maps an old chapter id to its new chapter. `field_changes` holds
    the queued field values per new chapter id; `changed_chapter_numbers`
    names the chapters any conflict message must cite.
    """

    existing_manifest: BookManifest
    new_positions: dict[str, int]
    new_block_count: int
    old_chapters: list[Chapter]
    edited_by_id: dict[str, Chapter]
    matches: dict[str, Chapter]
    changed_chapter_numbers: set[int]
    field_changes: dict[str, dict[str, int | str | None]] = field(default_factory=dict)
    explicit_boundary_fields: dict[str, set[str]] = field(default_factory=dict)
    moved_neighbor_fields: dict[str, set[str]] = field(default_factory=dict)


def _start_analysis(
    source: Path,
    settings: Settings,
    extractor: DocumentExtractor | None,
    progress: ProgressReporter | None,
) -> _AnalysisRun:
    """Hash the source, resolve an automatic model and fingerprint each stage."""
    log_event("stage_started", level=logging.INFO, stage="analysis")

    # These exceptions can include private book names and absolute paths.
    # Avoid rendering user-supplied source identifiers in public diagnostics.
    try:
        if not source.is_file():
            raise InputError("PDF not found; check the input path and permissions")
        book_hash = digest_file(source)
    except OSError:
        raise InputError("Cannot access PDF; check the input path and permissions") from None
    settings = _resolve_auto_llm_model(settings)
    root = Path(settings.general.output_dir).expanduser()
    folder = root / f"{source.stem}-{book_hash[:10]}"
    stage_fingerprints = _analysis_stage_fingerprints(book_hash, settings, extractor)
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
        _analysis_stage_fingerprints(run.book_hash, previous_settings, run.extractor)
    )
    if existing.analysis_fingerprint != previous_key:
        return False
    updated = _change_footnote_policy(existing, artifact_state["footnotes"], settings.pdf.footnotes)
    updated.analysis_fingerprint = run.analysis_key
    refresh_empty_chapter_reason(run.manifest_path, updated, persist=False)
    render_chapter_texts(updated, run.folder, settings.pdf.footnotes, commit_manifest=True)
    write_json(
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
    existing = read_manifest(run.manifest_path)
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
            log_event(
                "analysis_preserved",
                level=logging.WARNING,
                reason="unchanged_approved_analysis",
            )
        # Regenerate missing or stale derived texts without replacing user edits.
        render_chapter_texts(existing, run.folder, settings.pdf.footnotes)
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
        extracted = extract_pdf(
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
    log_event(
        "stage_completed", level=logging.INFO, stage="extraction", count=len(extracted.blocks)
    )
    return extracted


def _deterministic_cleanup(run: _AnalysisRun, extracted: ExtractedDocument) -> _AnalysisState:
    """Apply pagination cleanup and the footnote policy as audited edits."""
    settings = run.settings
    pagination_warnings: list[str] = []
    review_reasons = set(getattr(extracted, "review_reasons", []))
    edits = pagination_cleanup(
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
    return CachedLLMProvider(
        provider,
        cache_dir=folder / ".cache" / "llm",
        identity=_llm_cache_identity(settings),
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
        write_json(folder / "reports" / "vision_review.json", visual_review)
        if visual_review["pages"] or visual_review["warnings"]:
            warnings.append("Vision review suggestions are untrusted; inspect vision_review.json")
    if settings.llm.structure:
        state.llm_ids, heading_warnings = detect_llm_headings(
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
        suggestions, edit_warnings = propose_llm_cleanup(
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
        write_json(
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
        write_json(
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
    write_json(
        folder / "reports" / "classification_suggestions.json",
        {
            "schema_version": 1,
            "requires_manual_review": True,
            "labels": [],
        },
    )
    if settings.llm.vision:
        write_json(
            folder / "reports" / "vision_review.json",
            {
                "schema_version": 1,
                "prompt_version": "visual-review-v1",
                "requires_manual_review": True,
                "pages": [],
                "warnings": ["Visual review skipped after explicit deterministic fallback"],
            },
        )
    write_json(
        folder / "reports" / "narration_suggestions.json",
        {
            "schema_version": 1,
            "requires_manual_review": True,
            "suggestions": [],
        },
    )


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
            with create_provider(settings) as provider:
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
    write_json(
        run.folder / "reports" / "llm_cleanup_audit.json",
        {
            "schema_version": 2,
            "requires_manual_review": True,
            "decisions": [
                item.model_dump() for item in state.llm_decisions if item.task == "cleanup"
            ],
        },
    )
    write_json(
        run.folder / "reports" / "llm_decisions.json",
        {
            "schema_version": 1,
            "requires_manual_review": True,
            "decisions": [item.model_dump() for item in state.llm_decisions],
        },
    )


def _match_old_chapters(
    old_chapters: list[Chapter],
    chapters: list[Chapter],
    existing_manifest: BookManifest,
    new_positions: dict[str, int],
    edited_by_id: dict[str, Chapter],
) -> dict[str, Chapter]:
    """Match each old chapter to at most one new chapter.

    An edited chapter with no match, or one sharing its match with another
    chapter, is a conflict; an unedited one is skipped.
    """
    matches: dict[str, Chapter] = {}
    claimed_matches: dict[str, Chapter] = {}
    for old in old_chapters:
        match = _match_edited_chapter(old, chapters, existing_manifest, new_positions)
        if match is None:
            if old.id in edited_by_id:
                raise _hand_edit_conflict(
                    f"Chapter {old.number} was edited but cannot be aligned",
                    {old.number},
                )
            continue
        owner = claimed_matches.get(match.id)
        if owner is not None:
            if old.id in edited_by_id or owner.id in edited_by_id:
                if old.id in edited_by_id and owner.id not in edited_by_id:
                    message = f"Chapter {old.number} was edited but cannot be aligned"
                    numbers = {old.number}
                elif owner.id in edited_by_id and old.id not in edited_by_id:
                    message = f"Chapter {owner.number} was edited but cannot be aligned"
                    numbers = {owner.number}
                else:
                    message = "Edited chapters cannot be uniquely matched"
                    numbers = {old.number, owner.number}
                raise _hand_edit_conflict(
                    message,
                    numbers,
                )
            continue
        matches[old.id] = match
        claimed_matches[match.id] = old
    return matches


def _queue_change(
    merge: _HandEditMerge,
    item: Chapter,
    field_name: str,
    value: int | str | None,
    chapter_number: int,
) -> None:
    """Queue one field value for a new chapter; a different second value conflicts."""
    current = merge.field_changes.setdefault(item.id, {}).get(field_name)
    if field_name in merge.field_changes[item.id] and current != value:
        raise _hand_edit_conflict(
            "Edited boundaries conflict",
            merge.changed_chapter_numbers | {chapter_number},
        )
    merge.field_changes[item.id][field_name] = value


def _map_boundary(merge: _HandEditMerge, position: int) -> int | None:
    """Map an old block position to the new one through its block id."""
    blocks = merge.existing_manifest.blocks
    if position == len(blocks):
        return merge.new_block_count
    if position < 0 or position >= len(blocks):
        return None
    return merge.new_positions.get(blocks[position].id)


def _queue_moved_boundary(
    merge: _HandEditMerge,
    edited: Chapter,
    match: Chapter,
    old_index: int,
    field_name: str,
) -> None:
    """Queue an edited start or end, and the matching edge of the old neighbour."""
    position = edited.start_block if field_name == "start_block" else edited.end_block
    mapped = _map_boundary(merge, position)
    if mapped is None:
        raise _hand_edit_conflict(
            f"Chapter {edited.number} boundary cannot be aligned",
            {edited.number},
        )
    _queue_change(merge, match, field_name, mapped, edited.number)
    merge.explicit_boundary_fields.setdefault(match.id, set()).add(field_name)
    neighbor_index = old_index - 1 if field_name == "start_block" else old_index + 1
    if not 0 <= neighbor_index < len(merge.old_chapters):
        return
    old_neighbor = merge.old_chapters[neighbor_index]
    neighbor = merge.matches.get(old_neighbor.id)
    if neighbor is None:
        raise _hand_edit_conflict(
            "Edited boundary neighbor cannot be aligned",
            {old_neighbor.number, edited.number},
        )
    neighbor_field = "end_block" if field_name == "start_block" else "start_block"
    _queue_change(merge, neighbor, neighbor_field, mapped, edited.number)
    merge.moved_neighbor_fields.setdefault(neighbor.id, set()).add(neighbor_field)
    merge.changed_chapter_numbers.add(old_neighbor.number)


def _queue_hand_edits(merge: _HandEditMerge) -> None:
    """Queue every edited title, voice and boundary onto its matched new chapter."""
    block_count = len(merge.existing_manifest.blocks)
    for old_index, edited in enumerate(merge.old_chapters):
        if edited.id not in merge.edited_by_id:
            continue
        if (
            edited.start_block >= block_count
            or edited.end_block > block_count
            or edited.start_block < 0
            or edited.end_block < 0
        ):
            raise _hand_edit_conflict(
                f"Chapter {edited.number} was edited but cannot be aligned",
                {edited.number},
            )
        match = merge.matches.get(edited.id)
        if match is None:
            raise _hand_edit_conflict(
                f"Chapter {edited.number} was edited but cannot be aligned",
                {edited.number},
            )
        title_edited = edited.generated_title is not None and edited.title != edited.generated_title
        start_edited = (
            edited.generated_start_block is not None
            and edited.start_block != edited.generated_start_block
        )
        end_edited = (
            edited.generated_end_block is not None
            and edited.end_block != edited.generated_end_block
        )
        voice_edited = edited.generated_voice_id != edited.voice_id
        if start_edited:
            _queue_moved_boundary(merge, edited, match, old_index, "start_block")
        if end_edited:
            _queue_moved_boundary(merge, edited, match, old_index, "end_block")
        if title_edited:
            _queue_change(merge, match, "title", edited.title, edited.number)
        if voice_edited:
            _queue_change(merge, match, "voice_id", edited.voice_id, edited.number)


def _apply_hand_edits(
    merge: _HandEditMerge, extracted: ExtractedDocument, chapters: list[Chapter]
) -> None:
    """Apply the queued fields, refusing empty chapters or broken coverage.

    A neighbour edge moved only to follow an edit becomes the new generated
    baseline, so it is not reported as a user edit.
    """
    for item in chapters:
        for field_name, value in merge.field_changes.get(item.id, {}).items():
            setattr(item, field_name, value)
        if item.end_block <= item.start_block:
            affected = sorted(merge.changed_chapter_numbers)
            if len(affected) == 2:
                message = (
                    f"Edited boundary between chapters {affected[0]} and {affected[1]} "
                    "cannot be aligned; approve or revert the named chapter(s)."
                )
                raise ExtractionError(message)
            raise _hand_edit_conflict("Edited chapter would be empty", set(affected))

    try:
        validate_chapter_coverage(extracted.blocks, chapters)
    except ExtractionError:
        raise _hand_edit_conflict(
            "Edited boundaries conflict",
            merge.changed_chapter_numbers,
        ) from None

    for item in chapters:
        fields = merge.moved_neighbor_fields.get(item.id, set()) - (
            merge.explicit_boundary_fields.get(item.id, set())
        )
        if "start_block" in fields:
            item.generated_start_block = item.start_block
        if "end_block" in fields:
            item.generated_end_block = item.end_block
        if fields:
            item.generated_fingerprint = generated_baseline_fingerprint(item)


def _merge_hand_edits(
    run: _AnalysisRun,
    extracted: ExtractedDocument,
    chapters: list[Chapter],
    warnings: list[str],
) -> None:
    """Carry hand-edited chapter fields from the old manifest onto new chapters."""
    existing_manifest = run.existing_manifest
    if not run.hand_edited_chapters or existing_manifest is None:
        return
    new_positions = {block.id: index for index, block in enumerate(extracted.blocks)}
    old_chapters = sorted(existing_manifest.chapters, key=lambda item: item.start_block)
    edited_by_id = {chapter.id: chapter for chapter in run.hand_edited_chapters}
    matches = _match_old_chapters(
        old_chapters, chapters, existing_manifest, new_positions, edited_by_id
    )
    merge = _HandEditMerge(
        existing_manifest=existing_manifest,
        new_positions=new_positions,
        new_block_count=len(extracted.blocks),
        old_chapters=old_chapters,
        edited_by_id=edited_by_id,
        matches=matches,
        changed_chapter_numbers={chapter.number for chapter in run.hand_edited_chapters},
    )
    _queue_hand_edits(merge)
    _apply_hand_edits(merge, extracted, chapters)
    preserved_numbers = sorted(matches[chapter.id].number for chapter in run.hand_edited_chapters)
    warnings.append(
        "Preserved user-edited chapter numbers: "
        + ", ".join(str(number) for number in preserved_numbers)
    )


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
    render_chapter_texts(manifest, run.folder, settings.pdf.footnotes, commit_manifest=True)
    write_json(
        run.folder / "reports" / "analysis_fingerprints.json",
        {"schema_version": 1, "stages": run.stage_fingerprints},
    )
    manifest_warnings = len(extracted.warnings + state.warnings)
    if manifest_warnings:
        log_event(
            "review_warning", level=logging.WARNING, stage="analysis", count=manifest_warnings
        )
    log_event("stage_completed", level=logging.INFO, stage="analysis", count=len(chapters))
    return run.manifest_path


def _analyze_book_locked(
    source: Path,
    settings: Settings,
    *,
    extractor: DocumentExtractor | None = None,
    progress: ProgressReporter | None = None,
) -> Path:
    """Run every analysis step in order; the caller holds the workspace lock.

    Steps: start (hash and fingerprints), reuse of an existing analysis,
    extraction, deterministic cleanup, LLM proposals, chapter proposal, the
    hand-edit merge, chapter review, then the manifest and reports.
    """
    run = _start_analysis(source, settings, extractor, progress)
    if _reuse_existing_analysis(run):
        return run.manifest_path
    extracted = _extract(run)
    state = _deterministic_cleanup(run, extracted)
    _llm_proposals(run, extracted, state)
    chapter_proposal = propose_chapters(
        extracted.blocks,
        state.omitted,
        extracted.toc,
        run.settings.chapters,
        extra_heading_ids=state.llm_ids,
    )
    chapters, chapter_warnings = chapter_proposal
    state.review_reasons.update(getattr(chapter_proposal, "review_reasons", set()))
    _merge_hand_edits(run, extracted, chapters, state.warnings)
    _chapter_review(run, extracted, chapters, state, chapter_warnings)
    return _write_analysis(run, extracted, chapters, state)


def prepare_chapter_selection(
    manifest_path: Path,
    manifest: BookManifest,
    settings: Settings,
    *,
    chapter: int | None = None,
    chapter_range: tuple[int, int] | None = None,
    acknowledge: tuple[str, ...] = (),
    persist: bool = False,
    footnotes: str | None = None,
) -> ChapterSelection:
    """Apply chapter review gates while preserving the pipeline selector hook."""
    return _prepare_chapter_selection(
        manifest_path,
        manifest,
        settings,
        chapter=chapter,
        chapter_range=chapter_range,
        acknowledge=acknowledge,
        persist=persist,
        footnotes=footnotes,
        selector=select_chapters,
    )


# Bump when spoken text changes for unchanged chapter text (alignment, dashes,
# invisible characters, pronunciation punctuation) so chapter MP3s regenerate.
# Chunk WAV keys carry the spoken chunk text itself and need no bump.
CHAPTER_AUDIO_FINGERPRINT_NORMALIZATION_VERSION = "narration-normalization-v3"


def chapter_audio_fingerprint(
    text: str,
    settings: Settings,
    manifest: BookManifest,
    chapter: Chapter,
    adapters: tuple[str, ...] = (),
    *,
    cover_image: tuple[bytes, str] | None = None,
    cover_identity: str | None = None,
) -> str:
    """Key the final MP3 by audible content, encoding, and its ID3 metadata.

    adapters names injected TTS/encoder replacements so their output never
    shares an identity with the default Kitten/FFmpeg artifacts.
    """
    model = _tts_model_identity(settings)
    _provider_name, voice, speed = tts_selection(settings, chapter)
    if cover_identity is None:
        if cover_image is None and settings.audio.cover_image is not None:
            cover_image = read_cover_image(settings.audio.cover_image)
        cover_identity = digest_bytes(cover_image[0]) if cover_image is not None else None
    return fingerprint(
        text,
        settings.tts.provider,
        model,
        voice,
        speed,
        settings.tts.pause_ms,
        settings.tts.pronunciations,
        settings.tts.bitrate,
        settings.tts.sample_rate,
        cover_identity,
        CHAPTER_AUDIO_FINGERPRINT_NORMALIZATION_VERSION,
        manifest.title,
        manifest.author,
        chapter.title,
        chapter.number,
        "mp3-v7",
        *adapters,
        # Present only when on, so every existing identity is unchanged.
        *(("citations-skipped-v2",) if settings.reading.process_citations else ()),
    )


def convert_book(
    source: Path,
    settings: Settings,
    chapter: int | None = None,
    chapter_range: tuple[int, int] | None = None,
    *,
    force: bool = False,
    accept_review: tuple[str, ...] = (),
    extractor: DocumentExtractor | None = None,
    tts_provider: TTSProvider | None = None,
    encoder: AudioEncoder | None = None,
    progress: ProgressReporter | None = None,
) -> list[Path]:
    log_event("stage_started", level=logging.INFO, stage="conversion")
    manifest_path = None
    # Injected analysis adapters need not know about progress; pass it only when shown.
    analysis_extra: dict[str, Any] = {} if progress is None else {"progress": progress}
    if source.is_file():
        folder = _analysis_workspace_folder(source, settings)
    else:
        # Invalid inputs cannot write an analysis workspace; retain this path for
        # injected analysis adapters used by offline callers and tests.
        manifest_path = analyze_book(source, settings, extractor=extractor, **analysis_extra)
        folder = manifest_path.parent
    bind_workspace(progress if progress is not None else current_reporter(), folder)
    with workspace_lock(folder, create=True):
        cover_image = read_cover_image(settings.audio.cover_image)
        cover_identity = digest_bytes(cover_image[0]) if cover_image is not None else None
        if manifest_path is None:
            manifest_path = analyze_book(source, settings, extractor=extractor, **analysis_extra)
        return _convert_analyzed_book(
            manifest_path,
            settings,
            cover_image,
            cover_identity,
            chapter=chapter,
            chapter_range=chapter_range,
            force=force,
            accept_review=accept_review,
            tts_provider=tts_provider,
            encoder=encoder,
            progress=progress if progress is not None else current_reporter(),
        )


def _convert_analyzed_book(
    manifest_path: Path,
    settings: Settings,
    cover_image: tuple[bytes, str] | None,
    cover_identity: str | None,
    *,
    chapter: int | None,
    chapter_range: tuple[int, int] | None,
    force: bool,
    accept_review: tuple[str, ...],
    tts_provider: TTSProvider | None,
    encoder: AudioEncoder | None,
    progress: ProgressReporter | None = None,
) -> list[Path]:
    services = ConversionServices(
        log_event=log_event,
        read_manifest=read_manifest,
        prepare_chapter_selection=prepare_chapter_selection,
        render_chapter_texts=render_chapter_texts,
        create_tts_provider=create_tts_provider,
        synthesize_chunks=synthesize_chunks,
        encode_mp3=encode_mp3,
        chapter_audio_fingerprint=chapter_audio_fingerprint,
        audio_output_path=audio_output_path,
        read_synthesis_progress=read_synthesis_progress,
        valid_mp3_sidecar=valid_mp3_sidecar,
        tts_selection=tts_selection,
        voice_marker_ids=voice_marker_ids,
        unspeakable_pause_ranges=unspeakable_pause_ranges,
        _tts_model_identity=_tts_model_identity,
        _progress_report_fields=_progress_report_fields,
    )
    return _run_conversion(
        manifest_path,
        settings,
        cover_image,
        cover_identity,
        chapter=chapter,
        chapter_range=chapter_range,
        force=force,
        accept_review=accept_review,
        tts_provider=tts_provider,
        encoder=encoder,
        services=services,
        progress=progress,
    )
