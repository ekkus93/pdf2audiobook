"""Citation processing is part of audio identity only when it is on (C2)."""

import json
import shutil
from pathlib import Path

import fitz
import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook import pipeline
from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.pipeline import chapter_audio_fingerprint, convert_book

# Computed from the code as it was before citation processing existed (commit 8e3c204),
# with the TTS model identity pinned: the real identity embeds the installed kittenml
# version, so an unpinned golden would only match the machine that produced it.
GOLDEN_OFF = "1bf26140f8157af69176f93d867e274b6848252bab1d1ab1e1754fa831d757df"
GOLDEN_OFF_WITH_ADAPTER = "658a77ffd939d5158c8dab03897924a2c625c31adbe8213c13bb2de3b71cb823"
TEXT = "Attention is useful [13]. It also scales [35, 2, 5].\n"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")


def _manifest() -> BookManifest:
    return BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        author="Author",
        source_path="s",
        blocks=[DocumentBlock(id="b", page_index=0, text="Body")],
        chapters=[Chapter(id="c", number=1, title="One", start_block=0, end_block=1, confidence=1)],
    )


@pytest.fixture
def pinned_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "_tts_model_identity", lambda _settings: "pinned-model-identity")


def _fingerprint(settings: Settings, adapters: tuple[str, ...] = ()) -> str:
    manifest = _manifest()
    return chapter_audio_fingerprint(
        TEXT, settings, manifest, manifest.chapters[0], adapters, cover_identity="none"
    )


@pytest.mark.usefixtures("pinned_model")
def test_with_the_setting_off_the_fingerprint_is_byte_identical_to_before() -> None:
    assert _fingerprint(Settings()) == GOLDEN_OFF
    assert _fingerprint(Settings(), ("tts=x.Y",)) == GOLDEN_OFF_WITH_ADAPTER


@pytest.mark.usefixtures("pinned_model")
def test_turning_it_on_changes_the_fingerprint_and_is_stable() -> None:
    on = Settings()
    on.reading.process_citations = True
    assert _fingerprint(on) != GOLDEN_OFF
    assert _fingerprint(on) == _fingerprint(on)


@pytest.mark.usefixtures("pinned_model")
def test_the_equation_setting_does_not_touch_audio_identity() -> None:
    settings = Settings()
    settings.reading.process_equations = True
    assert _fingerprint(settings) == GOLDEN_OFF


class Provider:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def __init__(self) -> None:
        self.texts: list[str] = []

    def list_voices(self) -> list[str]:
        return ["Jasper"]

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        self.texts.append(text)
        return np.ones(2400, dtype=np.float32) * 0.1


def _book(tmp_path: Path) -> tuple[Path, Settings]:
    source = tmp_path / "book.pdf"
    document = fitz.open()
    for number in (1, 2):
        page = document.new_page()
        page.insert_text((72, 72), f"Chapter {number}", fontsize=24)
        page.insert_text((72, 120), f"Spoken words for part {number} are useful [13].", fontsize=11)
    document.save(source)
    document.close()
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    return source, settings


def _sidecars(tmp_path: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((tmp_path / "out").rglob("*.cache.json"))]


@needs_ffmpeg
def test_sidecars_record_the_citation_setting_only_when_it_is_on(tmp_path: Path) -> None:
    source, settings = _book(tmp_path)
    convert_book(source, settings, tts_provider=Provider())
    assert {tuple(s["rendering_inputs"]) for s in _sidecars(tmp_path)} == {("footnotes",)}
    assert all(s["rendering_inputs"] == {"footnotes": "warn"} for s in _sidecars(tmp_path))
    settings.reading.process_citations = True
    convert_book(source, settings, tts_provider=Provider())
    assert all(
        s["rendering_inputs"] == {"footnotes": "warn", "citations": True}
        for s in _sidecars(tmp_path)
    )


@needs_ffmpeg
def test_toggling_regenerates_audio_only_and_matching_audio_is_reused(tmp_path: Path) -> None:
    source, settings = _book(tmp_path)
    off = Provider()
    outputs = convert_book(source, settings, tts_provider=off)
    folder = outputs[0].parent.parent
    chapters = {p.name: p.read_bytes() for p in (folder / "chapters").glob("*.txt")}
    manifest = (folder / "manifest.json").read_bytes()
    assert any("[13]" in text for text in off.texts)

    settings.reading.process_citations = True
    on = Provider()
    convert_book(source, settings, tts_provider=on)
    assert on.texts and not any("[" in text or "13" in text for text in on.texts)

    stamps = {p.name: p.stat().st_mtime_ns for p in (folder / "audio").glob("*.mp3")}
    again = Provider()
    convert_book(source, settings, tts_provider=again)
    assert again.texts == []  # matching audio is reused, untouched
    assert {p.name: p.stat().st_mtime_ns for p in (folder / "audio").glob("*.mp3")} == stamps

    settings.reading.process_citations = False
    convert_book(source, settings, tts_provider=Provider())
    # Regenerated for the other setting (chunk WAVs from the first run are cached, so the
    # provider is not needed again), and recorded as such.
    assert all(s["rendering_inputs"] == {"footnotes": "warn"} for s in _sidecars(tmp_path))
    assert {p.name: p.stat().st_mtime_ns for p in (folder / "audio").glob("*.mp3")} != stamps

    assert {p.name: p.read_bytes() for p in (folder / "chapters").glob("*.txt")} == chapters
    assert (folder / "manifest.json").read_bytes() == manifest


@needs_ffmpeg
def test_pack_m4b_does_not_call_differing_citation_audio_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, settings = _book(tmp_path)
    settings.reading.process_citations = True
    convert_book(source, settings, tts_provider=Provider())
    manifest = next((tmp_path / "out").glob("*/manifest.json"))
    monkeypatch.setattr("pdf2audiobook.audio.encode_m4b", lambda *_a, **_k: tmp_path / "b.m4b")
    result = CliRunner().invoke(
        app, ["pack-m4b", str(manifest), "--output", str(tmp_path / "b.m4b"), "--no-config"]
    )
    assert result.exit_code == 0, result.stderr
