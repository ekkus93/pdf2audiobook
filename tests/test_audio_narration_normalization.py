"""Spoken-text normalization and scene-break handling preserve source spans."""

import json

import numpy as np
import pytest

from pdf2audiobook.audio import (
    _NARRATION_TRANSLATION,
    NARRATION_NORMALIZATION_VERSION,
    chunk_source_ranges,
    normalize_narration_text,
    split_sentences,
    synthesize_chunks,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [(chr(codepoint), target) for codepoint, target in _NARRATION_TRANSLATION.items()],
)
def test_each_narration_normalization_table_entry(source, expected):
    original = f"A{source}B"
    normalized = normalize_narration_text(original)
    assert normalized == f"A{expected}B"
    assert original == f"A{source}B"


def test_normalized_chunks_keep_original_source_ranges_and_text():
    source = "“ﬁrst” line—next…\n\nsoft\u00adhyphen\u200b end\u00a0here."
    before = source
    chunks = split_sentences(source)
    ranges = chunk_source_ranges(source, chunks)
    assert chunks == ['"first" line,next...', "softhyphen end here."]
    assert ranges[0][0] == 0
    assert ranges[1][2] is True
    assert source == before
    assert NARRATION_NORMALIZATION_VERSION == "narration-normalization-v1"


def test_punctuated_pronunciation_keys_match_whole_tokens():
    source = "Dr. U.S., (C++) Hermione."
    pronunciations = {
        "dr.": "Doctor",
        "u.s.": "United",
        "c++": "seeplus",
        "hermione.": "Her-my-oh-nee",
    }
    chunks = split_sentences(source, pronunciations=pronunciations)
    assert chunks == ["Doctor. UNITED, (SEEPLUS) Her-my-oh-nee."]
    assert chunk_source_ranges(source, chunks, pronunciations=pronunciations)


class RecordingProvider:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def __init__(self):
        self.calls = []

    def generate(self, text, *, voice, speed):
        self.calls.append(text)
        return np.full(24, 0.1, dtype=np.float32)


def test_scene_break_creates_pause_without_tts_call(tmp_path):
    source = "Before sentence.\n\n* * *\n\nAfter sentence."
    provider = RecordingProvider()
    progress_path = tmp_path / "progress.json"
    samples = synthesize_chunks(
        source,
        provider,
        model="stub",
        voice="voice",
        speed=1,
        pause_ms=250,
        cache=tmp_path / "cache",
        progress_file=progress_path,
    )
    progress = json.loads(progress_path.read_text())
    assert provider.calls == ["Before sentence.", "After sentence."]
    assert progress["chunks"][1]["paragraph_boundary_before"] is True
    assert samples.size == 2 * 24 + 2 * (24000 // 4)
