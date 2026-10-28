"""Accepting an edit stales only its chapter's audio; error paths stay content-free (C4)."""

import json
import shutil
from pathlib import Path

import fitz
import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.models import CleanupEdit
from pdf2audiobook.pipeline import analyze_book, convert_book
from pdf2audiobook.workspace import read_manifest, write_manifest

SECRET = "Zanzibar"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")


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


def _book(tmp_path: Path) -> tuple[Path, Settings, Path]:
    source = tmp_path / "book.pdf"
    document = fitz.open()
    for number in (1, 2):
        page = document.new_page()
        page.insert_text((72, 72), f"Chapter {number}", fontsize=24)
        page.insert_text(
            (72, 120), f"Spoken {SECRET} words for part {number} are useful.", fontsize=11
        )
    document.save(source)
    document.close()
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    return source, settings, analyze_book(source, settings)


def _propose(manifest_path: Path, chapter_number: int, replacement: str) -> str:
    manifest = read_manifest(manifest_path)
    chapter = manifest.chapters[chapter_number - 1]
    block = manifest.blocks[chapter.end_block - 1]
    manifest.edits.append(
        CleanupEdit(
            block_id=block.id,
            original=block.text,
            replacement=replacement,
            reason="model proposal",
            confidence=0.9,
            provider="llm",
        )
    )
    write_manifest(manifest_path, manifest)
    return block.id


@needs_ffmpeg
def test_accepting_an_edit_regenerates_only_its_chapters_audio(tmp_path: Path) -> None:
    source, settings, manifest_path = _book(tmp_path)
    block_id = _propose(manifest_path, 1, f"Spoken {SECRET} words for part 1 are quite useful.")
    first = Provider()
    outputs = convert_book(source, settings, tts_provider=first)
    stamps = {p.name: p.stat().st_mtime_ns for p in outputs}

    # A pending proposal changes nothing: converting again reuses everything.
    idle = Provider()
    convert_book(source, settings, tts_provider=idle)
    assert idle.texts == []

    result = CliRunner().invoke(app, ["edits", "accept", str(manifest_path), block_id, "--json"])
    assert result.exit_code == 0, result.stderr
    after = Provider()
    convert_book(source, settings, tts_provider=after)
    assert after.texts and all("quite useful" in text for text in after.texts)
    assert not any("part 2" in text for text in after.texts)
    changed = {p.name for p in outputs if p.stat().st_mtime_ns != stamps[p.name]}
    assert changed == {outputs[0].name}


def test_error_output_for_every_new_failure_is_content_free(tmp_path: Path) -> None:
    _source, _settings, manifest_path = _book(tmp_path)
    block_id = _propose(manifest_path, 1, f"Spoken {SECRET} words for part 1 are quite useful.")
    runner = CliRunner()
    failures = [
        runner.invoke(app, ["edits", "accept", str(manifest_path), "no-such-block", "--json"]),
        runner.invoke(app, ["edits", "list", str(manifest_path), "--status", "bogus", "--json"]),
        runner.invoke(app, ["edits", "reject", str(tmp_path / "missing" / "manifest.json"), "x"]),
    ]
    chapter = tmp_path / "out"
    (next(chapter.glob("*/chapters/001.txt"))).write_text(f"My own {SECRET} text\n", "utf-8")
    from pdf2audiobook.document.structure import render_chapter_texts

    render_chapter_texts(read_manifest(manifest_path), manifest_path.parent)  # records the edit
    failures.append(runner.invoke(app, ["edits", "accept", str(manifest_path), block_id, "--json"]))
    # unknown ID, bad status, missing workspace, hand-edited chapter
    assert [f.exit_code for f in failures] == [2, 2, 4, 4]
    for failure in failures:
        assert failure.exit_code != 0
        text = failure.stdout + failure.stderr
        assert SECRET not in text and str(tmp_path) not in text and "no-such-block" not in text
        if failure.stderr.startswith("{"):
            assert json.loads(failure.stderr)["ok"] is False
