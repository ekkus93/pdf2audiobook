"""Progress is reported for each stage with correct totals, and stays off for JSON/quiet (R11)."""

import json
import shutil
from pathlib import Path
from typing import Any

import fitz
import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook.audio import synthesize_chunks
from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.llm.cache import CachedLLMProvider
from pdf2audiobook.llm.structure import detect_llm_headings
from pdf2audiobook.models import DocumentBlock
from pdf2audiobook.pipeline import convert_book
from pdf2audiobook.workspace import read_manifest

PRIVATE = "Zanzibar"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")


class _Handle:
    def __init__(self, owner: "Recorder", name: str) -> None:
        self.owner, self.name = owner, name

    def advance(self, count: int = 1, *, cached: bool = False) -> None:
        self.owner.events.append(("advance", self.name, count, cached))

    def set_total(self, total: int) -> None:
        self.owner.events.append(("total", self.name, total))

    def set_detail(self, text: str) -> None:
        self.owner.events.append(("detail", self.name, text))

    def close(self) -> None:
        self.owner.events.append(("close", self.name))


class Recorder:
    enabled = True

    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []

    def stage(self, name: str, total: int | None, unit: str, initial: int = 0) -> _Handle:
        self.events.append(("stage", name, total, unit, initial))
        return _Handle(self, name)

    def summary(self, text: str) -> None:
        self.events.append(("summary", text))

    def close(self) -> None:
        self.events.append(("close-all",))

    def stages(self, name: str) -> list[tuple[Any, ...]]:
        return [event for event in self.events if event[:2] == ("stage", name)]

    def advanced(self, name: str, *, cached: bool | None = None) -> int:
        return sum(
            event[2]
            for event in self.events
            if event[:2] == ("advance", name) and (cached is None or event[3] is cached)
        )

    def details(self, name: str) -> list[str]:
        return [event[2] for event in self.events if event[:2] == ("detail", name)]


class _Provider:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def list_voices(self) -> list[str]:
        return ["Jasper"]

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        return np.ones(240, dtype=np.float32) * 0.1


def _encode(_samples, _rate, target: Path, **_kwargs) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"synthetic audio")


def _book(tmp_path: Path) -> tuple[Path, Settings]:
    source = tmp_path / "book.pdf"
    doc = fitz.open()
    for number in (1, 2):
        page = doc.new_page()
        page.insert_text((72, 72), f"Chapter {number}", fontsize=24)
        page.insert_text(
            (72, 120), f"Spoken {PRIVATE} words for part number {number}.", fontsize=11
        )
    doc.save(source)
    doc.close()
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    return source, settings


def test_conversion_reports_pages_then_characters_with_chapter_details(tmp_path: Path) -> None:
    source, settings = _book(tmp_path)
    recorder = Recorder()
    outputs = convert_book(
        source, settings, tts_provider=_Provider(), encoder=_encode, progress=recorder
    )
    folder = outputs[0].parent.parent
    texts = [(folder / "chapters" / f"{n:03d}.txt").read_text(encoding="utf-8") for n in (1, 2)]
    pages = recorder.stages("Extracting pages")
    assert pages == [("stage", "Extracting pages", 2, "page", 0)]
    assert recorder.advanced("Extracting pages") == 2
    synthesis = recorder.stages("Synthesizing speech")
    assert synthesis == [("stage", "Synthesizing speech", sum(map(len, texts)), "char", 0)]
    assert recorder.advanced("Synthesizing speech") == sum(map(len, texts))
    assert recorder.details("Synthesizing speech") == ["chapter 1/2", "chapter 2/2"]


@needs_ffmpeg
def test_resumed_conversion_counts_the_cached_chapter_as_initial_work(tmp_path: Path) -> None:
    source, settings = _book(tmp_path)
    outputs = convert_book(source, settings, tts_provider=_Provider())
    folder = outputs[0].parent.parent
    first = (folder / "chapters" / "001.txt").read_text(encoding="utf-8")
    second = (folder / "chapters" / "002.txt").read_text(encoding="utf-8")
    outputs[1].unlink()
    outputs[1].with_suffix(".cache.json").unlink()
    recorder = Recorder()
    convert_book(source, settings, tts_provider=_Provider(), progress=recorder)
    assert recorder.stages("Synthesizing speech") == [
        ("stage", "Synthesizing speech", len(first) + len(second), "char", len(first))
    ]
    assert recorder.advanced("Synthesizing speech") == len(second)
    assert recorder.details("Synthesizing speech") == ["chapter 1/1"]


@needs_ffmpeg
def test_a_fully_cached_conversion_shows_no_synthesis_bar(tmp_path: Path) -> None:
    source, settings = _book(tmp_path)
    convert_book(source, settings, tts_provider=_Provider())
    recorder = Recorder()
    convert_book(source, settings, tts_provider=_Provider(), progress=recorder)
    assert recorder.stages("Synthesizing speech") == []


def test_names_and_details_never_contain_book_text_or_paths(tmp_path: Path) -> None:
    source, settings = _book(tmp_path)
    recorder = Recorder()
    convert_book(source, settings, tts_provider=_Provider(), encoder=_encode, progress=recorder)
    text = json.dumps(recorder.events, default=str)
    assert PRIVATE not in text and str(tmp_path) not in text and "Chapter 1" not in text


def test_synthesis_reports_each_chunk_and_flags_cached_replays(tmp_path: Path) -> None:
    text = "First sentence here. Second sentence follows. Third one ends."
    calls: list[tuple[int, bool]] = []
    cache = tmp_path / "cache"
    cache.mkdir()
    kwargs = dict(
        model="m",
        voice="Jasper",
        speed=1.0,
        pause_ms=0,
        cache=cache,
        on_chunk=lambda n, c: calls.append((n, c)),
    )
    synthesize_chunks(text, _Provider(), **kwargs)  # type: ignore[arg-type]
    fresh = list(calls)
    calls.clear()
    synthesize_chunks(text, _Provider(), **kwargs)  # type: ignore[arg-type]
    assert fresh and all(cached is False for _, cached in fresh)
    assert calls and all(cached is True for _, cached in calls)
    assert sum(n for n, _ in fresh) == sum(n for n, _ in calls) <= len(text)


def test_cached_llm_provider_reports_expected_hits_and_misses(tmp_path: Path) -> None:
    class Inner:
        def complete_json(self, *, instructions: str, document_text: str) -> dict[str, Any]:
            return {"headings": []}

    recorder = Recorder()
    worker = CachedLLMProvider(Inner(), cache_dir=tmp_path / "cache", identity="x")
    worker.progress = recorder.stage("Analyzing with the LLM", None, "request")
    worker.expect_requests(2, "cleanup")
    worker.complete_json(instructions="a", document_text="b")
    worker.complete_json(instructions="a", document_text="b")
    assert ("total", "Analyzing with the LLM", 2) in recorder.events
    assert recorder.details("Analyzing with the LLM") == ["cleanup"]
    assert recorder.advanced("Analyzing with the LLM", cached=False) == 1
    assert recorder.advanced("Analyzing with the LLM", cached=True) == 1


def test_a_stage_announces_its_planned_requests_before_making_them() -> None:
    announced: list[tuple[int, str]] = []
    requests: list[str] = []

    class Provider:
        def expect_requests(self, count: int, stage: str) -> None:
            announced.append((count, stage))
            assert not requests, "announce before the first request"

        def complete_json(self, *, instructions: str, document_text: str) -> dict[str, Any]:
            requests.append(document_text)
            return {"headings": []}

    blocks = [DocumentBlock(id=f"b{i}", page_index=0, text=f"Line {i}.") for i in range(3)]
    detect_llm_headings(blocks, Provider(), chunk_tokens=4000, decisions=[])  # type: ignore[arg-type]
    assert announced and announced[0][1] == "structure"
    assert announced[0][0] == len(requests) >= 1


def test_forced_progress_prints_stages_and_a_summary_to_stderr_only(tmp_path: Path) -> None:
    source, _ = _book(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "--progress",
            "analyze",
            str(source),
            "--no-config",
            "--no-llm",
            "--ocr",
            "never",
            "--output",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert "Extracting pages" in result.stderr and "Analysis finished in" in result.stderr
    assert "Extracting pages" not in result.stdout
    progress_lines = [
        line
        for line in result.stderr.replace("\r", "\n").splitlines()
        if "Extracting" in line or "finished in" in line
    ]
    assert progress_lines
    assert PRIVATE not in result.stderr
    assert not any(str(tmp_path) in line for line in progress_lines)


@pytest.mark.parametrize("flags", [["--progress", "--quiet"], [], ["--no-progress"]])
def test_progress_is_off_when_quiet_not_a_terminal_or_disabled(tmp_path: Path, flags) -> None:
    source, _ = _book(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            *flags,
            "analyze",
            str(source),
            "--no-config",
            "--no-llm",
            "--ocr",
            "never",
            "--output",
            str(tmp_path / "out"),
        ],
        env={"PDF2AUDIOBOOK_PROGRESS": "always"} if flags == ["--no-progress"] else None,
    )
    assert result.exit_code == 0, result.stderr
    assert "Extracting pages" not in result.stderr and "finished in" not in result.stderr


def test_json_output_never_shows_progress_even_when_forced(tmp_path: Path) -> None:
    source, _ = _book(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "--progress",
            "analyze",
            str(source),
            "--no-config",
            "--no-llm",
            "--ocr",
            "never",
            "--output",
            str(tmp_path / "out"),
            "--json",
        ],
        env={"PDF2AUDIOBOOK_PROGRESS": "always"},
    )
    assert result.exit_code == 0, result.stderr
    assert "manifest" in json.loads(result.stdout)
    assert "Extracting pages" not in result.stderr and "finished in" not in result.stderr


def test_the_environment_setting_enables_progress_without_the_flag(tmp_path: Path) -> None:
    source, _ = _book(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "analyze",
            str(source),
            "--no-config",
            "--no-llm",
            "--ocr",
            "never",
            "--output",
            str(tmp_path / "out"),
        ],
        env={"PDF2AUDIOBOOK_PROGRESS": "always"},
    )
    assert result.exit_code == 0, result.stderr
    assert "Extracting pages" in result.stderr


def test_pack_m4b_shows_checking_and_encoding_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, settings = _book(tmp_path)
    convert_book(source, settings, tts_provider=_Provider(), encoder=_encode)
    manifest_path = next((tmp_path / "out").glob("*/manifest.json"))
    assert len(read_manifest(manifest_path).chapters) == 2
    monkeypatch.setattr("pdf2audiobook.audio.encode_m4b", lambda *_a, **_k: tmp_path / "book.m4b")
    result = CliRunner().invoke(
        app,
        [
            "--progress",
            "pack-m4b",
            str(manifest_path),
            "--output",
            str(tmp_path / "book.m4b"),
            "--no-config",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert "Checking chapter audio" in result.stderr and "Encoding M4B" in result.stderr
    assert "Packaged 2 chapter(s)" in result.stderr
    assert PRIVATE not in result.stderr
