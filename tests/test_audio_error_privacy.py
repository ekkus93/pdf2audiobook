"""Sensitive FFmpeg and ID3 diagnostics must never disclose book data."""

import subprocess
from pathlib import Path

import numpy as np
import pytest

import pdf2audiobook.audio as audio
from pdf2audiobook.errors import AudioError

PRIVATE = "PRIVATE_BOOK_IDENTIFIER_789"


def _encode(tmp_path: Path) -> None:
    audio.encode_mp3(
        np.full(200, 0.01, dtype=np.float32),
        24000,
        tmp_path / PRIVATE / "chapter.mp3",
        bitrate="128k",
        target_rate=24000,
        title=PRIVATE,
        artist="Fictional Author",
        album="Example",
        track=1,
    )


@pytest.mark.parametrize(
    ("failure", "expected_message"),
    [
        ("exit", "FFmpeg encoding failed (exit status 7)"),
        ("oserror", "Cannot execute FFmpeg"),
        ("timeout", "FFmpeg encoding timed out"),
        ("metadata", "MP3 metadata validation failed"),
    ],
)
def test_audio_errors_redact_private_backend_diagnostics(
    monkeypatch, tmp_path: Path, failure: str, expected_message: str
):
    monkeypatch.setattr(audio.shutil, "which", lambda executable: "/usr/bin/ffmpeg")

    def fake_run(command, **kwargs):
        if failure == "oserror":
            raise OSError(f"failed to launch {PRIVATE}")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1, stderr=PRIVATE.encode())
        if failure == "metadata":
            Path(command[-1]).write_bytes(b"synthetic invalid mp3 bytes")
            return subprocess.CompletedProcess(command, 0, b"", b"")
        return subprocess.CompletedProcess(command, 7, b"", PRIVATE.encode())

    monkeypatch.setattr(audio.subprocess, "run", fake_run)

    if failure == "metadata":
        def invalid_metadata(*args, **kwargs):
            raise ValueError(f"invalid ID3 book content {PRIVATE}")

        monkeypatch.setattr(audio, "MP3", invalid_metadata)

    with pytest.raises(AudioError) as raised:
        _encode(tmp_path)

    assert expected_message in str(raised.value)
    assert PRIVATE not in str(raised.value)
    assert PRIVATE not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert not (tmp_path / PRIVATE / "chapter.mp3").exists()
