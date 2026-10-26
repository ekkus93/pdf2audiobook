"""Long chapter encoding must not inherit the short TTS cache WAV limit."""

import shutil
import tracemalloc
import wave

import numpy as np
import pytest

from pdf2audiobook import audio as audio_module
from pdf2audiobook.audio import encode_mp3, synthesize_chunks, wav_bytes
from pdf2audiobook.errors import AudioError


class _StreamingProvider:
    sample_rate = 24000

    def generate(self, text, *, voice, speed):
        return np.full(24000, 0.05, dtype=np.float32)


def test_synthesis_can_stream_chunks_directly_to_wav(tmp_path):
    chapter = "\n\n".join(f"Sentence number {index} ends here." for index in range(8))
    output = tmp_path / "streamed.wav"
    result = synthesize_chunks(
        chapter,
        _StreamingProvider(),
        model="synthetic",
        voice="default",
        speed=1.0,
        pause_ms=0,
        cache=tmp_path / "cache",
        use_cache=False,
        output_wav=output,
    )
    assert result == output
    with wave.open(str(output), "rb") as reader:
        assert reader.getnchannels() == 1
        assert reader.getframerate() == 24000
        assert reader.getnframes() >= 8 * 24000


def test_streaming_peak_memory_does_not_grow_with_chapter_length(tmp_path):
    # Exclude one-time interpreter/NumPy initialization from the size comparison.
    warmup_text = "\n\n".join(f"Sentence number {index} ends here." for index in range(40))
    synthesize_chunks(
        warmup_text,
        _StreamingProvider(),
        model="synthetic",
        voice="default",
        speed=1.0,
        pause_ms=0,
        cache=tmp_path / "cache-warmup",
        use_cache=False,
        output_wav=tmp_path / "streamed-warmup.wav",
    )
    peaks = []
    for chunk_count in (10, 40):
        chapter = "\n\n".join(f"Sentence number {index} ends here." for index in range(chunk_count))
        tracemalloc.start()
        synthesize_chunks(
            chapter,
            _StreamingProvider(),
            model="synthetic",
            voice="default",
            speed=1.0,
            pause_ms=0,
            cache=tmp_path / f"cache-{chunk_count}",
            use_cache=False,
            output_wav=tmp_path / f"streamed-{chunk_count}.wav",
        )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peaks.append(peak)
    # One float32 chunk is 96 KiB. Chapter growth should add less than that.
    assert peaks[1] - peaks[0] < 24_000 * 4


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


def test_streaming_wav_checks_riff_limit_before_writing(monkeypatch):
    class NearLimitWriter:
        bytes_written = 0xFFFFFFFF - 37

        def writeframesraw(self, _data):
            raise AssertionError("oversized PCM must not be written")

    with pytest.raises(AudioError, match="RIFF size limit"):
        audio_module._write_pcm_chunk(NearLimitWriter(), np.ones(1, dtype=np.float32))
