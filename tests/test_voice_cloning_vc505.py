"""Finished clone audio resumes while its reference remains, and refusals stay clean (VC5.05)."""

import pytest
from test_voice_cloning import recording
from test_voice_cloning_conversion import app, runner
from test_voice_cloning_conversion import cloned_book as cloned_book

from pdf2audiobook.tts import catalog, clone_provider

# Bound before any fixture replaces it, so a refusal test can restore the real check.
REAL_REQUIRE_MODEL = catalog.require_model


@pytest.fixture(autouse=True)
def installed_backend(monkeypatch):
    monkeypatch.setattr("pdf2audiobook.tts.cloning.package_versions", lambda: {"torch": "2.6.0"})


@pytest.fixture
def constructed(monkeypatch):
    """Count providers built, with the fake inference behind them."""
    fake = clone_provider.KittenCloneProvider
    built = []

    class Counting:
        sample_rate = fake.sample_rate
        max_chars_per_chunk = fake.max_chars_per_chunk
        supports_voice_listing = False

        def __init__(self, reference):
            catalog.require_model()
            built.append(reference)
            self.inner = fake(reference)

        def generate(self, narration, *, voice, speed):
            return self.inner.generate(narration, voice=voice, speed=speed)

        def close(self):
            self.inner.close()

    monkeypatch.setattr("pdf2audiobook.tts.clone_provider.KittenCloneProvider", Counting)
    return built


def _remove_optional_backend(monkeypatch):
    monkeypatch.setattr("pdf2audiobook.tts.cloning.package_versions", lambda: {})
    monkeypatch.setattr(
        "pdf2audiobook.tts.catalog.model_readiness",
        lambda *_a, **_k: {"ready": False, "reason": "missing_package"},
    )


def test_a_changed_chapter_needing_synthesis_refuses_without_building_a_provider(
    cloned_book, constructed, monkeypatch
):
    book = cloned_book
    before = len(book["calls"])
    _remove_optional_backend(monkeypatch)
    # The refusal is the real readiness check, so restore it for this test only.
    monkeypatch.setattr("pdf2audiobook.tts.catalog.require_model", REAL_REQUIRE_MODEL)
    result = runner.invoke(app, [*book["args"], "--speed", "1.25"])
    assert result.exit_code != 0
    assert "kittenml" in result.output
    assert len(book["calls"]) == before
    assert constructed == []
    assert "PRIVATE" not in result.output


def _regenerates(book, monkeypatch, *extra: str):
    before = len(book["calls"])
    manifest = book["manifest"].read_bytes()
    result = runner.invoke(app, [*book["args"], *extra])
    assert result.exit_code == 0, result.output
    assert len(book["calls"]) > before
    assert book["manifest"].read_bytes() == manifest
    return len(book["calls"]) - before


def test_same_size_replacement_of_the_reference_audio_regenerates(
    cloned_book, constructed, monkeypatch
):
    book = cloned_book
    recording(book["audio"], frequency=880)  # same path, same length, different content
    assert _regenerates(book, monkeypatch) > 0


def test_a_changed_transcript_regenerates(cloned_book, constructed, monkeypatch):
    book = cloned_book
    book["text"].write_text("Entirely different PRIVATE reference words.", encoding="utf-8")
    assert _regenerates(book, monkeypatch) > 0


def test_an_installed_backend_version_change_regenerates(cloned_book, constructed, monkeypatch):
    book = cloned_book
    monkeypatch.setattr("pdf2audiobook.tts.cloning.package_versions", lambda: {"torch": "9.9.9"})
    assert _regenerates(book, monkeypatch) > 0


def test_a_generation_setting_change_regenerates(cloned_book, constructed, monkeypatch):
    book = cloned_book
    assert _regenerates(book, monkeypatch, "--speed", "1.25") > 0


@pytest.mark.parametrize("extra", [[], ["--json"]])
def test_resume_without_the_backend_emits_no_reference_markers(
    cloned_book, constructed, monkeypatch, extra
):
    book = cloned_book
    monkeypatch.setattr("pdf2audiobook.tts.cloning.package_versions", lambda: {})
    result = runner.invoke(app, [*book["args"], *extra])
    assert result.exit_code == 0, result.output
    for marker in (str(book["audio"]), str(book["text"]), "PRIVATE", "reference words"):
        assert marker not in result.output


def test_sidecars_written_before_the_fix_keep_their_identity(cloned_book, constructed):
    book = cloned_book
    audio = book["manifest"].parent / "audio"
    sidecars = {p.name: p.read_bytes() for p in audio.glob("*.cache.json")}
    stamps = {p.name: p.stat().st_mtime_ns for p in audio.glob("*.mp3")}
    assert sidecars and stamps
    result = runner.invoke(app, book["args"])
    assert result.exit_code == 0, result.output
    assert {p.name: p.read_bytes() for p in audio.glob("*.cache.json")} == sidecars
    assert {p.name: p.stat().st_mtime_ns for p in audio.glob("*.mp3")} == stamps


@pytest.mark.parametrize(
    ("installed", "accepted"),
    [({"torch": "2.6.0"}, True), ({}, True), ({"torch": "9.9.9"}, False)],
)
def test_a_recorded_identity_is_rejected_only_by_a_different_installed_backend(
    monkeypatch, installed, accepted
):
    from pdf2audiobook.tts import cloning

    identity = {
        **cloning.GENERATION,
        "reference_audio_sha256": "a" * 64,
        "reference_text_sha256": "b" * 64,
        "transcription": None,
        "backend_versions": {"torch": "2.6.0"},
    }
    monkeypatch.setattr("pdf2audiobook.tts.cloning.package_versions", lambda: installed)
    assert cloning.valid_recorded_identity(identity) is accepted
