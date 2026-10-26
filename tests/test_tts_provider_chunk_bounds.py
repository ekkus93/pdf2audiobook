"""TTS engines with smaller text windows receive bounded, source-aligned chunks."""

import numpy as np
import pytest

from pdf2audiobook.audio import (
    chunk_source_ranges,
    read_synthesis_progress,
    split_sentences,
    synthesize_chunks,
)
from pdf2audiobook.errors import AudioError


class BoundedVoice:
    sample_rate = 24000
    max_chars_per_chunk = 64

    def __init__(self):
        self.calls = []

    def generate(self, text, *, voice, speed):
        assert 0 < len(text) <= self.max_chars_per_chunk
        self.calls.append(text)
        return np.full(1200, 0.05, dtype=np.float32)


def _options(tmp_path):
    return dict(
        model="small",
        voice="Default",
        speed=1.0,
        pause_ms=15,
        cache=tmp_path / "wav",
        progress_file=tmp_path / "progress.json",
    )


def test_provider_limit_controls_all_audio_chunks_and_source_offsets(tmp_path):
    source = (
        "The first paragraph contains words that must not be truncated or skipped. "
        "Another sentence follows the first.\n\n"
        "The next paragraph contains its own punctuation and a distinct pause. "
        "The final sentence retains the complete source text."
    )
    provider = BoundedVoice()
    opts = _options(tmp_path)
    synthesize_chunks(source, provider, **opts)
    expected = split_sentences(source, max_chars=provider.max_chars_per_chunk)
    assert len(expected) > 2
    assert provider.calls == expected
    assert all(len(part) <= provider.max_chars_per_chunk for part in provider.calls)
    offsets = chunk_source_ranges(source, expected)
    assert [source[start:end].split() for start, end, _ in offsets] == [
        chunk.split() for chunk in expected
    ]
    ledger = read_synthesis_progress(opts["progress_file"])
    assert ledger["total_chunks"] == len(expected)
    assert ledger["completed_chunks"] == len(expected)
    assert all(chunk["status"] == "completed" for chunk in ledger["chunks"])
    assert source not in opts["progress_file"].read_text(encoding="utf-8")

    fresh = BoundedVoice()
    synthesize_chunks(source, fresh, **opts)
    assert fresh.calls == []  # Cached WAV reuse respects the same chunk identities.


def test_oversized_single_token_fails_before_generating_audio(tmp_path):
    voice = BoundedVoice()
    with pytest.raises(AudioError, match="single narration token exceeds"):
        synthesize_chunks("a" * 65, voice, **_options(tmp_path))
    assert voice.calls == []
    assert not (tmp_path / "progress.json").exists()


@pytest.mark.parametrize("limit", [0, 39, -1, True, 64.5, "64"])
def test_invalid_provider_limits_fail_closed(tmp_path, limit):
    voice = BoundedVoice()
    voice.max_chars_per_chunk = limit
    with pytest.raises(AudioError, match="max_chars_per_chunk"):
        synthesize_chunks("This sentence should never be synthesized.", voice, **_options(tmp_path))
    assert voice.calls == []


@pytest.mark.parametrize("rate", [0, -1, 7999, 192001, True, 24000.5, "24000"])
def test_invalid_tts_sample_rate_does_not_write_cache_or_start_synthesis(
    tmp_path,
    rate,
):
    voice = BoundedVoice()
    voice.sample_rate = rate
    with pytest.raises(AudioError, match="sample_rate"):
        synthesize_chunks("A short synthetic sentence.", voice, **_options(tmp_path))
    assert voice.calls == []
    assert not (tmp_path / "progress.json").exists()
    assert not (tmp_path / "wav").exists()


@pytest.mark.parametrize("pause", [-1, 5001, True, 2.5, "500"])
def test_invalid_pause_length_fails_before_synthesis(tmp_path, pause):
    voice = BoundedVoice()
    opts = dict(_options(tmp_path), pause_ms=pause)
    with pytest.raises(AudioError, match="pause_ms"):
        synthesize_chunks("A short synthetic sentence.", voice, **opts)
    assert voice.calls == []
    assert not (tmp_path / "progress.json").exists()
