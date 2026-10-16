"""Inspectably staged PDF analysis and resumable audio generation."""
from __future__ import annotations

from pathlib import Path

from pdf2audiobook.audio import audio_output_path, encode_mp3, synthesize_chunks
from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import chapter_text, pagination_cleanup, propose_chapters
from pdf2audiobook.errors import AudioError
from pdf2audiobook.models import BookManifest
from pdf2audiobook.pdf import extract_pdf
from pdf2audiobook.tts import KittenProvider
from pdf2audiobook.workspace import atomic_write, digest_bytes, read_manifest, write_manifest


def analyze_book(source: Path, settings: Settings) -> Path:
    # Remote content is never transmitted by the deterministic PDF pipeline.
    extracted = extract_pdf(source, settings.pdf)
    edits = pagination_cleanup(extracted.blocks, extracted.page_sizes, settings.pdf)
    omitted = {edit.block_id for edit in edits if edit.accepted and not edit.replacement}
    chapters, warnings = propose_chapters(extracted.blocks, omitted, extracted.toc, settings.chapters)
    book_hash = digest_bytes(source.read_bytes())
    root = Path(settings.general.output_dir).expanduser()
    folder = root / f"{source.stem}-{book_hash[:10]}"
    manifest_path = folder / "manifest.json"
    if manifest_path.is_file() and settings.general.resume:
        existing = read_manifest(manifest_path)
        if existing.input_sha256 == book_hash:
            return manifest_path
    manifest = BookManifest(
        input_sha256=book_hash, title=extracted.title, author=extracted.author,
        source_path=str(source.resolve()), spans=extracted.spans,
        blocks=extracted.blocks, edits=edits, chapters=chapters,
        warnings=extracted.warnings + warnings
        + (["LLM analysis not yet implemented; deterministic chapter heuristics used"]
           if settings.llm.enabled else []),
    )
    write_manifest(manifest_path, manifest)
    for chapter in chapters:
        atomic_write(
            folder / "chapters" / f"{chapter.number:03d}.txt",
            chapter_text(extracted.blocks, chapter, omitted).encode("utf-8"),
        )
    return manifest_path


def convert_book(source: Path, settings: Settings, chapter: int | None = None) -> list[Path]:
    manifest_path = analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
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
    # Do not load the model if all requested valid outputs already exist.
    pending = []
    for item in chosen:
        output = audio_output_path(manifest, item, manifest_path.parent)
        if output.is_file() and settings.general.resume and output.stat().st_size > 0:
            continue
        pending.append(item)
    provider = KittenProvider(settings.tts.kitten.model) if pending else None
    for item in pending:
        assert provider is not None
        text_file = manifest_path.parent / "chapters" / f"{item.number:03d}.txt"
        text = text_file.read_text(encoding="utf-8")
        samples = synthesize_chunks(
            text, provider, model=settings.tts.kitten.model,
            voice=settings.tts.kitten.voice, speed=settings.tts.kitten.speed,
            pause_ms=settings.tts.pause_ms,
            cache=manifest_path.parent / ".cache" / "tts",
            use_cache=settings.cache.enabled and settings.general.resume,
        )
        encode_mp3(
            samples, provider.sample_rate,
            audio_output_path(manifest, item, manifest_path.parent),
            bitrate=settings.tts.bitrate, target_rate=settings.tts.sample_rate,
            title=item.title, artist=manifest.author,
            album=manifest.title, track=item.number,
        )
    return [audio_output_path(manifest, item, manifest_path.parent) for item in chosen]
