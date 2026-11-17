"""Chapter audio is replaced safely and the previous audio kept (audio verification AV4.01, AV4.02)."""

from __future__ import annotations

import errno
import json
import shutil
from pathlib import Path
from typing import Any

import fitz
import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook.audio import commit
from pdf2audiobook.audio.freshness import valid_mp3_sidecar
from pdf2audiobook.cli import app

runner = CliRunner()


class _Kitten:
    sample_rate = 24000
    supports_voice_listing = True
    max_chars_per_chunk = 350
    tone = 0.03
    fail = False
    interrupt = False

    def __init__(self, model: str) -> None:
        pass

    def list_voices(self) -> list[str]:
        return ["Jasper"]

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        if _Kitten.interrupt:
            raise KeyboardInterrupt
        if _Kitten.fail:
            raise RuntimeError("voice engine broke")
        return np.ones(4800, dtype=np.float32) * _Kitten.tone


@pytest.fixture
def book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    _Kitten.tone, _Kitten.fail, _Kitten.interrupt = 0.03, False, False
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
    out = tmp_path / "out"
    args = ["convert", str(source), "--no-llm", "--ocr", "never", "--output", str(out), "--json"]
    assert runner.invoke(app, args).exit_code == 0
    audio = next(out.glob("*/audio"))
    return {"args": args, "audio": audio, "mp3": sorted(audio.glob("002 *.mp3"))[0]}


def _again(book: dict[str, Any], *extra: str) -> Any:
    return runner.invoke(app, [*book["args"], "--chapter", "2", "--force", *extra])


def _state(mp3: Path) -> tuple[bytes, bytes]:
    return mp3.read_bytes(), mp3.with_suffix(".cache.json").read_bytes()


def _no_leftovers(audio: Path) -> None:
    assert (
        not list((audio / commit.STAGING).glob("*")) if (audio / commit.STAGING).exists() else True
    )
    assert not list(audio.glob(".commit-*")) and not list(audio.glob("tmp*"))


def test_a_forced_retry_keeps_the_previous_audio_as_a_backup(book: dict[str, Any]) -> None:
    before = _state(book["mp3"])
    _Kitten.tone = 0.05
    assert _again(book).exit_code == 0
    after = _state(book["mp3"])
    assert after[0] != before[0]
    assert valid_mp3_sidecar(book["mp3"]) is not None
    backups = sorted((book["audio"] / commit.BACKUP).glob("002 *.mp3"))
    assert len(backups) == 1
    assert (backups[0].read_bytes(), backups[0].with_suffix(".cache.json").read_bytes()) == before
    # Backups sit below audio/, so the chapter list and pack-m4b never see them.
    assert sorted(p.name for p in book["audio"].glob("*.mp3")) == sorted(
        p.name for p in book["audio"].glob("00? *.mp3")
    )
    _no_leftovers(book["audio"])


def test_a_failed_synthesis_leaves_the_previous_audio(book: dict[str, Any]) -> None:
    before = _state(book["mp3"])
    _Kitten.fail = True
    result = _again(book)
    assert result.exit_code != 0
    assert _state(book["mp3"]) == before and valid_mp3_sidecar(book["mp3"]) is not None
    _no_leftovers(book["audio"])


def test_an_interrupted_synthesis_leaves_the_previous_audio(book: dict[str, Any]) -> None:
    before = _state(book["mp3"])
    _Kitten.interrupt = True
    result = _again(book)
    assert result.exit_code == 130
    assert _state(book["mp3"]) == before
    _no_leftovers(book["audio"])


def test_a_full_disk_while_staging_leaves_the_previous_audio(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _state(book["mp3"])

    def full(path: Path, data: bytes) -> None:
        raise OSError(errno.ENOSPC, "No space left on device", str(path))

    monkeypatch.setattr(commit, "atomic_write", full)
    _Kitten.tone = 0.05
    result = _again(book)
    assert result.exit_code != 0
    assert "No space" not in result.output and str(book["audio"]) not in result.output
    assert _state(book["mp3"]) == before and valid_mp3_sidecar(book["mp3"]) is not None
    _no_leftovers(book["audio"])


def test_a_commit_stopped_after_its_journal_is_finished_next_time(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def stop(journal: Path, **_kw: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(commit, "_finish", stop)
    _Kitten.tone = 0.05
    assert _again(book).exit_code == 130
    # The renames never happened: the old MP3 and sidecar still belong together.
    assert valid_mp3_sidecar(book["mp3"]) is not None
    assert list(book["audio"].glob(".commit-*"))
    staged = commit.staged_path(book["mp3"]).read_bytes()
    monkeypatch.undo()
    monkeypatch.setattr("pdf2audiobook.pipeline.KittenProvider", _Kitten)
    # Any later conversion finishes the commit first.
    assert runner.invoke(app, book["args"]).exit_code == 0
    assert book["mp3"].read_bytes() == staged
    assert valid_mp3_sidecar(book["mp3"]) is not None
    _no_leftovers(book["audio"])


def test_recovery_drops_unjournaled_staging_and_old_temporary_folders(book: dict[str, Any]) -> None:
    staging = book["audio"] / commit.STAGING
    staging.mkdir(exist_ok=True)
    (staging / "002 - stray.mp3").write_bytes(b"never committed")
    (book["audio"] / "tmpabc123").mkdir()
    before = _state(book["mp3"])
    assert commit.recover_audio_commits(book["audio"]) == 0
    assert _state(book["mp3"]) == before
    _no_leftovers(book["audio"])


def test_only_the_newest_backups_are_kept(book: dict[str, Any]) -> None:
    for tone in (0.04, 0.05, 0.06, 0.07, 0.08):
        _Kitten.tone = tone
        assert _again(book).exit_code == 0
    assert len(list((book["audio"] / commit.BACKUP).glob("002 *.mp3"))) == commit.KEEP_BACKUPS
    assert (
        len(list((book["audio"] / commit.BACKUP).glob("002 *.cache.json"))) == commit.KEEP_BACKUPS
    )


def test_the_journal_names_only_files_in_the_audio_folder(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        commit, "_finish", lambda journal, **_kw: (_ for _ in ()).throw(KeyboardInterrupt)
    )
    _Kitten.tone = 0.05
    _again(book)
    journal = next(book["audio"].glob(".commit-*"))
    assert set(json.loads(journal.read_text())) == {"output", "record"}
    assert "/" not in json.loads(journal.read_text())["output"]
