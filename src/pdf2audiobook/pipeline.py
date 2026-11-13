"""Inspectably staged PDF analysis and resumable audio generation."""

from __future__ import annotations

import logging
import os as os
from pathlib import Path
from typing import Any

from pdf2audiobook.analysis import AnalysisServices, _analyze_book_locked
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
    chapter_has_speakable_text as chapter_has_speakable_text,
)
from pdf2audiobook.document.structure import (
    footnote_anchor_edits as footnote_anchor_edits,
)
from pdf2audiobook.document.structure import (
    footnote_omit_edits as footnote_omit_edits,
)
from pdf2audiobook.document.structure import (
    pagination_cleanup,
    propose_chapters,
    render_chapter_texts,
)
from pdf2audiobook.document.structure import (
    place_footnotes as place_footnotes,
)
from pdf2audiobook.document.structure import (
    validate_chapter_coverage as validate_chapter_coverage,
)
from pdf2audiobook.errors import (
    ExtractionError,
    InputError,
    LLMError,
    WorkspaceLockedError,
)
from pdf2audiobook.llm import (
    LLMDecision as LLMDecision,
)
from pdf2audiobook.llm import (
    create_provider,
    detect_llm_headings,
    propose_llm_cleanup,
)
from pdf2audiobook.llm import (
    propose_llm_classification as propose_llm_classification,
)
from pdf2audiobook.llm import (
    propose_llm_contents_boundaries as propose_llm_contents_boundaries,
)
from pdf2audiobook.llm import (
    propose_llm_narration as propose_llm_narration,
)
from pdf2audiobook.llm.cache import CachedLLMProvider
from pdf2audiobook.llm.equations import (
    propose_llm_equation_readings as propose_llm_equation_readings,
)
from pdf2audiobook.logging import log_event
from pdf2audiobook.models import (
    BookManifest,
    Chapter,
)

# Re-exported for callers of this facade; the analysis code now lives in `analysis`.
from pdf2audiobook.models import (
    CleanupEdit as CleanupEdit,
)
from pdf2audiobook.models import (
    DocumentBlock as DocumentBlock,
)
from pdf2audiobook.models import (
    generated_baseline_fingerprint as generated_baseline_fingerprint,
)
from pdf2audiobook.models import (
    generated_chapter_fingerprint as generated_chapter_fingerprint,
)
from pdf2audiobook.pdf import DocumentExtractor, extract_pdf
from pdf2audiobook.pdf import (
    ExtractedDocument as ExtractedDocument,
)
from pdf2audiobook.progress_display import (
    ProgressHandle as ProgressHandle,
)
from pdf2audiobook.progress_display import (
    ProgressReporter,
    bind_workspace,
    current_reporter,
)
from pdf2audiobook.review_reasons import (
    REVIEW_REASON_CODES as REVIEW_REASON_CODES,
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
            "analysis-v24",
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


def _analysis_services() -> AnalysisServices:
    """The analysis dependencies, read from this module now so test patches apply."""
    return AnalysisServices(
        CachedLLMProvider=CachedLLMProvider,
        _analysis_stage_fingerprints=_analysis_stage_fingerprints,
        _llm_cache_identity=_llm_cache_identity,
        _resolve_auto_llm_model=_resolve_auto_llm_model,
        create_provider=create_provider,
        detect_llm_headings=detect_llm_headings,
        digest_file=digest_file,
        extract_pdf=extract_pdf,
        log_event=log_event,
        pagination_cleanup=pagination_cleanup,
        propose_chapters=propose_chapters,
        propose_llm_cleanup=propose_llm_cleanup,
        read_manifest=read_manifest,
        render_chapter_texts=render_chapter_texts,
        write_json=write_json,
    )


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
            return _analyze_book_locked(
                source,
                settings,
                extractor=extractor,
                progress=reporter,
                services=_analysis_services(),
            )
    except WorkspaceLockedError as exc:
        if str(exc) == "Could not lock the book workspace":
            raise ExtractionError("Could not create or update the output workspace") from None
        raise ExtractionError("Another conversion is already running for this book") from None


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
