"""M4B output preserves book metadata and navigable chapter titles."""

import json
import shutil
import subprocess

import numpy as np
import pytest
from mutagen.mp4 import MP4

from pdf2audiobook.audio import encode_m4b, encode_mp3


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg/ffprobe are required for M4B packaging acceptance",
)
def test_m4b_contains_aac_audio_tags_and_chapter_navigation(tmp_path):
    chapters = []
    rate = 24000
    for index, title in enumerate(("Opening", "A; B = C"), start=1):
        timeline = np.arange(rate // 3, dtype=np.float32) / rate
        samples = (0.1 * np.sin(2 * np.pi * (300 + index * 100) * timeline)).astype(np.float32)
        path = tmp_path / f"chapter-{index}.mp3"
        encode_mp3(
            samples,
            rate,
            path,
            bitrate="96k",
            target_rate=rate,
            title=title,
            artist="Synthetic Author",
            album="Synthetic Book",
            track=index,
        )
        chapters.append((path, title))

    output = encode_m4b(
        chapters,
        tmp_path / "book.m4b",
        title="Synthetic Book",
        artist="Synthetic Author",
    )

    metadata = MP4(output)
    assert metadata.info is not None and metadata.info.length > 0
    assert metadata.tags["\xa9nam"] == ["Synthetic Book"]
    assert metadata.tags["\xa9ART"] == ["Synthetic Author"]
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    chapters_json = json.loads(probe.stdout)["chapters"]
    assert [chapter["tags"]["title"] for chapter in chapters_json] == [
        "Opening",
        "A; B = C",
    ]
