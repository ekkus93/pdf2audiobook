"""Conversion is single-writer, retries transient TTS errors and isolates bad markers (R77)."""

import fcntl
import json
import subprocess
import wave
from types import SimpleNamespace

import numpy as np
import pytest

import pdf2audiobook.pipeline as pipeline
from pdf2audiobook.audio import synthesize_chunks
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import AudioError, PartialConversionError
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.tts import PiperProvider


def _chapter(number):
    return Chapter(
        id=f"c{number}",
        number=number,
        title=f"Chapter {number}",
        start_block=number - 1,
        end_block=number,
        confidence=1,
    )


class StubProvider:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def list_voices(self):
        return ["Jasper", "Bella"]

    def generate(self, text, *, voice, speed):
        return np.ones(240, dtype=np.float32) * 0.1


def _book(tmp_path, monkeypatch, texts):
    chapters = [_chapter(number) for number in range(1, len(texts) + 1)]
    manifest = BookManifest(
        schema_version=3,
        input_sha256="a" * 64,
        title="Book",
        source_path="book.pdf",
        chapters=chapters,
    )
    path = tmp_path / "manifest.json"

    def render(_manifest, folder, *_args):
        for number, text in enumerate(texts, start=1):
            target = folder / "chapters" / f"{number:03d}.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

    monkeypatch.setattr(pipeline, "analyze_book", lambda *_a, **_k: path)
    monkeypatch.setattr(pipeline, "read_manifest", lambda _p: manifest)
    monkeypatch.setattr(pipeline, "render_chapter_texts", render)
    return path


def _encode(samples, rate, output, **_kwargs):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"fake-mp3")


def test_second_conversion_is_refused_and_leaves_the_first_runs_wav(tmp_path, monkeypatch):
    path = _book(tmp_path, monkeypatch, ["Hello there."])
    wav = tmp_path / ".cache" / "tts" / "chapters" / "chapter-running.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"in use by the other run")
    with (tmp_path / ".convert.lock").open("a+") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        with pytest.raises(AudioError, match="Another conversion is already running"):
            pipeline.convert_book(
                tmp_path / "book.pdf", Settings(), tts_provider=StubProvider(), encoder=_encode
            )
    assert wav.read_bytes() == b"in use by the other run"
    assert path.parent == tmp_path
    # Once the other run finishes, the lock is free and a stale WAV is swept.
    pipeline.convert_book(
        tmp_path / "book.pdf", Settings(), tts_provider=StubProvider(), encoder=_encode
    )
    assert not wav.exists()


def _piper(tmp_path, monkeypatch):
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    Path = type(model)
    Path(f"{model}.json").write_text(json.dumps({"audio": {"sample_rate": 22050}}))
    monkeypatch.setattr("pdf2audiobook.tts.shutil.which", lambda _name: "/usr/bin/piper")
    return PiperProvider(model)


def test_piper_timeout_is_transient_and_the_chunk_is_retried(tmp_path, monkeypatch):
    provider = _piper(tmp_path, monkeypatch)
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(args, 300)
        output = args[args.index("--output_file") + 1]
        with wave.open(output, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(22050)
            stream.writeframes(np.zeros(2205, dtype="<i2").tobytes())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("pdf2audiobook.tts.subprocess.run", fake_run)
    monkeypatch.setattr("pdf2audiobook.audio.time.sleep", lambda _s: None)
    samples = synthesize_chunks(
        "Hello there.",
        provider,
        model="m",
        voice="",
        speed=1.0,
        pause_ms=100,
        cache=tmp_path / "cache",
        max_retries=1,
    )
    assert len(calls) == 2
    assert samples.size > 0


def test_piper_non_timeout_failure_is_not_retried(tmp_path, monkeypatch):
    provider = _piper(tmp_path, monkeypatch)
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr("pdf2audiobook.tts.subprocess.run", fake_run)
    monkeypatch.setattr("pdf2audiobook.audio.time.sleep", lambda _s: None)
    with pytest.raises(AudioError):
        synthesize_chunks(
            "Hello there.",
            provider,
            model="m",
            voice="",
            speed=1.0,
            pause_ms=100,
            cache=tmp_path / "cache",
            max_retries=2,
        )
    assert len(calls) == 1


def test_misplaced_voice_marker_fails_only_its_chapter(tmp_path, monkeypatch):
    _book(
        tmp_path,
        monkeypatch,
        ["Some words\n[[voice:Bella]]\nmore words.", "A good second chapter."],
    )
    with pytest.raises(PartialConversionError, match="chapter\\(s\\): 1"):
        pipeline.convert_book(
            tmp_path / "book.pdf", Settings(), tts_provider=StubProvider(), encoder=_encode
        )
    report = json.loads((tmp_path / "reports" / "conversion_status.json").read_text())
    by_number = {row["number"]: row for row in report["chapters"]}
    assert by_number[1]["status"] == "failed"
    assert by_number[1]["reason_code"] == "invalid_voice_marker"
    assert by_number[2]["status"] == "complete"


def test_resumed_conversion_reports_the_same_pause_count(tmp_path, monkeypatch):
    _book(tmp_path, monkeypatch, ["First part.\n\n* * *\n\nSecond part."])

    def read_mp3(_path, *, ID3):
        return SimpleNamespace(
            info=SimpleNamespace(length=1),
            tags={"title": ["Chapter 1"], "album": ["Book"], "tracknumber": ["1"]},
        )

    monkeypatch.setattr("mutagen.mp3.MP3", read_mp3)
    status = tmp_path / "reports" / "conversion_status.json"
    pipeline.convert_book(
        tmp_path / "book.pdf", Settings(), tts_provider=StubProvider(), encoder=_encode
    )
    first = json.loads(status.read_text())
    assert first["pause_count"] == 1
    pipeline.convert_book(
        tmp_path / "book.pdf", Settings(), tts_provider=StubProvider(), encoder=_encode
    )
    second = json.loads(status.read_text())
    assert second["chapters"][0]["status"] == "complete"
    assert second["pause_count"] == first["pause_count"] == 1
