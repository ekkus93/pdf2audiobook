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
    kwargs = dict(model="mini", voice="Jasper", speed=1.0, pause_ms=100, cache=tmp_path)
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
        audio,
        24000,
        tmp_path / "chapter.mp3",
        bitrate="128k",
        target_rate=24000,
        title="Chapter One",
        artist="Example Author",
        album="Example Book",
        track=1,
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


def test_chunk_cache_invalidation_for_voice_model_speed_and_resume(tmp_path):
    provider = FakeProvider()
    options = dict(model="mini", voice="Jasper", speed=1.0, pause_ms=100, cache=tmp_path)
    synthesize_chunks("A short sentence.", provider, **options)
    assert provider.calls == 1
    synthesize_chunks("A short sentence.", provider, **options)
    assert provider.calls == 1
    for field, value in [("model", "nano"), ("voice", "Different"), ("speed", 1.2)]:
        changed = dict(options, **{field: value})
        synthesize_chunks("A short sentence.", provider, **changed)
        assert provider.calls >= 2
    before = provider.calls
    synthesize_chunks("A short sentence.", provider, **options, use_cache=False)
    assert provider.calls == before + 1
    synthesize_chunks("A short sentence.", provider, **dict(options, pause_ms=500))
    assert provider.calls == before + 1


class AlternateFakeProvider(FakeProvider):
    """A second engine using the same public model, voice and sample rate."""

    def generate(self, text, *, voice, speed):
        self.calls += 1
        return np.zeros(2400, dtype=np.float32) - 0.025


def test_wav_cache_isolated_by_tts_engine_with_identical_public_settings(tmp_path):
    options = dict(
        model="mini",
        voice="Jasper",
        speed=1.0,
        pause_ms=0,
        cache=tmp_path / "wav",
    )
    first_engine = FakeProvider()
    first_audio = synthesize_chunks("The same synthetic sentence.", first_engine, **options)
    assert first_engine.calls == 1

    second_engine = AlternateFakeProvider()
    second_audio = synthesize_chunks("The same synthetic sentence.", second_engine, **options)
    assert second_engine.calls == 1
    assert not np.array_equal(first_audio, second_audio)
    assert len(list((tmp_path / "wav").glob("*.wav"))) == 2

    # Both engines still resume their own verified chunks independently.
    synthesize_chunks("The same synthetic sentence.", first_engine, **options)
    synthesize_chunks("The same synthetic sentence.", second_engine, **options)
    assert first_engine.calls == 1
    assert second_engine.calls == 1


class FractionalVoice(FakeProvider):
    def generate(self, text, *, voice, speed):
        self.calls += 1
        return np.array([0.123456, -0.123456, 1.2, -1.2], dtype=np.float32)


def test_fresh_and_cached_synthesis_use_identical_canonical_pcm(tmp_path):
    voice = FractionalVoice()
    options = dict(
        model="mini",
        voice="Jasper",
        speed=1.0,
        pause_ms=0,
        cache=tmp_path,
    )
    first = synthesize_chunks("A deterministic synthetic sentence.", voice, **options)
    assert voice.calls == 1
    replay = synthesize_chunks("A deterministic synthetic sentence.", voice, **options)
    assert voice.calls == 1
    assert np.array_equal(first, replay)
    assert np.array_equal(first, read_wav(wav_bytes(first, voice.sample_rate), voice.sample_rate))
    assert first.max() == 1.0
    assert first.min() == -1.0


@pytest.mark.parametrize("sample_rate", [0, -1, 7999, 192001, True, 24000.0, 10**100])
def test_wav_rejects_invalid_sample_rate(sample_rate):
    with pytest.raises(AudioError, match="sample_rate"):
        wav_bytes(np.zeros(32, dtype=np.float32), sample_rate)


@pytest.mark.parametrize("shape", [(2, 32), (32, 2), (1, 32)])
def test_wav_rejects_multidimensional_samples_instead_of_interleaving_channels(shape):
    with pytest.raises(AudioError, match="one-dimensional mono"):
        wav_bytes(np.zeros(shape, dtype=np.float32), 24000)
