"""FX9 changed derived text, so analysis and chapter audio identities must differ (spec §9.9)."""

import pdf2audiobook.pipeline as pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.pipeline import (
    CHAPTER_AUDIO_FINGERPRINT_NORMALIZATION_VERSION,
    _analysis_stage_fingerprints,
    chapter_audio_fingerprint,
)


def test_chapter_audio_identity_carries_the_fx9_narration_version():
    assert CHAPTER_AUDIO_FINGERPRINT_NORMALIZATION_VERSION == "narration-normalization-v3"
    manifest = BookManifest(
        schema_version=3, input_sha256="x", title="Book", source_path="book.pdf"
    )
    chapter = Chapter(id="c1", number=1, title="One", start_block=0, end_block=1, confidence=1)
    first = chapter_audio_fingerprint("A sentence.", Settings(), manifest, chapter)
    assert first == chapter_audio_fingerprint("A sentence.", Settings(), manifest, chapter)


def test_changing_narration_version_changes_computed_chapter_audio_fingerprint(monkeypatch):
    manifest = BookManifest(
        schema_version=3, input_sha256="x", title="Book", source_path="book.pdf"
    )
    chapter = Chapter(id="c1", number=1, title="One", start_block=0, end_block=1, confidence=1)
    before = chapter_audio_fingerprint("A sentence.", Settings(), manifest, chapter)
    monkeypatch.setattr(
        pipeline,
        "CHAPTER_AUDIO_FINGERPRINT_NORMALIZATION_VERSION",
        "test-different-version",
    )
    after = chapter_audio_fingerprint("A sentence.", Settings(), manifest, chapter)
    assert after != before


def test_extraction_fingerprint_is_the_epub_chapters_generation():
    # Supersedes the FX9 pin (analysis-v22): EPUB chapter detection changed the stored
    # warnings and review reasons, so older extraction results are not reused.
    stages = _analysis_stage_fingerprints("a" * 64, Settings(), None)
    from pdf2audiobook.workspace import fingerprint

    assert stages["extraction"] == fingerprint(
        "analysis-v23", "a" * 64, Settings().pdf.model_dump()
    )
    assert stages["chapter-boundaries"] == fingerprint(
        "chapter-detection-v4",
        Settings().chapters.model_dump(exclude={"allow_single_chapter", "min_boundary_confidence"}),
    )
