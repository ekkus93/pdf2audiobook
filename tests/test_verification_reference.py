"""The verification reference is exactly the narration sent to TTS (audio verification AV1.02)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import fitz
import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import load_settings
from pdf2audiobook.verification.reference import Reference, Unavailable, chapter_reference
from pdf2audiobook.workspace import read_manifest

runner = CliRunner()
spoken: list[str] = []


class _RecordingKitten:
    """Stands in for Kitten and records every text it is asked to speak."""

    sample_rate = 24000
    supports_voice_listing = True
    max_chars_per_chunk = 350

    def __init__(self, model: str) -> None:
        self.model = model

    def list_voices(self) -> list[str]:
        return ["Jasper"]

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        spoken.append(text)
        return np.ones(2400, dtype=np.float32) * 0.03


@pytest.fixture
def book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    spoken.clear()
    monkeypatch.setattr("pdf2audiobook.pipeline.KittenProvider", _RecordingKitten)
    config = tmp_path / "xdg"
    (config / "pdf2audiobook").mkdir(parents=True)
    # A pronunciation and citation masking: the reference must have both applied.
    (config / "pdf2audiobook" / "config.toml").write_text(
        '[tts.pronunciations]\ngauge = "gayj"\n\n[reading]\nprocess_citations = true\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    source = tmp_path / "book.pdf"
    pdf = fitz.open()
    for index, line in enumerate(
        ["The harbour gauge read high [12] that night.", "By morning the gauge was calm again."]
    ):
        page = pdf.new_page()
        page.insert_text((80, 60), f"Chapter {index + 1}")
        page.insert_text((80, 115), line)
    pdf.save(source)
    pdf.close()
    output = tmp_path / "out"
    result = runner.invoke(
        app,
        ["convert", str(source), "--no-llm", "--ocr", "never", "--output", str(output), "--json"],
    )
    assert result.exit_code == 0, result.output
    manifest = next(output.glob("*/manifest.json"))
    return {"manifest": manifest, "workspace": manifest.parent}


def _references(manifest_path: Path, **changes: object) -> list[Reference | Unavailable]:
    settings, _ = load_settings()
    if changes:
        settings = settings.model_copy(update=changes, deep=True)
    manifest = read_manifest(manifest_path)
    return [
        chapter_reference(manifest_path.parent, manifest, chapter, settings)
        for chapter in manifest.chapters
    ]


def test_the_reference_is_what_was_spoken(book: dict[str, Path]) -> None:
    references = _references(book["manifest"])
    assert all(isinstance(r, Reference) and r.exact for r in references)
    texts = [r.text for r in references if isinstance(r, Reference)]
    # Every chapter's reference, in order, is exactly the chunks TTS received.
    assert " ".join(texts) == " ".join(spoken)
    joined = " ".join(texts)
    assert "gayj" in joined and "gauge" not in joined
    assert "[12]" not in joined


def test_changed_chapter_text_makes_the_audio_stale(book: dict[str, Path]) -> None:
    text = book["workspace"] / "chapters" / "002.txt"
    text.write_text(text.read_text(encoding="utf-8") + " An added line.", encoding="utf-8")
    references = _references(book["manifest"])
    assert isinstance(references[0], Reference)
    assert references[1] == Unavailable("audio_stale")


def test_missing_audio_is_reported(book: dict[str, Path]) -> None:
    for mp3 in (book["workspace"] / "audio").glob("002 *.mp3"):
        mp3.unlink()
    assert _references(book["manifest"])[1] == Unavailable("audio_missing")


def test_a_replaced_mp3_no_longer_matches_its_sidecar(book: dict[str, Path]) -> None:
    mp3 = next((book["workspace"] / "audio").glob("001 *.mp3"))
    mp3.write_bytes(mp3.read_bytes() + b"\0")
    assert _references(book["manifest"])[0] == Unavailable("audio_stale")


def test_changed_pronunciations_are_no_longer_exact(book: dict[str, Path]) -> None:
    settings, _ = load_settings()
    tts = settings.tts.model_copy(update={"pronunciations": {}})
    references = _references(book["manifest"], tts=tts)
    assert all(isinstance(r, Reference) for r in references)
    assert not any(r.exact for r in references if isinstance(r, Reference))


def test_a_symlinked_mp3_is_not_read(book: dict[str, Path], tmp_path: Path) -> None:
    mp3 = next((book["workspace"] / "audio").glob("001 *.mp3"))
    elsewhere = tmp_path / "elsewhere.mp3"
    shutil.move(mp3, elsewhere)
    mp3.symlink_to(elsewhere)
    assert _references(book["manifest"])[0] == Unavailable("audio_missing")


def test_a_non_english_piper_voice_is_unsupported(book: dict[str, Path]) -> None:
    settings, _ = load_settings()
    piper = settings.tts.piper.model_copy(
        update={"model_path": "/voices/de_DE-thorsten-medium.onnx"}
    )
    tts = settings.tts.model_copy(update={"provider": "piper", "piper": piper})
    assert set(_references(book["manifest"], tts=tts)) == {Unavailable("unsupported_language")}
    english = settings.tts.piper.model_copy(
        update={"model_path": "/voices/en_US-lessac-medium.onnx"}
    )
    tts = settings.tts.model_copy(update={"provider": "piper", "piper": english})
    assert not any(
        isinstance(r, Unavailable) and r.reason == "unsupported_language"
        for r in _references(book["manifest"], tts=tts)
    )


def test_the_ledger_is_what_proves_exactness(book: dict[str, Path]) -> None:
    for ledger in (book["workspace"] / ".cache" / "tts" / "progress").glob("*.json"):
        lines = ledger.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines]
        for record in records:
            if record.get("event") == "chunk":
                record["chunk"]["text_sha256"] = "0" * 64
        ledger.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    assert not any(r.exact for r in _references(book["manifest"]) if isinstance(r, Reference))
