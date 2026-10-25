"""FX9 changed derived text, so analysis and chapter audio identities must differ (spec §9.9)."""

from pdf2audiobook.config import Settings
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.pipeline import (
    CHAPTER_AUDIO_NARRATION_VERSION,
    _analysis_stage_fingerprints,
    chapter_audio_fingerprint,
)


def test_chapter_audio_identity_carries_the_fx9_narration_version():
    assert CHAPTER_AUDIO_NARRATION_VERSION == "narration-normalization-v2"
    manifest = BookManifest(
        schema_version=3, input_sha256="x", title="Book", source_path="book.pdf"
    )
    chapter = Chapter(id="c1", number=1, title="One", start_block=0, end_block=1, confidence=1)
    first = chapter_audio_fingerprint("A sentence.", Settings(), manifest, chapter)
    assert first == chapter_audio_fingerprint("A sentence.", Settings(), manifest, chapter)


def test_extraction_fingerprint_is_the_fx9_generation():
    stages = _analysis_stage_fingerprints("a" * 64, Settings(), None)
    from pdf2audiobook.workspace import fingerprint

    assert stages["extraction"] == fingerprint(
        "analysis-v21", "a" * 64, Settings().pdf.model_dump()
    )
