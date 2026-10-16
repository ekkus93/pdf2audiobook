"""Inspectably staged PDF analysis and future audio conversion."""
from __future__ import annotations

from pathlib import Path

from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import (
    chapter_text,
    pagination_cleanup,
    propose_chapters,
)
from pdf2audiobook.errors import AudioError
from pdf2audiobook.models import BookManifest
from pdf2audiobook.pdf import extract_pdf
from pdf2audiobook.workspace import digest_bytes, read_manifest, write_manifest, atomic_write


def analyze_book(source: Path, settings: Settings) -> Path:
    # Do not transmit PDF content to any remote service: LLM integration is not wired yet.
    extracted = extract_pdf(source, settings.pdf)
    edits = pagination_cleanup(extracted.blocks, extracted.page_sizes, settings.pdf)
    omitted = {edit.block_id for edit in edits if edit.accepted and not edit.replacement}
    chapters, warnings = propose_chapters(
        extracted.blocks, omitted, extracted.toc, settings.chapters
    )
    book_hash = digest_bytes(source.read_bytes())
    output_root = Path(settings.general.output_dir).expanduser()
    # Stable per-book workspace avoids mixing identically named PDFs.
    folder = output_root / f"{source.stem}-{book_hash[:10]}"
    manifest_path = folder / "manifest.json"
    # Do not overwrite edited user manifests without validation or warning.
    if manifest_path.is_file() and settings.general.resume:
        existing = read_manifest(manifest_path)
        if existing.input_sha256 == book_hash:
            return manifest_path
    manifest = BookManifest(
        input_sha256=book_hash,
        title=extracted.title,
        author=extracted.author,
        source_path=str(source.resolve()),
        spans=extracted.spans,
        blocks=extracted.blocks,
        edits=edits,
        chapters=chapters,
        warnings=extracted.warnings + warnings
        + (["LLM analysis is not yet implemented; deterministic chapter heuristics used"]
           if settings.llm.enabled else []),
    )
    write_manifest(manifest_path, manifest)
    for chapter in chapters:
        name = f"{chapter.number:03d}.txt"
        atomic_write(
            folder / "chapters" / name,
            chapter_text(extracted.blocks, chapter, omitted).encode("utf-8"),
        )
    return manifest_path


def convert_book(source: Path, settings: Settings, chapter: int | None = None) -> list[Path]:
    analyze_book(source, settings)
    raise AudioError(
        "Analysis produced chapter text, but Kitten TTS and MP3 creation "
        "are not implemented yet (phase M4)"
    )
