"""Chapter-level speaker assignments override, and invalidate, default voice audio."""

import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.models import Chapter
from pdf2audiobook.pipeline import chapter_audio_fingerprint, chapter_voice


def test_chapter_voice_assignment_overrides_provider_default_and_audio_identity():
    settings = Settings.model_validate({"llm": {"enabled": False}})
    chapter = Chapter(
        id="chapter-1",
        number=1,
        title="Chapter One",
        start_block=0,
        end_block=1,
        confidence=1,
    )
    before = chapter_audio_fingerprint("Source text.", settings, _manifest(), chapter)
    assert chapter_voice(settings, chapter) == "Jasper"

    chapter.voice_id = "Bella"

    assert chapter_voice(settings, chapter) == "Bella"
    assert chapter_audio_fingerprint("Source text.", settings, _manifest(), chapter) != before


def test_chapter_voice_id_is_bounded_and_nonempty():
    with pytest.raises(ValueError, match="voice_id"):
        Chapter(
            id="chapter-1",
            number=1,
            title="Chapter One",
            start_block=0,
            end_block=1,
            confidence=1,
            voice_id="  ",
        )


def _manifest():
    from pdf2audiobook.models import BookManifest

    return BookManifest(
        input_sha256="0" * 64,
        title="Synthetic",
        source_path="synthetic.pdf",
    )
