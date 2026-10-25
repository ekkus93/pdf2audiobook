"""Final MP3 cache keys must reflect audible settings and ID3 metadata."""

from pdf2audiobook.config import Settings
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.pipeline import chapter_audio_fingerprint


def _fixture():
    settings = Settings()
    manifest = BookManifest(
        schema_version=2,
        input_sha256="a" * 64,
        title="Book",
        author="Author",
        source_path="book.pdf",
    )
    chapter = Chapter(
        id="chapter-1",
        number=1,
        title="First",
        start_block=0,
        end_block=1,
        confidence=1.0,
    )
    return settings, manifest, chapter


def test_mp3_identity_changes_with_audible_and_encoding_settings():
    settings, manifest, chapter = _fixture()
    baseline = chapter_audio_fingerprint("Read this.", settings, manifest, chapter)
    assert baseline == chapter_audio_fingerprint("Read this.", settings, manifest, chapter)
    assert baseline != chapter_audio_fingerprint(
        "Read something else.", settings, manifest, chapter
    )
    for field, value in [
        ("pause_ms", 750),
        ("bitrate", "192k"),
        ("sample_rate", 44100),
    ]:
        changed = settings.model_copy(
            update={"tts": settings.tts.model_copy(update={field: value})}
        )
        assert chapter_audio_fingerprint("Read this.", changed, manifest, chapter) != baseline
    for field, value in [
        ("model", "nano"),
        ("voice", "AnotherVoice"),
        ("speed", 1.2),
    ]:
        changed_tts = settings.tts.model_copy(
            update={"kitten": settings.tts.kitten.model_copy(update={field: value})}
        )
        changed = settings.model_copy(update={"tts": changed_tts})
        assert chapter_audio_fingerprint("Read this.", changed, manifest, chapter) != baseline


def test_mp3_identity_changes_when_id3_metadata_changes():
    settings, manifest, chapter = _fixture()
    baseline = chapter_audio_fingerprint("Read this.", settings, manifest, chapter)
    for field, value in [("title", "Renamed Book"), ("author", "Different Author")]:
        changed = manifest.model_copy(update={field: value})
        assert chapter_audio_fingerprint("Read this.", settings, changed, chapter) != baseline
    for field, value in [("title", "Renamed Chapter"), ("number", 2)]:
        changed = chapter.model_copy(update={field: value})
        assert chapter_audio_fingerprint("Read this.", settings, manifest, changed) != baseline


def test_mp3_identity_does_not_change_for_resume_policy_only():
    settings, manifest, chapter = _fixture()
    changed = settings.model_copy(
        update={"general": settings.general.model_copy(update={"resume": False})}
    )
    assert chapter_audio_fingerprint("Read this.", settings, manifest, chapter) == (
        chapter_audio_fingerprint("Read this.", changed, manifest, chapter)
    )
