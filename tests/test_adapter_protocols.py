"""Public adapter protocols: PDF extractor, TTS provider and chapter encoder are swappable."""

import numpy as np
import pymupdf
import pytest

import pdf2audiobook.pipeline as pipeline
from pdf2audiobook.audio import AudioEncoder, encode_mp3
from pdf2audiobook.config import LLM, General, Pdf, Settings
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.pdf import DocumentExtractor, PyMuPDFExtractor, extract_pdf
from pdf2audiobook.pipeline import analyze_book, chapter_audio_fingerprint, convert_book
from pdf2audiobook.tts import TTSProvider


class RecordingExtractor:
    name = "recording"

    def __init__(self) -> None:
        self.calls = 0

    def inspect(self, source, password_env=None):
        return {}

    def extract(self, source, settings, *, ocr_cache_dir=None, source_sha256=None):
        self.calls += 1
        return extract_pdf(
            source, settings, ocr_cache_dir=ocr_cache_dir, source_sha256=source_sha256
        )


class ToneProvider:
    sample_rate = 16000
    max_chars_per_chunk = 350

    def __init__(self) -> None:
        self.generated = 0

    def list_models(self):
        return ["tone"]

    def list_voices(self):
        return ["tone"]

    def health(self):
        return True

    def generate(self, text, *, voice, speed):
        self.generated += 1
        return np.full(1600, 0.02, dtype=np.float32)


class RecordingEncoder:
    def __init__(self) -> None:
        self.tracks: list[tuple[int, str]] = []

    def __call__(self, samples, sample_rate, output, *, track, title, **_):
        self.tracks.append((track, title))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"encoded")
        return output


def _book(tmp_path):
    source = tmp_path / "book.pdf"
    doc = pymupdf.open()
    for number in (1, 2):
        page = doc.new_page()
        page.insert_text((70, 70), f"Chapter {number}", fontsize=20)
        page.insert_text((70, 110), f"Synthetic chapter number {number} text.", fontsize=11)
    doc.save(source)
    doc.close()
    return source


def _settings(tmp_path):
    return Settings(
        general=General(output_dir=str(tmp_path / "out")),
        pdf=Pdf(ocr="never"),
        llm=LLM(enabled=False),
    )


def test_default_and_test_adapters_satisfy_public_protocols():
    assert isinstance(PyMuPDFExtractor(), DocumentExtractor)
    assert isinstance(RecordingExtractor(), DocumentExtractor)
    assert isinstance(ToneProvider(), TTSProvider)
    assert isinstance(encode_mp3, AudioEncoder)
    assert isinstance(RecordingEncoder(), AudioEncoder)


def test_default_extractor_matches_function_api(tmp_path):
    source = _book(tmp_path)
    settings = Pdf(ocr="never")
    direct = extract_pdf(source, settings)
    adapted = PyMuPDFExtractor().extract(source, settings)
    assert [b.text for b in adapted.blocks] == [b.text for b in direct.blocks]


def test_injected_adapters_replace_kitten_and_ffmpeg(tmp_path, monkeypatch):
    def no_kitten(*_args, **_kwargs):
        raise AssertionError("default TTS engine must not load")

    monkeypatch.setattr(pipeline, "KittenProvider", no_kitten)
    monkeypatch.setattr(pipeline, "encode_mp3", no_kitten)
    source = _book(tmp_path)
    extractor, tts, encoder = RecordingExtractor(), ToneProvider(), RecordingEncoder()
    files = convert_book(
        source, _settings(tmp_path), extractor=extractor, tts_provider=tts, encoder=encoder
    )
    assert extractor.calls == 1
    assert tts.generated >= 2
    assert encoder.tracks == [(1, "Chapter 1"), (2, "Chapter 2")]
    assert [path.read_bytes() for path in files] == [b"encoded", b"encoded"]


def test_injected_extractor_never_reuses_default_analysis(tmp_path):
    source = _book(tmp_path)
    settings = _settings(tmp_path)
    analyze_book(source, settings)
    extractor = RecordingExtractor()
    analyze_book(source, settings, extractor=extractor)
    assert extractor.calls == 1


@pytest.mark.parametrize("adapters", [("tts=x.Tone",), ("encoder=x.Wav",)])
def test_injected_audio_adapters_change_chapter_identity(adapters):
    settings = Settings()
    manifest = BookManifest(
        schema_version=2, input_sha256="0" * 64, title="Book", source_path="book.pdf"
    )
    chapter = Chapter(id="c1", number=1, title="One", start_block=0, end_block=1, confidence=1.0)
    default = chapter_audio_fingerprint("Read.", settings, manifest, chapter)
    assert chapter_audio_fingerprint("Read.", settings, manifest, chapter, ()) == default
    assert chapter_audio_fingerprint("Read.", settings, manifest, chapter, adapters) != default
