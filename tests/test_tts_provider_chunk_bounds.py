"""TTS engines with smaller text windows receive bounded, source-aligned chunks."""

import json

import numpy as np
import pytest

from pdf2audiobook.audio import chunk_source_ranges, split_sentences, synthesize_chunks
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
        model="small", voice="Default", speed=1.0, pause_ms=15,
        cache=tmp_path / "wav", progress_file=tmp_path / "progress.json",
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
    ledger = json.loads(opts["progress_file"].read_text(encoding="utf-8"))
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
