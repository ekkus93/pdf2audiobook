"""Interrupted synthesis must resume from validated per-chunk WAV checkpoints."""

import numpy as np
import pytest

from pdf2audiobook.audio import split_sentences, synthesize_chunks
from pdf2audiobook.errors import AudioError


class InterruptibleProvider:
    sample_rate = 24000

    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def generate(self, text, *, voice, speed):
        self.calls.append(text)
        if self.fail_at == len(self.calls):
            raise AudioError("simulated interruption")
        return np.full(1200, 0.1, dtype=np.float32)


def _chapter():
    # Deliberately exceed the half-chunk sentence threshold for three
    # separate, stable cache keys rather than depending on punctuation alone.
    return " ".join([" ".join([word] * 38) + "." for word in ("alpha", "bravo", "charlie")])


def test_interrupted_synthesis_reuses_only_completed_chunks(tmp_path):
    chapter = _chapter()
    chunks = split_sentences(chapter)
    assert len(chunks) == 3
    options = dict(
        model="mini",
        voice="Jasper",
        speed=1.0,
        pause_ms=0,
        cache=tmp_path,
    )
    interrupted = InterruptibleProvider(fail_at=2)
    with pytest.raises(AudioError, match="TTS synthesis failed"):
        synthesize_chunks(chapter, interrupted, **options)
    assert interrupted.calls == chunks[:2]
    assert len(list(tmp_path.glob("*.wav"))) == 1

    resumed = InterruptibleProvider()
    audio = synthesize_chunks(chapter, resumed, **options)
    assert resumed.calls == chunks[1:]
    assert audio.size == 3 * 1200
    assert len(list(tmp_path.glob("*.wav"))) == 3

    # A fresh process/provider instance must reuse the complete checkpoint.
    fully_cached = InterruptibleProvider()
    synthesize_chunks(chapter, fully_cached, **options)
    assert fully_cached.calls == []


def test_no_resume_regenerates_all_chunks(tmp_path):
    chapter = _chapter()
    options = dict(
        model="mini",
        voice="Jasper",
        speed=1.0,
        pause_ms=0,
        cache=tmp_path,
    )
    synthesize_chunks(chapter, InterruptibleProvider(), **options)
    forced = InterruptibleProvider()
    synthesize_chunks(chapter, forced, use_cache=False, **options)
    assert forced.calls == split_sentences(chapter)
