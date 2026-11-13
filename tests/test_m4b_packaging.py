"""M4B output preserves book metadata and navigable chapter titles."""

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from mutagen.mp4 import MP4

from pdf2audiobook.audio import encode_m4b, encode_mp3, encoding
from pdf2audiobook.errors import AudioError


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


# --- Packaging failures (test coverage spec T5) --------------------------------


class _FFmpeg:
    """Stands in for `encoding.subprocess`: an exit status, an output, or a timeout."""

    PIPE = subprocess.PIPE
    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, returncode=0, output=b"fake m4b", timeout=False):
        self.calls = 0
        self.returncode, self.output, self.timeout = returncode, output, timeout

    def run(self, command, **_kwargs):
        self.calls += 1
        if self.timeout:
            raise subprocess.TimeoutExpired(command, 3600)
        if self.output is not None:
            Path(command[-1]).write_bytes(self.output)
        return subprocess.CompletedProcess(command, self.returncode, b"", b"private stderr")


def _fake_tools(monkeypatch, ffmpeg=None, *, installed=True, chapter_length=1.5):
    ffmpeg = ffmpeg or _FFmpeg()
    monkeypatch.setattr(encoding, "subprocess", ffmpeg)
    monkeypatch.setattr(
        encoding,
        "shutil",
        SimpleNamespace(
            which=lambda _name: "/usr/bin/ffmpeg" if installed else None,
            copyfile=shutil.copyfile,
        ),
    )
    monkeypatch.setattr(
        encoding, "MP3", lambda _path: SimpleNamespace(info=SimpleNamespace(length=chapter_length))
    )
    return ffmpeg


def _chapter_files(folder, count=2):
    folder.mkdir()
    chapters = []
    for index in range(1, count + 1):
        path = folder / f"{index:03d}.mp3"
        path.write_bytes(b"chapter audio")
        chapters.append((path, f"Chapter {index}"))
    return chapters


def _package(tmp_path, chapters):
    return encode_m4b(chapters, tmp_path / "out" / "book.m4b", title="Synthetic Book", artist=None)


def _assert_no_output(tmp_path):
    out = tmp_path / "out"
    assert not out.exists() or list(out.iterdir()) == []


def test_missing_ffmpeg_stops_packaging(tmp_path, monkeypatch):
    """T5.b: without FFmpeg, encode_m4b writes nothing."""
    ffmpeg = _fake_tools(monkeypatch, installed=False)

    with pytest.raises(AudioError, match="^FFmpeg executable not found in PATH$"):
        _package(tmp_path, _chapter_files(tmp_path / "chapters"))

    assert ffmpeg.calls == 0
    _assert_no_output(tmp_path)


def test_audiobook_needs_at_least_one_chapter(tmp_path, monkeypatch):
    """T5.c: an empty chapter list is refused before any work."""
    ffmpeg = _fake_tools(monkeypatch)

    with pytest.raises(AudioError, match="^Cannot package an audiobook with no chapters$"):
        _package(tmp_path, [])

    assert ffmpeg.calls == 0
    _assert_no_output(tmp_path)


@pytest.mark.parametrize("problem", ["missing-file", "zero-length", "nan-length", "unreadable"])
def test_invalid_chapter_audio_is_refused(tmp_path, monkeypatch, problem):
    """T5.c: a missing, empty or unparseable chapter stops packaging."""
    ffmpeg = _fake_tools(
        monkeypatch,
        chapter_length={"zero-length": 0.0, "nan-length": float("nan")}.get(problem, 1.5),
    )
    chapters = _chapter_files(tmp_path / "chapters")
    if problem == "missing-file":
        chapters[1][0].unlink()
    if problem == "unreadable":

        def unreadable(_path):
            raise OSError(5, "I/O error", str(_path))

        monkeypatch.setattr(encoding, "MP3", unreadable)

    with pytest.raises(
        AudioError, match="^An audiobook chapter is missing, invalid or has zero duration$"
    ) as error:
        _package(tmp_path, chapters)

    assert str(tmp_path) not in str(error.value)
    assert ffmpeg.calls == 0
    _assert_no_output(tmp_path)


@pytest.mark.parametrize(
    ("ffmpeg", "message"),
    [
        (_FFmpeg(returncode=3), r"^FFmpeg audiobook packaging failed \(exit status 3\)$"),
        (_FFmpeg(output=None), r"^FFmpeg audiobook packaging failed \(exit status 0\)$"),
        (_FFmpeg(output=b""), r"^FFmpeg audiobook packaging failed \(exit status 0\)$"),
        (_FFmpeg(timeout=True), "^FFmpeg audiobook packaging failed or timed out$"),
        (_FFmpeg(output=b"not an mp4 container"), "^M4B metadata validation failed"),
    ],
    ids=["nonzero-exit", "no-output", "empty-output", "timeout", "invalid-mp4"],
)
def test_ffmpeg_packaging_failures_publish_nothing(tmp_path, monkeypatch, ffmpeg, message):
    """T5.c: each failure gives a fixed message (never FFmpeg's stderr) and no M4B."""
    _fake_tools(monkeypatch, ffmpeg)

    with pytest.raises(AudioError, match=message) as error:
        _package(tmp_path, _chapter_files(tmp_path / "chapters"))

    assert "private stderr" not in str(error.value)
    _assert_no_output(tmp_path)


class _FakeMP4:
    """Stands in for mutagen's MP4 across the parse, tag and reparse calls."""

    def __init__(self, lengths):
        self.lengths = list(lengths)
        self.saved = []

    def __call__(self, _path):
        length = self.lengths.pop(0)
        container = SimpleNamespace(
            info=None if length is None else SimpleNamespace(length=length), tags=None
        )

        def add_tags():
            container.tags = {}

        container.add_tags = add_tags
        container.save = lambda: self.saved.append(dict(container.tags))
        return container


@pytest.mark.parametrize(
    ("lengths", "published"),
    [([0.0, 2.0], False), ([None, 2.0], False), ([2.0, None], False), ([2.0, 2.0], True)],
    ids=["zero-length", "no-audio-info", "invalid-after-tagging", "valid"],
)
def test_m4b_container_is_checked_before_and_after_tagging(
    tmp_path, monkeypatch, lengths, published
):
    """T5.c: empty audio, or audio that fails the reparse, is never published."""
    _fake_tools(monkeypatch)
    mp4 = _FakeMP4(lengths)
    monkeypatch.setattr(encoding, "MP4", mp4)
    chapters = _chapter_files(tmp_path / "chapters")

    if published:
        output = _package(tmp_path, chapters)
        assert output.read_bytes() == b"fake m4b"
        assert mp4.saved == [{"\xa9nam": "Synthetic Book", "\xa9alb": "Synthetic Book"}]
    else:
        with pytest.raises(AudioError, match="^M4B metadata validation failed"):
            _package(tmp_path, chapters)
        _assert_no_output(tmp_path)
