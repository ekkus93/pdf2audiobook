"""Validate generated chapter MP3 files by decoding with FFmpeg."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3

from pdf2audiobook.audio import encode_mp3


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
@pytest.mark.parametrize(
    ("rate", "seconds", "bitrate", "track"),
    [(24000, 0.6, "128k", 1), (44100, 1.2, "96k", 2)],
)
def test_mp3_decode_tags_and_duration(
    tmp_path: Path, rate: int, seconds: float, bitrate: str, track: int,
):
    timeline = np.arange(int(rate * seconds), dtype=np.float32) / rate
    audio = (0.12 * np.sin(2 * np.pi * 440 * timeline)).astype(np.float32)
    path = tmp_path / f"chapter-{track}.mp3"
    encode_mp3(
        audio, rate, path, bitrate=bitrate, target_rate=rate,
        title=f"Chapter {track}", artist="Synthetic Author",
        album="Synthetic Book", track=track,
    )
    assert path.is_file() and path.stat().st_size > 0
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-xerror",
         "-nostdin", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    metadata = MP3(path)
    assert abs(metadata.info.length - seconds) < 0.2
    assert metadata.info.sample_rate == rate
    tags = EasyID3(path)
    assert tags["title"] == [f"Chapter {track}"]
    assert tags["artist"] == ["Synthetic Author"]
    assert tags["album"] == ["Synthetic Book"]
    assert tags["tracknumber"] == [str(track)]
