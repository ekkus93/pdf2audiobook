"""Faults during chapter-audio commits and conversion keep the previous audio (coverage round 3,
TC3 / R3, R4).

The commit tests drive `audio.commit` directly on a small folder; the conversion test runs the
CLI on a synthetic book with a stand-in voice engine.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import fitz
import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook.audio import commit
from pdf2audiobook.cli import app
from pdf2audiobook.errors import AudioError

runner = CliRunner()
needs_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores the folder permissions"
)


def _previous(folder: Path) -> tuple[Path, Path]:
    """A committed chapter: its MP3 and sidecar, plus the staged MP3 a new encode left behind."""
    audio = folder / "audio"
    audio.mkdir(parents=True)
    output = audio / "001 - Chapter One.mp3"
    record = output.with_suffix(".cache.json")
    output.write_bytes(b"previous mp3")
    record.write_text(json.dumps({"previous": True}), encoding="utf-8")
    staged = commit.staged_path(output)
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"new mp3")
    return output, record


def _state(output: Path, record: Path) -> tuple[bytes, bytes]:
    return output.read_bytes(), record.read_bytes()


# --- TC3.01: a read-only audio folder during staging -------------------------------------


@needs_non_root
def test_a_read_only_audio_folder_leaves_the_previous_audio(tmp_path: Path) -> None:
    output, record = _previous(tmp_path)
    before = _state(output, record)
    audio = output.parent
    audio.chmod(0o500)  # read and search only: no new backup folder can be made
    try:
        with pytest.raises(AudioError) as raised:
            commit.commit_chapter_audio(output, record, {"sidecar": 1})
    finally:
        audio.chmod(0o755)

    assert _state(output, record) == before
    assert str(tmp_path) not in str(raised.value)
    assert not commit.staged_path(output).exists()  # the staged MP3 is cleaned up


def test_the_backup_copies_the_previous_audio_when_a_hard_link_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, record = _previous(tmp_path)
    before = _state(output, record)

    def refuse_links(source: str, target: str) -> None:
        raise OSError("hard links are not allowed here")

    monkeypatch.setattr(commit.os, "link", refuse_links)

    commit.commit_chapter_audio(output, record, {"sidecar": 2})

    backups = sorted((output.parent / commit.BACKUP).glob("001 *.mp3"))
    assert len(backups) == 1
    assert (backups[0].read_bytes(), backups[0].with_suffix(".cache.json").read_bytes()) == before
    assert output.read_bytes() == b"new mp3"


# --- TC3.02: a rename that fails while publishing ----------------------------------------


def test_a_failed_publish_says_so_and_names_no_path(tmp_path: Path) -> None:
    output, record = _previous(tmp_path)
    output.unlink()
    output.mkdir()  # the MP3's destination is a folder, so the rename must fail
    try:
        with pytest.raises(AudioError) as raised:
            commit.commit_chapter_audio(output, record, {"sidecar": 3})
    finally:
        shutil.rmtree(output)

    assert str(raised.value) == "Could not publish the new chapter audio; run the conversion again"
    assert str(tmp_path) not in str(raised.value)


# --- TC3.03: recovery with an unreadable journal, and with leftover staged files ----------


def test_recovery_skips_an_unreadable_journal_and_keeps_it(tmp_path: Path) -> None:
    output, record = _previous(tmp_path)
    before = _state(output, record)
    journal = commit._journal(output)
    journal.write_text("{not json", encoding="utf-8")

    finished = commit.recover_audio_commits(output.parent)

    assert finished == 0
    assert journal.exists()  # kept for a person to look at, not guessed at
    assert _state(output, record) == before


def test_recovery_removes_leftover_staged_files_and_folders(tmp_path: Path) -> None:
    output, record = _previous(tmp_path)
    staging = output.parent / commit.STAGING
    (staging / "stray-folder").mkdir()
    (staging / "stray-folder" / "inner.mp3").write_bytes(b"x")
    (staging / "stray.mp3").write_bytes(b"x")

    commit.recover_audio_commits(output.parent)

    assert list(staging.iterdir()) == []


# --- TC3.04: the TTS provider cannot be created --------------------------------------------


class _Kitten:
    sample_rate = 24000
    supports_voice_listing = True
    max_chars_per_chunk = 350

    def __init__(self, model: str) -> None:
        pass

    def list_voices(self) -> list[str]:
        return ["Jasper"]

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        return np.ones(4800, dtype=np.float32) * 0.03


@pytest.fixture
def converted_book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    monkeypatch.setattr("pdf2audiobook.pipeline.KittenProvider", _Kitten)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config"))
    source = tmp_path / "book.pdf"
    pdf = fitz.open()
    for index in range(2):
        page = pdf.new_page()
        page.insert_text((80, 60), f"Chapter {index + 1}")
        page.insert_text((80, 115), f"Sentence {index + 1} of the book.")
    pdf.save(source)
    pdf.close()
    args = [
        "convert",
        str(source),
        "--no-llm",
        "--ocr",
        "never",
        "--output",
        str(tmp_path / "out"),
        "--json",
    ]
    assert runner.invoke(app, args).exit_code == 0
    audio = next((tmp_path / "out").glob("*/audio"))
    return {"args": args, "audio": audio, "mp3": sorted(audio.glob("002 *.mp3"))[0]}


def test_a_chapter_whose_voice_engine_cannot_start_keeps_its_audio(
    converted_book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    mp3 = converted_book["mp3"]
    record = mp3.with_suffix(".cache.json")
    before = _state(mp3, record)

    def no_engine(settings: object) -> None:
        raise AudioError("voice engine is not installed")

    monkeypatch.setattr("pdf2audiobook.pipeline.create_tts_provider", no_engine)
    result = runner.invoke(app, [*converted_book["args"], "--chapter", "2", "--force"])

    assert result.exit_code != 0
    assert _state(mp3, record) == before
    assert not list(converted_book["audio"].glob(f"{commit.STAGING}/*.mp3"))
    assert str(converted_book["audio"]) not in result.output


def test_a_staged_mp3_that_vanishes_mid_commit_fails_and_keeps_the_old_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, record = _previous(tmp_path)
    before = _state(output, record)
    staged = commit.staged_path(output)
    real_backup = commit._backup

    def vanish_then_back_up(output_path: Path, record_path: Path) -> Path | None:
        staged.unlink()  # the staged MP3 disappears after staging and before publishing
        return real_backup(output_path, record_path)

    monkeypatch.setattr(commit, "_backup", vanish_then_back_up)

    with pytest.raises(AudioError):
        commit.commit_chapter_audio(output, record, {"sidecar": 4})

    assert _state(output, record) == before


def _journaled_commit(output: Path, record: Path, *, published: bool) -> bytes:
    """A stopped commit: staged sidecar written, staged MP3 gone, journal left. Returns the new bytes."""
    import hashlib

    new_bytes = b"new mp3"
    staged = commit.staged_path(output)
    staged.with_suffix(".cache.json").write_text(
        json.dumps({"sha256": hashlib.sha256(new_bytes).hexdigest(), "bytes": len(new_bytes)}),
        encoding="utf-8",
    )
    staged.unlink()
    if published:
        output.write_bytes(new_bytes)  # the rename happened before the stop
    commit._journal(output).write_text(
        json.dumps({"output": output.name, "record": record.name}), encoding="utf-8"
    )
    return new_bytes


def test_a_journal_whose_staged_mp3_is_gone_drops_the_commit_and_keeps_the_previous_audio(
    tmp_path: Path,
) -> None:
    output, record = _previous(tmp_path)
    _journaled_commit(output, record, published=False)
    before = _state(output, record)

    finished = commit.recover_audio_commits(output.parent)

    assert finished == 0  # no commit was finished: the new MP3 was never published
    assert _state(output, record) == before
    assert not commit._journal(output).exists()
    assert not commit.staged_path(output).with_suffix(".cache.json").exists()


def test_a_journal_whose_mp3_was_already_published_finishes_the_sidecar(tmp_path: Path) -> None:
    output, record = _previous(tmp_path)
    new_bytes = _journaled_commit(output, record, published=True)
    staged_record = commit.staged_path(output).with_suffix(".cache.json")  # gone after recovery

    finished = commit.recover_audio_commits(output.parent)

    assert finished == 1
    assert output.read_bytes() == new_bytes
    assert json.loads(record.read_text(encoding="utf-8"))["sha256"]  # the new sidecar is in place
    assert not commit._journal(output).exists()
    assert not staged_record.exists()
