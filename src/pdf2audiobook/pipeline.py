"""Inspectably staged PDF analysis and resumable audio generation."""
from __future__ import annotations

from pathlib import Path

from pdf2audiobook.audio import audio_output_path, encode_mp3, synthesize_chunks
from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import (
    pagination_cleanup,
    propose_chapters,
    render_chapter_texts,
)
from pdf2audiobook.errors import AudioError, LLMError
from pdf2audiobook.llm import (
    CleanupDecision,
    create_provider,
    detect_llm_headings,
    propose_llm_classification,
    propose_llm_cleanup,
    propose_llm_narration,
)
from pdf2audiobook.llm.cache import CachedLLMProvider
from pdf2audiobook.models import BookManifest, Chapter, CleanupEdit
from pdf2audiobook.pdf import extract_pdf
from pdf2audiobook.tts import KittenProvider
from pdf2audiobook.workspace import (
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
        "llm-provider-v2", settings.llm.provider,
        selected.model, selected.base_url,
        settings.llm.temperature, settings.llm.max_context_tokens,
        settings.llm.chunk_tokens, settings.llm.max_output_tokens,
    )


def analyze_book(source: Path, settings: Settings) -> Path:
    from pdf2audiobook.errors import InputError

    # These exceptions can include private book names and absolute paths.
    # Avoid rendering user-supplied source identifiers in public diagnostics.
    try:
        if not source.is_file():
            raise InputError("PDF not found; check the input path and permissions")
        book_hash = digest_file(source)
    except OSError:
        raise InputError("Cannot access PDF; check the input path and permissions") from None
    root = Path(settings.general.output_dir).expanduser()
    folder = root / f"{source.stem}-{book_hash[:10]}"
    manifest_path = folder / "manifest.json"
    chosen_provider = getattr(settings.llm, settings.llm.provider.replace("-", "_"))
    analysis_key = fingerprint(
        book_hash, settings.pdf.model_dump(), settings.chapters.model_dump(),
        settings.llm.model_dump(exclude={"openai", "ollama", "llama_server"}),
        chosen_provider.model, chosen_provider.base_url, "analysis-v8"
    )
    if manifest_path.is_file():
        existing = read_manifest(manifest_path)
        same_input = existing.input_sha256 == book_hash
        same_analysis = existing.analysis_fingerprint == analysis_key
        approved_content = (
            existing.approved
            or any(ch.manually_approved for ch in existing.chapters)
            or any(
                edit.accepted and edit.provider != "deterministic"
                for edit in existing.edits
            )
        )
        if same_input and same_analysis and settings.general.resume:
            # Regenerate missing or stale derived texts without replacing user edits.
            render_chapter_texts(existing, folder)
            return manifest_path
        if approved_content:
            from pdf2audiobook.errors import ExtractionError

            raise ExtractionError(
                "This workspace contains manually approved chapter or cleanup edits. "
                "A reanalysis would overwrite those decisions. Back up the manifest "
                "and use a new --output directory for a fresh analysis."
            )

    extracted = extract_pdf(
        source, settings.pdf,
        ocr_cache_dir=(folder / ".cache" / "ocr") if settings.cache.enabled else None,
        source_sha256=book_hash,
    )
    edits = pagination_cleanup(extracted.blocks, extracted.page_sizes, settings.pdf)
    # Only explicitly selected omit mode can remove a high-confidence note.
    # Source spans/blocks remain intact and every exclusion is audited.
    footnotes = [block for block in extracted.blocks if block.kind == "footnote"]
    if settings.pdf.footnotes == "omit":
        edits.extend(
            CleanupEdit(
                block_id=block.id, original=block.text, replacement="",
                reason="explicit footnotes=omit policy (conservative classification)",
                confidence=0.9, accepted=True,
            )
            for block in footnotes
        )
    omitted = {edit.block_id for edit in edits if edit.accepted and not edit.replacement}

    llm_ids: set[str] = set()
    llm_decisions: list[CleanupDecision] = []
    warnings: list[str] = []
    if footnotes and settings.pdf.footnotes == "omit":
        warnings.append(
            f"Excluded {len(footnotes)} conservatively classified footnote "
            "block(s) under explicit omit policy; inspect audited cleanup edits"
        )
    elif footnotes and settings.pdf.footnotes == "inline":
        warnings.append(
            "Footnotes retained at their PDF reading positions; "
            "anchor relocation is not yet supported"
        )
    original_warning_count = len(warnings)
    try:
        if settings.llm.enabled and (
            settings.llm.structure or settings.llm.cleanup
            or settings.llm.classification or settings.llm.narration
        ):
            # Only anchored proposals are accepted. OCR cleanup requires manual approval.
            source_blocks = [
                block for block in extracted.blocks if block.id not in omitted
            ]
            with create_provider(settings) as provider:
                worker = CachedLLMProvider(
                    provider, cache_dir=folder / ".cache" / "llm",
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
                if settings.llm.structure:
                    llm_ids, heading_warnings = detect_llm_headings(
                        source_blocks, worker, chunk_tokens=settings.llm.chunk_tokens,
                    )
                    # Keep deterministic footnote-policy warnings in the audit.
                    # Replacing the list also corrupts the fallback warning prefix.
                    warnings.extend(heading_warnings)
                if settings.llm.cleanup:
                    suggestions, edit_warnings = propose_llm_cleanup(
                        source_blocks, worker, decisions=llm_decisions,
                        chunk_tokens=settings.llm.chunk_tokens,
                    )
                    edits.extend(suggestions)
                    warnings.extend(edit_warnings)
                if settings.llm.classification:
                    classified, class_warnings = propose_llm_classification(
                        source_blocks, worker, chunk_tokens=settings.llm.chunk_tokens,
                    )
                    warnings.extend(class_warnings)
                    write_json(folder / "reports" / "classification_suggestions.json", {
                        "schema_version": 1,
                        "requires_manual_review": True,
                        "labels": [item.model_dump() for item in classified],
                    })
                if settings.llm.narration:
                    spoken_suggestions, spoken_warnings = propose_llm_narration(
                        source_blocks, worker, chunk_tokens=settings.llm.chunk_tokens,
                    )
                    warnings.extend(spoken_warnings)
                    # Deliberately separate from approved CleanupEdits and chapter
                    # texts. This report is advisory and never changes audio.
                    write_json(folder / "reports" / "narration_suggestions.json", {
                        "schema_version": 1,
                        "requires_manual_review": True,
                        "suggestions": [
                            item.model_dump() for item in spoken_suggestions
                        ],
                    })
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
        write_json(folder / "reports" / "classification_suggestions.json", {
            "schema_version": 1, "requires_manual_review": True, "labels": [],
        })
        write_json(folder / "reports" / "narration_suggestions.json", {
            "schema_version": 1, "requires_manual_review": True, "suggestions": [],
        })
    write_json(folder / "reports" / "llm_cleanup_audit.json", {
        "schema_version": 1,
        "requires_manual_review": True,
        "decisions": [item.model_dump() for item in llm_decisions],
    })
    chapters, chapter_warnings = propose_chapters(
        extracted.blocks, omitted, extracted.toc, settings.chapters,
        extra_heading_ids=llm_ids,
    )
    warnings.extend(chapter_warnings)
    if settings.llm.enabled and not settings.llm.structure:
        warnings.append("LLM structure analysis disabled in settings")
    manifest = BookManifest(
        input_sha256=book_hash, title=extracted.title, author=extracted.author,
        source_path=str(source.resolve()), spans=extracted.spans,
        blocks=extracted.blocks, edits=edits, chapters=chapters,
        analysis_fingerprint=analysis_key,
        warnings=extracted.warnings + warnings,
    )
    render_chapter_texts(manifest, folder)
    write_manifest(manifest_path, manifest)
    return manifest_path

def select_chapters(
    manifest: BookManifest, settings: Settings,
    *, chapter: int | None = None, chapter_range: tuple[int, int] | None = None,
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
        if item.confidence < settings.chapters.min_boundary_confidence and not (
            item.manually_approved or settings.chapters.allow_single_chapter
        ):
            raise AudioError(
                f"Chapter {item.number} has low boundary confidence; "
                "review the manifest before synthesis"
            )
    return chosen



def chapter_audio_fingerprint(
    text: str, settings: Settings, manifest: BookManifest, chapter: Chapter,
) -> str:
    """Key the final MP3 by audible content, encoding, and its ID3 metadata."""
    return fingerprint(
        text, settings.tts.provider, settings.tts.kitten.model,
        settings.tts.kitten.voice, settings.tts.kitten.speed,
        settings.tts.pause_ms, settings.tts.bitrate, settings.tts.sample_rate,
        manifest.title, manifest.author, chapter.title, chapter.number, "mp3-v4",
    )


def convert_book(
    source: Path, settings: Settings, chapter: int | None = None,
    chapter_range: tuple[int, int] | None = None, *, force: bool = False,
) -> list[Path]:
    manifest_path = analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    render_chapter_texts(manifest, manifest_path.parent)
    chosen = select_chapters(manifest, settings, chapter=chapter, chapter_range=chapter_range)
    # Audio identities include all audible and encoding settings, not merely the PDF hash.
    pending = []
    outputs = []
    for item in chosen:
        output = audio_output_path(manifest, item, manifest_path.parent)
        outputs.append(output)
        text_file = manifest_path.parent / "chapters" / f"{item.number:03d}.txt"
        try:
            text = text_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            # PDF-derived filenames and source text must not escape in errors.
            raise AudioError("Cannot read approved chapter text; check workspace files") from None
        identity = chapter_audio_fingerprint(text, settings, manifest, item)
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
                import json

                from mutagen import MutagenError
                from mutagen.easyid3 import EasyID3
                from mutagen.mp3 import MP3

                # A cache sidecar is tiny (three scalar fields). Never parse
                # an unbounded or non-object JSON document from disk.
                with record.open("rb") as sidecar:
                    raw_metadata = sidecar.read(4097)
                metadata = json.loads(raw_metadata) if len(raw_metadata) <= 4096 else None
                cached = (
                    isinstance(metadata, dict)
                    and metadata.get("fingerprint") == identity
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
            pending.append((item, output, text, record, identity))

    provider = KittenProvider(settings.tts.kitten.model) if pending else None
    for item, output, text, record, identity in pending:
        assert provider is not None
        samples = synthesize_chunks(
            text, provider, model=settings.tts.kitten.model,
            voice=settings.tts.kitten.voice, speed=settings.tts.kitten.speed,
            pause_ms=settings.tts.pause_ms,
            cache=manifest_path.parent / ".cache" / "tts",
            use_cache=settings.cache.enabled and settings.general.resume and not force,
            progress_file=(
                manifest_path.parent / ".cache" / "tts" / "progress"
                / f"{fingerprint(item.id, item.number)[:32]}.json"
            ),
        )
        encode_mp3(
            samples, provider.sample_rate, output,
            bitrate=settings.tts.bitrate, target_rate=settings.tts.sample_rate,
            title=item.title, artist=manifest.author, album=manifest.title,
            track=item.number,
        )
        write_json(record, {
            "fingerprint": identity,
            "sha256": digest_file(output),
            "bytes": output.stat().st_size,
        })
    return outputs
