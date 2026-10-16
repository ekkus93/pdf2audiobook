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
from pdf2audiobook.errors import AudioError
from pdf2audiobook.llm import create_provider, detect_llm_headings
from pdf2audiobook.models import BookManifest
from pdf2audiobook.pdf import extract_pdf
from pdf2audiobook.tts import KittenProvider
from pdf2audiobook.workspace import (
    digest_file,
    fingerprint,
    read_manifest,
    write_json,
    write_manifest,
)


def analyze_book(source: Path, settings: Settings) -> Path:
    from pdf2audiobook.errors import InputError

    if not source.is_file():
        raise InputError(f"PDF not found: {source}")
    book_hash = digest_file(source)
    root = Path(settings.general.output_dir).expanduser()
    folder = root / f"{source.stem}-{book_hash[:10]}"
    manifest_path = folder / "manifest.json"
    chosen_provider = getattr(settings.llm, settings.llm.provider.replace("-", "_"))
    analysis_key = fingerprint(
        book_hash, settings.pdf.model_dump(), settings.chapters.model_dump(),
        settings.llm.model_dump(exclude={"openai", "ollama", "llama_server"}),
        chosen_provider.model, chosen_provider.base_url, "analysis-v2"
    )
    if manifest_path.is_file() and settings.general.resume:
        existing = read_manifest(manifest_path)
        if (existing.input_sha256 == book_hash
                and existing.analysis_fingerprint == analysis_key
                and all(
                    (folder / "chapters" / f"{part.number:03d}.txt").is_file()
                    for part in existing.chapters
                )):
            render_chapter_texts(existing, folder)
            return manifest_path

    extracted = extract_pdf(source, settings.pdf)
    edits = pagination_cleanup(extracted.blocks, extracted.page_sizes, settings.pdf)
    omitted = {edit.block_id for edit in edits if edit.accepted and not edit.replacement}

    llm_ids: set[str] = set()
    warnings: list[str] = []
    if settings.llm.enabled and settings.llm.structure:
        # A provider cannot introduce new prose or unanchored chapter starts.
        with create_provider(settings) as provider:
            llm_ids, warnings = detect_llm_headings(
                [block for block in extracted.blocks if block.id not in omitted],
                provider,
            )
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

def convert_book(source: Path, settings: Settings, chapter: int | None = None) -> list[Path]:
    manifest_path = analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    render_chapter_texts(manifest, manifest_path.parent)
    chosen = [
        item for item in manifest.chapters if chapter is None or item.number == chapter
    ]
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
    # Audio identities include all audible and encoding settings, not merely the PDF hash.
    pending = []
    outputs = []
    for item in chosen:
        output = audio_output_path(manifest, item, manifest_path.parent)
        outputs.append(output)
        text_file = manifest_path.parent / "chapters" / f"{item.number:03d}.txt"
        text = text_file.read_text(encoding="utf-8")
        identity = fingerprint(
            text, settings.tts.kitten.model, settings.tts.kitten.voice,
            settings.tts.kitten.speed, settings.tts.pause_ms,
            settings.tts.bitrate, settings.tts.sample_rate, "mp3-v2"
        )
        record = output.with_suffix(".cache.json")
        cached = False
        if (settings.general.resume and output.is_file()
                and output.stat().st_size > 0 and record.is_file()):
            try:
                import json

                from mutagen.mp3 import MP3

                metadata = json.loads(record.read_text(encoding="utf-8"))
                cached = (
                    metadata.get("fingerprint") == identity
                    and metadata.get("bytes") == output.stat().st_size
                    and metadata.get("sha256") == digest_file(output)
                    and MP3(output).info.length > 0
                )
            except (OSError, ValueError):
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
            use_cache=settings.cache.enabled and settings.general.resume,
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
