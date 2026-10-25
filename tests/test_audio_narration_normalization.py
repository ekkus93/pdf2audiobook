"""Spoken-text normalization and scene-break handling preserve source spans."""

import json

import numpy as np
import pytest

from pdf2audiobook.audio import (
    _NARRATION_TRANSLATION,
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


def test_case_transfer_only_applies_to_alphabetic_pronunciation_keys():
    assert split_sentences("C++", pronunciations={"c++": "seeplus"}) == ["seeplus"]


def test_bom_and_zero_width_characters_do_not_split_alignment_tokens():
    source = "\ufeffsoft\u200bware and hy\u00adphen."
    chunks = split_sentences(source)
    assert chunks == ["software and hyphen."]
    assert chunk_source_ranges(source, chunks)


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
    assert progress["pause_count"] == 1
    assert [item["kind"] for item in progress["mapping"]].count("pause") == 1
    assert samples.size == 2 * 24 + 2 * (24000 // 4)
