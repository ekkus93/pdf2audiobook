"""`resynthesize`: targeted retry with backups, and re-verification after repair (AV4.03, AV4.04)."""

from __future__ import annotations

import itertools
import json
import shutil
from pathlib import Path
from typing import Any

import fitz
import jsonschema
import numpy as np
import pytest
from mutagen.id3 import ID3
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import load_settings
from pdf2audiobook.verification import run as verify_run
from pdf2audiobook.verification.contracts import Readiness, Transcript, Word
from pdf2audiobook.verification.models import SPECS
from pdf2audiobook.verification.reference import Reference, chapter_reference
from pdf2audiobook.workspace import read_manifest

runner = CliRunner()
spoken: list[tuple[str, str]] = []
_takes = itertools.count(1)


class _Kitten:
    sample_rate = 24000
    supports_voice_listing = True
    max_chars_per_chunk = 350

    def __init__(self, model: str) -> None:
        pass

    def list_voices(self) -> list[str]:
        return ["Jasper", "Luna"]

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        spoken.append((voice, text))
        # Each take sounds a little different, as a real retry does.
        return np.ones(4800, dtype=np.float32) * (0.02 + 0.001 * next(_takes))


class _Echo:
    """A model that hears exactly the narration of each chapter."""

    def __init__(self, name: str, narration: dict[int, str]) -> None:
        self.name, self.narration = name, narration

    def readiness(self) -> Readiness:
        revision = SPECS[self.name].revision  # type: ignore[index]
        return Readiness(self.name, "fake", "m", revision, "pytest", "1", True, 1, "/m")  # type: ignore[arg-type]

    def transcribe(self, wav: Path, *, should_stop: Any) -> Transcript:
        words = self.narration[int(wav.stem.split("-")[1])].split()
        return Transcript(
            self.name, tuple(Word(w, i * 0.4, i * 0.4 + 0.3) for i, w in enumerate(words))
        )  # type: ignore[arg-type]


@pytest.fixture
def book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    spoken.clear()
    monkeypatch.setattr("pdf2audiobook.pipeline.KittenProvider", _Kitten)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config"))
    source = tmp_path / "book.pdf"
    pdf = fitz.open()
    for index in range(2):
        page = pdf.new_page()
        page.insert_text((80, 60), f"Chapter {index + 1}")
        page.insert_text(
            (80, 115), f"The keeper climbed {index + 2} long flights of stairs that night."
        )
    pdf.save(source)
    pdf.close()
    cover = tmp_path / "cover.png"
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
    pix.save(cover)
    out = tmp_path / "out"
    converted = runner.invoke(
        app,
        [
            "convert",
            str(source),
            "--no-llm",
            "--ocr",
            "never",
            "--output",
            str(out),
            "--cover",
            str(cover),
            "--json",
        ],
    )
    assert converted.exit_code == 0, converted.output
    manifest = next(out.glob("*/manifest.json"))
    spoken.clear()
    return {"manifest": manifest, "audio": manifest.parent / "audio", "cover": cover.read_bytes()}


def _resynthesize(book: dict[str, Any], *args: str) -> Any:
    return runner.invoke(app, ["resynthesize", str(book["manifest"]), *args, "--json"])


def _narration(book: dict[str, Any]) -> dict[int, str]:
    settings, _ = load_settings()
    manifest = read_manifest(book["manifest"])
    texts = {}
    for chapter in manifest.chapters:
        reference = chapter_reference(book["manifest"].parent, manifest, chapter, settings)
        assert isinstance(reference, Reference)
        texts[chapter.number] = reference.text
    return texts


def _echo_models(book: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    narration = _narration(book)
    monkeypatch.setattr(verify_run, "make_backend", lambda name, **options: _Echo(name, narration))


def test_only_the_chosen_chapter_is_spoken_again_and_backed_up(book: dict[str, Any]) -> None:
    first = next(book["audio"].glob("001 *.mp3")).read_bytes()
    result = _resynthesize(book, "--chapter", "2")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [Path(p).name[:3] for p in payload["mp3_files"]] == ["002"]
    assert spoken and all("3 long flights" in text or "Chapter 2" in text for _, text in spoken)
    assert next(book["audio"].glob("001 *.mp3")).read_bytes() == first
    assert len(list((book["audio"] / ".backup").glob("002 *.mp3"))) == 1
    assert "audio_verification" not in payload  # never checked before, so not now either


def test_a_retry_can_use_another_voice(book: dict[str, Any]) -> None:
    assert _resynthesize(book, "--chapter", "1", "--voice", "Luna").exit_code == 0
    assert {voice for voice, _ in spoken} == {"Luna"}


def test_the_cover_art_already_in_the_mp3_is_kept(book: dict[str, Any]) -> None:
    assert _resynthesize(book, "--chapter", "2").exit_code == 0
    mp3 = next(book["audio"].glob("002 *.mp3"))
    assert bytes(ID3(mp3).getall("APIC")[0].data) == book["cover"]


@pytest.mark.parametrize("args", [[], ["--chapter", "7"]])
def test_choosing_no_or_unknown_chapters_is_refused(book: dict[str, Any], args: list[str]) -> None:
    result = _resynthesize(book, *args)
    assert result.exit_code == 2
    assert spoken == []


def test_a_chapter_checked_before_is_checked_again_after_repair(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _echo_models(book, monkeypatch)
    assert (
        runner.invoke(
            app, ["verify-audio", str(book["manifest"]), "--chapter", "2", "--json"]
        ).exit_code
        == 0
    )
    report_path = book["manifest"].parent / "reports" / "audio_verification.json"
    before = json.loads(report_path.read_text())
    result = _resynthesize(book, "--chapter", "2")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    contract = Path(__file__).parent.parent / "desktop" / "contracts" / "convert.schema.json"
    jsonschema.validate(payload, json.loads(contract.read_text()))
    assert [c["number"] for c in payload["audio_verification"]["chapters"]] == [2]
    after = json.loads(report_path.read_text())
    old = next(c for c in before["chapters"] if c["number"] == 2)
    new = next(c for c in after["chapters"] if c["number"] == 2)
    assert new["audio_sha256"] != old["audio_sha256"]
    settings, _ = load_settings()
    assert (
        verify_run.stale_chapters(
            book["manifest"].parent, read_manifest(book["manifest"]), settings, after
        )
        == set()
    )
    # Opting out skips it.
    skipped = json.loads(_resynthesize(book, "--chapter", "2", "--no-verify-audio").stdout)
    assert "audio_verification" not in skipped


def test_a_repair_makes_the_old_result_stale(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _echo_models(book, monkeypatch)
    report = json.loads(
        runner.invoke(app, ["verify-audio", str(book["manifest"]), "--json"]).stdout
    )
    assert _resynthesize(book, "--chapter", "1", "--no-verify-audio").exit_code == 0
    settings, _ = load_settings()
    manifest = read_manifest(book["manifest"])
    assert verify_run.stale_chapters(book["manifest"].parent, manifest, settings, report) == {1}


def test_results_from_other_model_revisions_are_stale(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _echo_models(book, monkeypatch)
    report = json.loads(
        runner.invoke(app, ["verify-audio", str(book["manifest"]), "--json"]).stdout
    )
    settings, _ = load_settings()
    manifest = read_manifest(book["manifest"])
    assert verify_run.stale_chapters(book["manifest"].parent, manifest, settings, report) == set()
    # Judged with another revision of a model than the pinned one: every result is stale.
    older = {
        **report,
        "models": [
            {**m, "revision": "an-older-revision"} if m["model"] == "vosk" else m
            for m in report["models"]
        ],
    }
    assert verify_run.stale_chapters(book["manifest"].parent, manifest, settings, older) == {1, 2}
