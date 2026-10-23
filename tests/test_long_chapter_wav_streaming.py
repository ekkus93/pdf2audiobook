"""Long chapter encoding must not inherit the short TTS cache WAV limit."""

import shutil
import wave

import numpy as np
import pytest

from pdf2audiobook import audio as audio_module
from pdf2audiobook.audio import encode_mp3, wav_bytes
from pdf2audiobook.errors import AudioError


def test_chapter_wav_streaming_exceeds_chunk_cache_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_module, "_MAX_CACHED_WAV_BYTES", 512)
    samples = np.full(1200, 0.1, dtype=np.float32)
    with pytest.raises(AudioError, match="cache limit"):
        wav_bytes(samples, 24000)
    path = tmp_path / "long-chapter.wav"
    audio_module._write_chapter_wav(samples, 24000, path)
    assert path.stat().st_size > 512
    with wave.open(str(path), "rb") as reader:
        assert reader.getnframes() == 1200
        assert reader.getframerate() == 24000
        assert reader.getnchannels() == 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_mp3_chapter_encode_is_not_limited_by_wav_chunk_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_module, "_MAX_CACHED_WAV_BYTES", 512)
    result = encode_mp3(
        np.full(24000, 0.05, dtype=np.float32),
        24000,
        tmp_path / "long-chapter.mp3",
        bitrate="128k",
        target_rate=24000,
        title="Synthetic Chapter",
        artist=None,
        album="Synthetic Book",
        track=1,
    )
    assert result.is_file()
    assert result.stat().st_size > 0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_chapter_wav_streaming_rejects_nonfinite_samples(tmp_path, bad):
    samples = np.array([0.1, bad, 0.2], dtype=np.float32)
    with pytest.raises(AudioError, match="empty/nonfinite"):
        audio_module._write_chapter_wav(samples, 24000, tmp_path / "invalid.wav")
