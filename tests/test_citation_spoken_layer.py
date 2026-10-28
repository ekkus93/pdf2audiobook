"""Skipped citations never reach the voice, and chunking still aligns with the source (C2)."""

from pathlib import Path

import numpy as np
import pytest

from pdf2audiobook.audio import (
    chunk_source_ranges,
    split_sentences,
    synthesize_chunks,
    unspeakable_pause_ranges,
)
from pdf2audiobook.audio.citations import mask_citations
from pdf2audiobook.errors import AudioError


def _chunks(text: str) -> list[str]:
    return split_sentences(mask_citations(text))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The model shown in [13] works well.", ["The model shown in works well."]),
        ("We use attention [38].", ["We use attention."]),
        ("[13] showed that it works.", ["showed that it works."]),
        ("It is known [35, 2, 5], and so on.", ["It is known, and so on."]),
        ("shown in [35,\n2] before now.", ["shown in before now."]),
        ("First sentence.\n\n[13]\n\nSecond sentence.", ["First sentence.", "Second sentence."]),
        ("(see also [13]) for details.", ["(see also) for details."]),
        ("Two [1] citations [2, 3] here.", ["Two citations here."]),
        ("Code a[1] and x[i] stay.", ["Code a[1] and x[i] stay."]),
    ],
)
def test_citations_are_absent_from_the_spoken_chunks(text: str, expected: list[str]) -> None:
    assert _chunks(text) == expected


def test_with_the_setting_off_chunks_are_exactly_what_they_were() -> None:
    text = "The model shown in [13] works well.\n\nSee [35, 2, 5]."
    assert split_sentences(text) == ["The model shown in [13] works well.", "See [35, 2, 5]."]


def test_a_paragraph_of_a_citation_and_punctuation_becomes_a_pause() -> None:
    text = "First sentence.\n\n[13].\n\nSecond sentence."
    start = text.index("[13]")
    assert unspeakable_pause_ranges(text, skip_citations=True) == [(start, start + 5)]
    assert unspeakable_pause_ranges(text) == []  # read literally it is speakable digits


def test_a_paragraph_of_only_a_citation_contributes_nothing() -> None:
    text = "First sentence.\n\n[13]\n\nSecond sentence."
    assert unspeakable_pause_ranges(text, skip_citations=True) == []
    assert _chunks(text) == ["First sentence.", "Second sentence."]


@pytest.mark.parametrize(
    "text",
    [
        "The model shown in [13] works well. It is known [35, 2, 5], and so on.",
        "[1] opens the paragraph.\n\nThen a second [2-4] one ends [7].",
        "split [35,\n2] across lines, then (see [8]) close.",
    ],
)
def test_chunks_still_align_to_the_original_source(text: str) -> None:
    masked = mask_citations(text)
    assert len(masked) == len(text)
    chunks = split_sentences(masked)
    ranges = chunk_source_ranges(masked, chunks)
    assert len(ranges) == len(chunks)
    for chunk, (start, end, _boundary) in zip(chunks, ranges, strict=True):
        assert text[start:].startswith(chunk.split()[0])
        assert 0 <= start < end <= len(text)


class RecordingProvider:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        self.calls.append((text, voice))
        return np.ones(240, dtype=np.float32) * 0.1


def _synthesize(tmp_path: Path, text: str, **kwargs) -> RecordingProvider:
    provider = RecordingProvider()
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    synthesize_chunks(
        text, provider, model="m", voice="Jasper", speed=1.0, pause_ms=0, cache=cache, **kwargs
    )
    return provider


def test_the_voice_never_receives_a_citation_when_skipping(tmp_path: Path) -> None:
    text = "Attention is useful [13]. It also scales [35, 2, 5]."
    provider = _synthesize(tmp_path, text, skip_citations=True)
    spoken = " ".join(call[0] for call in provider.calls)
    assert spoken == "Attention is useful. It also scales."
    assert "[" not in spoken and "13" not in spoken


def test_the_voice_receives_citations_unchanged_when_not_skipping(tmp_path: Path) -> None:
    text = "Attention is useful [13]. It also scales [35, 2, 5]."
    provider = _synthesize(tmp_path, text)
    assert " ".join(call[0] for call in provider.calls) == text


def test_voice_markers_and_citations_work_together(tmp_path: Path) -> None:
    text = "[[voice:Bella]]\n\nSpoken [4] words.\n"
    provider = _synthesize(tmp_path, text, skip_citations=True)
    assert provider.calls == [("Spoken words.", "Bella")]


def test_a_bibliography_entry_number_is_not_spoken_and_alignment_holds() -> None:
    text = "[1] Jimmy Ba. Layer normalization.\n\n[2] Dzmitry Bahdanau. Neural translation."
    masked = mask_citations(text)
    chunks = split_sentences(masked)
    assert chunks == [
        "Jimmy Ba. Layer normalization.",
        "Dzmitry Bahdanau. Neural translation.",
    ]
    for chunk, (start, end, _) in zip(chunks, chunk_source_ranges(masked, chunks), strict=True):
        assert text[start:end].startswith(chunk.split()[0])


def test_text_of_only_citations_has_nothing_to_speak(tmp_path: Path) -> None:
    with pytest.raises(AudioError, match="no speakable text"):
        _synthesize(tmp_path, "[1] [2]\n", skip_citations=True)
