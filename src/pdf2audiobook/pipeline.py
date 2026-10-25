"""Inspectably staged PDF analysis and resumable audio generation."""

from __future__ import annotations

import tempfile
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path

from pdf2audiobook.audio import (
    AudioEncoder,
    audio_output_path,
    encode_mp3,
    has_speakable_narration,
    read_cover_image,
    synthesize_chunks,
    voice_marker_ids,
)
from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import (
    footnote_anchor_edits,
    pagination_cleanup,
    place_footnotes,
    propose_chapters,
    render_chapter_texts,
    validate_chapter_coverage,
)
from pdf2audiobook.errors import AudioError, LLMError, PartialConversionError
from pdf2audiobook.jsonio import load_bounded_json
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
from pdf2audiobook.models import BookManifest, Chapter, CleanupEdit, generated_chapter_fingerprint
from pdf2audiobook.pdf import DocumentExtractor, extract_pdf
from pdf2audiobook.tts import KITTEN_MODEL_ALIASES, KittenProvider, PiperProvider, TTSProvider
from pdf2audiobook.workspace import (
    digest_bytes,
    digest_file,
    fingerprint,
    read_manifest,
    write_json,
    write_manifest,
)


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


@lru_cache(maxsize=128)
def _model_file_digest(path: str, size: int, mtime_ns: int) -> str:
    """Memoize local model hashes while still invalidating changed file metadata."""
    del size, mtime_ns
    return digest_file(Path(path))


def _tts_model_identity(settings: Settings) -> str:
    """Return content/version identity for the active TTS model without loading it."""
    if settings.tts.provider == "piper":
        configured = settings.tts.piper.model_path
        if not configured:
            return fingerprint("piper-model-v1", "missing")
        model_path = Path(configured).expanduser().resolve()
        digests = []
        for path in (model_path, Path(f"{model_path}.json")):
            try:
                stat = path.stat()
                digest = _model_file_digest(str(path), stat.st_size, stat.st_mtime_ns)
            except OSError:
                digest = "missing"
            digests.append((path.suffix, digest))
        return fingerprint("piper-model-v1", str(model_path), digests)
    model = settings.tts.kitten.model
    resolved_model = KITTEN_MODEL_ALIASES.get(model, model)
    try:
        engine_version = package_version("kittenml")
    except PackageNotFoundError:
        engine_version = "not-installed"
    return fingerprint("kitten-model-v1", resolved_model, engine_version)


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
    selected = getattr(settings.llm, settings.llm.provider.replace("-", "_"))
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
    chapter_settings = settings.chapters.model_dump(exclude={"allow_single_chapter"})
    return {
        "extraction": fingerprint(
            "analysis-v19",
            book_hash,
            settings.pdf.model_dump(),
            *(() if extractor is None else ("extractor", extractor.name)),
        ),
        "chapter-boundaries": fingerprint(chapter_settings),
        "llm-analysis": fingerprint(
            llm_settings,
            settings.llm.provider,
            selected.model,
            selected.base_url,
        ),
    }


def _changed_analysis_stages(folder: Path, current: dict[str, str]) -> list[str]:
    """Return changed stage names without loading or displaying their inputs."""
    previous = load_bounded_json(
        folder / "reports" / "analysis_fingerprints.json", max_bytes=4096, max_depth=8
    )
    prior_stages = previous.get("stages") if isinstance(previous, dict) else None
    if not isinstance(prior_stages, dict):
        return ["analysis"]
    changed = sorted(
        name
        for name, value in current.items()
        if not isinstance(prior_stages.get(name), str) or prior_stages[name] != value
    )
    return changed or ["analysis"]


def valid_mp3_sidecar(audio_path: Path) -> dict[str, object] | None:
    """Return a verified owned sidecar; foreign or stale files are never trusted."""
    record = audio_path.with_suffix(".cache.json")
    data = load_bounded_json(record, max_bytes=4096, max_depth=8)
    if not isinstance(data, dict):
        return None
    try:
        valid = (
            isinstance(data.get("chapter_id"), str)
            and isinstance(data.get("fingerprint"), str)
            and isinstance(data.get("bytes"), int)
            and not isinstance(data.get("bytes"), bool)
            and data["bytes"] == audio_path.stat().st_size
            and isinstance(data.get("sha256"), str)
            and data["sha256"] == digest_file(audio_path)
        )
    except OSError:
        return None
    return data if valid else None


def settings_for_book_tts(
    settings: Settings, book_stem: str, *, explicit: frozenset[str] = frozenset()
) -> Settings:
    """Apply a named TTS profile unless a command-line option overrides it."""
    profile = settings.tts.profiles.get(book_stem)
    if profile is None:
        return settings
    selected = settings.model_copy(deep=True)
    if "tts_provider" not in explicit and profile.provider is not None:
        selected.tts.provider = profile.provider
    if "tts_model" not in explicit:
        if profile.kitten_model is not None:
            selected.tts.kitten.model = profile.kitten_model
        if profile.piper_model_path is not None:
            selected.tts.piper.model_path = profile.piper_model_path
    if "voice" not in explicit and profile.voice is not None:
        if selected.tts.provider == "piper":
            selected.tts.piper.voice = profile.voice
        else:
            selected.tts.kitten.voice = profile.voice
    if "speed" not in explicit and profile.speed is not None:
        if selected.tts.provider == "piper":
            selected.tts.piper.speed = profile.speed
        else:
            selected.tts.kitten.speed = profile.speed
    return selected


def chapter_voice(settings: Settings, chapter: Chapter) -> str:
    """Resolve an explicit per-chapter voice before the configured default."""
    if chapter.voice_id is not None:
        return chapter.voice_id
    return (
        settings.tts.piper.voice if settings.tts.provider == "piper" else settings.tts.kitten.voice
    )


def analyze_book(
    source: Path, settings: Settings, *, extractor: DocumentExtractor | None = None
) -> Path:
    from pdf2audiobook.errors import InputError

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
    manifest_path = folder / "manifest.json"
    stage_fingerprints = _analysis_stage_fingerprints(book_hash, settings, extractor)
    analysis_key = fingerprint(stage_fingerprints)
    hand_edited_chapters: list[Chapter] = []
    existing_manifest: BookManifest | None = None
    if manifest_path.is_file():
        existing = read_manifest(manifest_path)
        existing_manifest = existing
        hand_edited_chapters = [
            chapter
            for chapter in existing.chapters
            if chapter.generated_fingerprint is not None
            and chapter.generated_fingerprint != generated_chapter_fingerprint(chapter)
        ]
        same_input = existing.input_sha256 == book_hash
        same_analysis = existing.analysis_fingerprint == analysis_key
        approved_content = (
            existing.approved
            or any(ch.manually_approved for ch in existing.chapters)
            or any(edit.accepted and edit.provider != "deterministic" for edit in existing.edits)
        )
        if same_input and same_analysis and settings.general.resume:
            # Regenerate missing or stale derived texts without replacing user edits.
            render_chapter_texts(existing, folder, settings.pdf.footnotes)
            return manifest_path
        if approved_content:
            from pdf2audiobook.errors import ExtractionError

            changed_stages = _changed_analysis_stages(folder, stage_fingerprints)
            raise ExtractionError(
                "This workspace contains manually approved or protected chapter/cleanup edits. "
                "Changed analysis stage(s): "
                + ", ".join(changed_stages)
                + ". Use a new --output directory for changed analysis."
            )

    ocr_cache_dir = (folder / ".cache" / "ocr") if settings.cache.enabled else None
    if extractor is None:
        extracted = extract_pdf(
            source, settings.pdf, ocr_cache_dir=ocr_cache_dir, source_sha256=book_hash
        )
    else:
        extracted = extractor.extract(
            source, settings.pdf, ocr_cache_dir=ocr_cache_dir, source_sha256=book_hash
        )
    pagination_warnings: list[str] = []
    edits = pagination_cleanup(
        extracted.blocks,
        extracted.page_sizes,
        settings.pdf,
        page_labels=getattr(extracted, "page_labels", None),
        warnings=pagination_warnings,
    )
    # Only explicitly selected omit mode can remove a high-confidence note.
    # Source spans/blocks remain intact and every exclusion is audited.
    footnotes = [block for block in extracted.blocks if block.kind == "footnote"]
    if settings.pdf.footnotes == "omit":
        edits.extend(
            CleanupEdit(
                block_id=block.id,
                original=block.text,
                replacement="",
                reason="explicit footnotes=omit policy (conservative classification)",
                confidence=0.9,
                accepted=True,
            )
            for block in footnotes
        )
    if footnotes and settings.pdf.footnotes in {"inline", "end", "omit"}:
        # Once notes are handled, their anchor digits ("world.5") would only
        # be read aloud as numbers. Removal is per anchor, audited, reversible.
        edits.extend(
            footnote_anchor_edits(
                extracted.blocks, {edit.block_id for edit in edits if edit.accepted}
            )
        )
    omitted = {edit.block_id for edit in edits if edit.accepted and not edit.replacement}

    llm_ids: set[str] = set()
    llm_decisions: list[LLMDecision] = []
    warnings: list[str] = pagination_warnings
    if footnotes and settings.pdf.footnotes == "omit":
        warnings.append(
            f"Excluded {len(footnotes)} conservatively classified footnote "
            "block(s) under explicit omit policy; inspect audited cleanup edits"
        )
    original_warning_count = len(warnings)
    try:
        if settings.llm.enabled and (
            settings.llm.structure
            or settings.llm.contents
            or settings.llm.cleanup
            or settings.llm.classification
            or settings.llm.narration
            or settings.llm.vision
        ):
            # Only anchored proposals are accepted. OCR cleanup requires manual approval.
            source_blocks = [block for block in extracted.blocks if block.id not in omitted]
            with create_provider(settings) as provider:
                worker = CachedLLMProvider(
                    provider,
                    cache_dir=folder / ".cache" / "llm",
                    identity=_llm_cache_identity(settings),
                    enabled=settings.cache.enabled and settings.general.resume,
                    max_requests=settings.llm.max_requests,
                    max_reported_tokens=settings.llm.max_reported_tokens,
                    max_estimated_cost_usd=settings.llm.max_estimated_cost_usd,
                    input_cost_usd_per_million_tokens=(
                        settings.llm.input_cost_usd_per_million_tokens
                    ),
                    output_cost_usd_per_million_tokens=(
                        settings.llm.output_cost_usd_per_million_tokens
                    ),
                    usage_report=folder / "reports" / "llm_usage.json",
                    ledger_path=folder / "reports" / "llm_budget.sqlite3",
                )
                if settings.llm.vision:
                    from pdf2audiobook.llm.vision import review_visual_pages

                    visual_review = review_visual_pages(source, worker)
                    write_json(folder / "reports" / "vision_review.json", visual_review)
                    if visual_review["pages"] or visual_review["warnings"]:
                        warnings.append(
                            "Vision review suggestions are untrusted; inspect vision_review.json"
                        )
                if settings.llm.structure:
                    llm_ids, heading_warnings = detect_llm_headings(
                        source_blocks,
                        worker,
                        chunk_tokens=settings.llm.chunk_tokens,
                        decisions=llm_decisions,
                    )
                    # Keep deterministic footnote-policy warnings in the audit.
                    # Replacing the list also corrupts the fallback warning prefix.
                    warnings.extend(heading_warnings)
                if settings.llm.contents:
                    content_heading_ids, content_warnings = propose_llm_contents_boundaries(
                        source_blocks,
                        worker,
                        chunk_tokens=settings.llm.chunk_tokens,
                        decisions=llm_decisions,
                    )
                    llm_ids.update(content_heading_ids)
                    warnings.extend(content_warnings)
                if settings.llm.cleanup:
                    suggestions, edit_warnings = propose_llm_cleanup(
                        source_blocks,
                        worker,
                        decisions=llm_decisions,
                        chunk_tokens=settings.llm.chunk_tokens,
                    )
                    edits.extend(suggestions)
                    warnings.extend(edit_warnings)
                if settings.llm.classification:
                    classified, class_warnings = propose_llm_classification(
                        source_blocks,
                        worker,
                        chunk_tokens=settings.llm.chunk_tokens,
                        decisions=llm_decisions,
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
                        decisions=llm_decisions,
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
    except LLMError:
        if not settings.llm.fallback_to_deterministic:
            raise
        # Fail closed to deterministic analysis: no partial model proposals,
        # rejected decisions or uncertain chapter boundaries may be retained.
        llm_ids.clear()
        edits = [edit for edit in edits if edit.provider != "llm"]
        llm_decisions.clear()
        warnings = warnings[:original_warning_count] + [
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
    for decision in llm_decisions:
        decision.provider = settings.llm.provider
    write_json(
        folder / "reports" / "llm_cleanup_audit.json",
        {
            "schema_version": 2,
            "requires_manual_review": True,
            "decisions": [item.model_dump() for item in llm_decisions if item.task == "cleanup"],
        },
    )
    write_json(
        folder / "reports" / "llm_decisions.json",
        {
            "schema_version": 1,
            "requires_manual_review": True,
            "decisions": [item.model_dump() for item in llm_decisions],
        },
    )
    chapters, chapter_warnings = propose_chapters(
        extracted.blocks,
        omitted,
        extracted.toc,
        settings.chapters,
        extra_heading_ids=llm_ids,
    )
    for chapter in chapters:
        has_speakable_source = any(
            block.id not in omitted and has_speakable_narration(block.text)
            for block in extracted.blocks[chapter.start_block : chapter.end_block]
        )
        if not has_speakable_source:
            chapter.warnings.append("No speakable text after accepted cleanup; review manually")
            warnings.append(
                f"Chapter {chapter.number} has no speakable text after cleanup; "
                "review before synthesis"
            )
    if hand_edited_chapters and existing_manifest is not None:
        new_positions = {block.id: index for index, block in enumerate(extracted.blocks)}
        preserved_numbers = []
        for edited in hand_edited_chapters:
            if edited.start_block >= len(existing_manifest.blocks):
                raise ExtractionError(
                    f"Chapter {edited.number} was edited but cannot be aligned after reanalysis"
                )
            start_id = existing_manifest.blocks[edited.start_block].id
            end_id = (
                existing_manifest.blocks[edited.end_block].id
                if edited.end_block < len(existing_manifest.blocks)
                else None
            )
            new_start = new_positions.get(start_id)
            new_end = new_positions.get(end_id) if end_id is not None else len(extracted.blocks)
            match = next(
                (
                    chapter
                    for chapter in chapters
                    if chapter.start_block == new_start and chapter.end_block == new_end
                ),
                next((chapter for chapter in chapters if chapter.number == edited.number), None),
            )
            if match is None or new_start is None or new_end is None:
                raise ExtractionError(
                    f"Chapter {edited.number} was edited but cannot be aligned after reanalysis"
                )
            match.start_block = new_start
            match.end_block = new_end
            match.title = edited.title
            match.voice_id = edited.voice_id
            match.generated_fingerprint = edited.generated_fingerprint
            match.warnings = list(edited.warnings)
            preserved_numbers.append(edited.number)
        validate_chapter_coverage(extracted.blocks, chapters)
        warnings.append(
            "Preserved user-edited chapter numbers: "
            + ", ".join(str(number) for number in sorted(preserved_numbers))
        )
    warnings.extend(chapter_warnings)
    if footnotes and settings.pdf.footnotes in {"inline", "end"}:
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
    manifest = BookManifest(
        schema_version=2,
        input_sha256=book_hash,
        title=extracted.title,
        author=extracted.author,
        source_path=str(source.resolve()),
        spans=extracted.spans,
        blocks=extracted.blocks,
        edits=edits,
        chapters=chapters,
        analysis_fingerprint=analysis_key,
        warnings=extracted.warnings + warnings,
    )
    render_chapter_texts(manifest, folder, settings.pdf.footnotes)
    write_manifest(manifest_path, manifest)
    write_json(
        folder / "reports" / "analysis_fingerprints.json",
        {"schema_version": 1, "stages": stage_fingerprints},
    )
    return manifest_path


def select_chapters(
    manifest: BookManifest,
    settings: Settings,
    *,
    chapter: int | None = None,
    chapter_range: tuple[int, int] | None = None,
) -> list:
    """Validate chosen chapters before loading or downloading a speech model."""
    if chapter is not None and chapter_range is not None:
        raise AudioError("--chapter and --chapter-range cannot be combined")
    count = len(manifest.chapters)
    if chapter_range is not None:
        first, last = chapter_range
        if first < 1 or last < first or last > count:
            raise AudioError(
                f"Chapter range {first}:{last} is outside the book's 1:{count} chapters"
            )
        chosen = [c for c in manifest.chapters if first <= c.number <= last]
    elif chapter is not None:
        chosen = [c for c in manifest.chapters if c.number == chapter]
    else:
        chosen = list(manifest.chapters)
    if not chosen:
        raise AudioError(f"Chapter {chapter} does not exist")
    for item in chosen:
        if (
            "No speakable text after accepted cleanup; review manually" in item.warnings
            and not item.manually_approved
        ):
            raise AudioError(
                f"Chapter {item.number} has no speakable text; review and approve it before synthesis"
            )
        if (
            any(
                warning == "source PDF was damaged and repaired; verify page coverage"
                or (
                    warning.startswith("Page ")
                    and "could not be loaded; verify coverage" in warning
                )
                for warning in manifest.warnings
            )
            and not item.manually_approved
        ):
            raise AudioError(
                f"Chapter {item.number} comes from a damaged source; "
                "review and approve it before synthesis"
            )
        if item.confidence < settings.chapters.min_boundary_confidence and not (
            item.manually_approved or settings.chapters.allow_single_chapter
        ):
            raise AudioError(
                f"Chapter {item.number} has low boundary confidence; "
                "review the manifest before synthesis"
            )
    return chosen


def chapter_audio_fingerprint(
    text: str,
    settings: Settings,
    manifest: BookManifest,
    chapter: Chapter,
    adapters: tuple[str, ...] = (),
) -> str:
    """Key the final MP3 by audible content, encoding, and its ID3 metadata.

    adapters names injected TTS/encoder replacements so their output never
    shares an identity with the default Kitten/FFmpeg artifacts.
    """
    model = _tts_model_identity(settings)
    voice = chapter_voice(settings, chapter)
    speed = (
        settings.tts.piper.speed if settings.tts.provider == "piper" else settings.tts.kitten.speed
    )
    cover = read_cover_image(settings.audio.cover_image)
    cover_identity = digest_bytes(cover[0]) if cover is not None else None
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
        "narration-normalization-v1",
        manifest.title,
        manifest.author,
        chapter.title,
        chapter.number,
        "mp3-v5",
        *adapters,
    )


def convert_book(
    source: Path,
    settings: Settings,
    chapter: int | None = None,
    chapter_range: tuple[int, int] | None = None,
    *,
    force: bool = False,
    extractor: DocumentExtractor | None = None,
    tts_provider: TTSProvider | None = None,
    encoder: AudioEncoder | None = None,
) -> list[Path]:
    cover_image = read_cover_image(settings.audio.cover_image)
    manifest_path = analyze_book(source, settings, extractor=extractor)
    adapters = tuple(
        f"{role}={type(adapter).__module__}.{type(adapter).__qualname__}"
        for role, adapter in (("tts", tts_provider), ("encoder", encoder))
        if adapter is not None
    )
    manifest = read_manifest(manifest_path)
    render_chapter_texts(manifest, manifest_path.parent, settings.pdf.footnotes)
    chosen = select_chapters(manifest, settings, chapter=chapter, chapter_range=chapter_range)
    preflight_failed: dict[int, int] = {}
    approved_marker_chapters: dict[int, list[str]] = {}
    for item in chosen:
        text_file = manifest_path.parent / "chapters" / f"{item.number:03d}.txt"
        try:
            marker_ids = voice_marker_ids(text_file.read_text(encoding="utf-8"))
        except (AudioError, OSError, UnicodeError):
            raise AudioError("Cannot read approved chapter text; check workspace files") from None
        if marker_ids and not item.manually_approved:
            preflight_failed[item.number] = AudioError.exit_code
        elif marker_ids:
            approved_marker_chapters[item.number] = marker_ids
    provider = tts_provider
    all_marker_ids = {marker for markers in approved_marker_chapters.values() for marker in markers}
    if all_marker_ids:
        try:
            if provider is None:
                provider = (
                    PiperProvider(settings.tts.piper.model_path)
                    if settings.tts.provider == "piper"
                    else KittenProvider(settings.tts.kitten.model)
                )
            available_voices = provider.list_voices()
        except Exception:
            available_voices = []
        if available_voices:
            for item in chosen:
                marker_ids = approved_marker_chapters.get(item.number, [])
                if any(marker not in available_voices for marker in marker_ids):
                    preflight_failed[item.number] = AudioError.exit_code
    # Audio identities include all audible and encoding settings, not merely the PDF hash.
    pending = []
    outputs = []
    failed_chapters = set(preflight_failed)
    conversion_status = {
        item.id: {
            "number": item.number,
            "status": "failed" if item.number in preflight_failed else "pending",
            **({"error_code": AudioError.exit_code} if item.number in preflight_failed else {}),
        }
        for item in chosen
    }
    for item in chosen:
        output = audio_output_path(manifest, item, manifest_path.parent)
        outputs.append(output)
        if item.number in preflight_failed:
            continue
        text_file = manifest_path.parent / "chapters" / f"{item.number:03d}.txt"
        try:
            text = text_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            # PDF-derived filenames and source text must not escape in errors.
            raise AudioError("Cannot read approved chapter text; check workspace files") from None
        identity = chapter_audio_fingerprint(text, settings, manifest, item, adapters)
        record = output.with_suffix(".cache.json")
        cached = False
        if settings.general.resume and not force:
            # A file can disappear or become unreadable between is_file()
            # and stat(). Treat this as a cache miss, not a book-path error.
            try:
                cache_files_ready = (
                    output.is_file() and output.stat().st_size > 0 and record.is_file()
                )
            except OSError:
                cache_files_ready = False
        else:
            cache_files_ready = False
        if cache_files_ready:
            try:
                from mutagen import MutagenError
                from mutagen.easyid3 import EasyID3
                from mutagen.mp3 import MP3

                # A cache sidecar is tiny (three scalar fields). Never parse
                # an unbounded or non-object JSON document from disk.
                metadata = load_bounded_json(record, max_bytes=4096, max_depth=8)
                cached = (
                    isinstance(metadata, dict)
                    and metadata.get("fingerprint") == identity
                    and metadata.get("chapter_id", item.id) == item.id
                    and metadata.get("bytes") == output.stat().st_size
                    and metadata.get("sha256") == digest_file(output)
                )
                if cached:
                    mp3 = MP3(output, ID3=EasyID3)
                    tags = mp3.tags
                    # The sidecar is not sufficient evidence of correct chapter
                    # identity: verify the actual audio tags before reusing it.
                    cached = (
                        mp3.info is not None
                        and mp3.info.length > 0
                        and tags is not None
                        and tags.get("title") == [item.title]
                        and tags.get("album") == [manifest.title]
                        and tags.get("tracknumber") == [str(item.number)]
                        and (not manifest.author or tags.get("artist") == [manifest.author])
                    )
            except (OSError, ValueError, MutagenError):
                # A corrupt MP3, even with a matching cache sidecar checksum,
                # must be regenerated rather than aborting the entire book.
                cached = False
        if not cached:
            # Retain the path and identity, not the full text of every chapter.
            # A long book may have hundreds of pending chapters.
            pending.append((item, output, text_file, record, identity))
        else:
            conversion_status[item.id]["status"] = "complete"
        del text

    encode = encode_mp3 if encoder is None else encoder
    for item, output, text_file, record, identity in pending:
        try:
            text = text_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise AudioError("Cannot read approved chapter text; check workspace files") from None
        # Detect edits between the cache-check and synthesis passes. Never
        # publish audio with a fingerprint computed from different prose.
        if chapter_audio_fingerprint(text, settings, manifest, item, adapters) != identity:
            raise AudioError("Approved chapter text changed during conversion; retry")
        if provider is None:
            try:
                if settings.tts.provider == "piper":
                    provider = PiperProvider(settings.tts.piper.model_path)
                else:
                    provider = KittenProvider(settings.tts.kitten.model)
            except AudioError:
                failed_chapters.add(item.number)
                conversion_status[item.id] = {
                    "number": item.number,
                    "status": "failed",
                    "error_code": AudioError.exit_code,
                }
                continue
        selected_model = _tts_model_identity(settings)
        selected_voice = chapter_voice(settings, item)
        selected_speed = (
            settings.tts.piper.speed
            if settings.tts.provider == "piper"
            else settings.tts.kitten.speed
        )
        streamed_wav: Path | None = None
        try:
            synth_kwargs = {}
            if encoder is None:
                try:
                    manifest_path.parent.joinpath(".cache", "tts", "chapters").mkdir(
                        parents=True, exist_ok=True
                    )
                    with tempfile.NamedTemporaryFile(
                        prefix="chapter-",
                        suffix=".wav",
                        dir=manifest_path.parent / ".cache" / "tts" / "chapters",
                        delete=False,
                    ) as temp_wav:
                        streamed_wav = Path(temp_wav.name)
                except OSError:
                    raise AudioError("Could not create temporary chapter audio") from None
                synth_kwargs["output_wav"] = streamed_wav
            samples = synthesize_chunks(
                text,
                provider,
                # Chunk cache keys include the model; qualify it for injected engines.
                model=":".join((selected_model, *(a for a in adapters if a.startswith("tts=")))),
                voice=selected_voice,
                speed=selected_speed,
                pause_ms=settings.tts.pause_ms,
                pronunciations=settings.tts.pronunciations,
                max_retries=settings.tts.max_retries,
                cache=manifest_path.parent / ".cache" / "tts",
                use_cache=settings.cache.enabled and settings.general.resume and not force,
                progress_file=(
                    manifest_path.parent
                    / ".cache"
                    / "tts"
                    / "progress"
                    / f"{fingerprint(item.id, item.number)[:32]}.json"
                ),
                **synth_kwargs,
            )
            encode_kwargs = {
                "bitrate": settings.tts.bitrate,
                "target_rate": settings.tts.sample_rate,
                "title": item.title,
                "artist": manifest.author,
                "album": manifest.title,
                "track": item.number,
            }
            if cover_image is not None:
                encode_kwargs["cover_image"] = cover_image
            try:
                encode(samples, provider.sample_rate, output, **encode_kwargs)
            finally:
                if streamed_wav is not None:
                    streamed_wav.unlink(missing_ok=True)
        except AudioError:
            if streamed_wav is not None:
                streamed_wav.unlink(missing_ok=True)
            failed_chapters.add(item.number)
            conversion_status[item.id] = {
                "number": item.number,
                "status": "failed",
                "error_code": AudioError.exit_code,
            }
            continue
        write_json(
            record,
            {
                "chapter_id": item.id,
                "fingerprint": identity,
                "sha256": digest_file(output),
                "bytes": output.stat().st_size,
            },
        )
        conversion_status[item.id]["status"] = "complete"
        for previous in output.parent.glob("*.mp3"):
            if previous == output:
                continue
            metadata = valid_mp3_sidecar(previous)
            if metadata is None or metadata.get("chapter_id") != item.id:
                continue
            try:
                previous.unlink()
                previous.with_suffix(".cache.json").unlink(missing_ok=True)
            except OSError:
                raise AudioError(
                    f"Chapter {item.number} was published but old chapter audio could not be removed"
                ) from None
    write_json(
        manifest_path.parent / "reports" / "conversion_status.json",
        {
            "schema_version": 1,
            "chapters": sorted(conversion_status.values(), key=lambda value: int(value["number"])),
        },
    )
    if failed_chapters:
        numbers = ", ".join(str(number) for number in sorted(failed_chapters))
        raise PartialConversionError(f"Chapter audio failed for chapter(s): {numbers}")
    return outputs
