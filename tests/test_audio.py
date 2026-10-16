import shutil

import numpy as np
import pytest

from pdf2audiobook.audio import encode_mp3, read_wav, split_sentences, synthesize_chunks, wav_bytes
from pdf2audiobook.errors import AudioError


class FakeProvider:
    sample_rate = 24000

    def __init__(self):
        self.calls = 0

    def generate(self, text, *, voice, speed):
        self.calls += 1
        return np.zeros(2400, dtype=np.float32) + 0.025


def test_sentence_chunking_preserves_words():
    text = "One chapter begins. This sentence continues. And this ends!"
    parts = split_sentences(text, max_chars=40)
    assert len(parts) >= 2
    assert " ".join(parts) == text
    assert all(len(item) <= 40 for item in parts)


def test_cache_reuses_pcm_chunks(tmp_path):
    provider = FakeProvider()
    kwargs = dict(
        model="mini", voice="Jasper", speed=1.0,
        pause_ms=100, cache=tmp_path
    )
    first = synthesize_chunks("Hi there. Another sentence.", provider, **kwargs)
    count = provider.calls
    second = synthesize_chunks("Hi there. Another sentence.", provider, **kwargs)
    assert count > 0
    assert provider.calls == count
    assert len(first) == len(second)
    assert read_wav(wav_bytes(first, provider.sample_rate), provider.sample_rate).size > 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_ffmpeg_mp3_encodes_and_tags(tmp_path):
    from mutagen.easyid3 import EasyID3
    from mutagen.mp3 import MP3

    audio = np.zeros(24000, dtype=np.float32) + 0.01
    result = encode_mp3(
        audio, 24000, tmp_path / "chapter.mp3",
        bitrate="128k", target_rate=24000,
        title="Chapter One", artist="Example Author", album="Example Book", track=1
    )
    assert MP3(result).info.length > 0
    assert EasyID3(result)["album"] == ["Example Book"]
    assert EasyID3(result)["tracknumber"] == ["1"]


def test_empty_audio_rejected():
    with pytest.raises(AudioError):
        wav_bytes(np.array([], dtype=np.float32), 24000)


def test_corrupt_wav_cache_regenerates_only_affected_chunk(tmp_path):
    provider = FakeProvider()
    kwargs = dict(model="mini", voice="Jasper", speed=1, pause_ms=0, cache=tmp_path)
    synthesize_chunks("One sentence. Another sentence.", provider, **kwargs)
    original = provider.calls
    files = list(tmp_path.glob("*.wav"))
    assert files
    files[0].write_bytes(b"RIFF invalid")
    synthesize_chunks("One sentence. Another sentence.", provider, **kwargs)
    assert provider.calls == original + 1
    synthesize_chunks("One sentence. Another sentence.", provider, **kwargs)
    assert provider.calls == original + 1
