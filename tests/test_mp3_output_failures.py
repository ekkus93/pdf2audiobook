"""Encoded MP3 output failures must not expose private document paths."""

import shutil
from pathlib import Path

import numpy as np
import pytest

from pdf2audiobook import audio as audio_module
from pdf2audiobook.audio import encode_mp3
from pdf2audiobook.errors import AudioError


def _encode(target: Path) -> Path:
    return encode_mp3(
        np.full(2400, 0.05, dtype=np.float32),
        24000,
        target,
        bitrate="128k",
        target_rate=24000,
        title="Synthetic chapter",
        artist=None,
        album="Synthetic book",
        track=1,
    )


def test_mp3_directory_creation_error_redacts_private_path(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_module.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fail_mkdir(_self, *args, **kwargs):
        raise OSError("PRIVATE_BOOK_DIRECTORY: disk access denied")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)
    with pytest.raises(AudioError, match="Could not create MP3 output directory") as exc:
        _encode(tmp_path / "PRIVATE_BOOK_DIRECTORY" / "chapter.mp3")
    assert "PRIVATE_BOOK_DIRECTORY" not in str(exc.value)
    assert exc.value.__suppress_context__ is True


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_mp3_publication_error_redacts_path_and_preserves_existing_file(tmp_path, monkeypatch):
    target = tmp_path / "PRIVATE_BOOK_TITLE.mp3"
    existing = b"existing completed audio placeholder"
    target.write_bytes(existing)

    def fail_replace(_self, _target):
        raise OSError("PRIVATE_BOOK_TITLE: cannot atomically replace output")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(AudioError, match="Could not publish encoded MP3") as exc:
        _encode(target)
    assert "PRIVATE_BOOK_TITLE" not in str(exc.value)
    assert exc.value.__suppress_context__ is True
    assert target.read_bytes() == existing


def test_mp3_temporary_workspace_error_redacts_private_path(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_module.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fail_workspace(*, dir):
        raise OSError("PRIVATE_TEMP_DIRECTORY: cannot create workspace")

    monkeypatch.setattr(audio_module.tempfile, "TemporaryDirectory", fail_workspace)
    target = tmp_path / "PRIVATE_TEMP_DIRECTORY.mp3"
    with pytest.raises(AudioError, match="Could not manage temporary MP3 workspace") as exc:
        _encode(target)
    assert "PRIVATE_TEMP_DIRECTORY" not in str(exc.value)
    assert exc.value.__suppress_context__ is True
    assert not target.exists()
