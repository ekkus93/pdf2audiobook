"""Source-aligned speech chunks and paragraph pause behavior."""

import hashlib
import json

import numpy as np

from pdf2audiobook.audio import chunk_source_ranges, split_sentences, synthesize_chunks


class FakeVoice:
    sample_rate = 24000

    def __init__(self):
        self.calls = []

    def generate(self, text, *, voice, speed):
        self.calls.append((text, voice))
        return np.full(2400, 0.03, dtype=np.float32)


def test_chunk_mapping_preserves_source_offsets_and_punctuation(tmp_path):
    text = ("Alpha " * 40).strip() + "!\n\n" + ("Bravo " * 40).strip() + "?"
    chunks = split_sentences(text)
    assert len(chunks) == 2
    spans = chunk_source_ranges(text, chunks)
    assert spans[0][2] is False
    assert spans[1][2] is True
    assert [text[a:b].split() for (a, b, _) in spans] == [c.split() for c in chunks]
    assert text[spans[0][1] : spans[1][0]] == "\n\n"

    ledger_path = tmp_path / "progress.json"
    audio = synthesize_chunks(
        text,
        FakeVoice(),
        model="mini",
        voice="Jasper",
        speed=1,
        pause_ms=100,
        cache=tmp_path / "wav",
        progress_file=ledger_path,
    )
    assert audio.size == 2400 * 2 + 4800  # Doubled paragraph pause.
    import json

    ledger = json.loads(ledger_path.read_text())
    assert ledger["status"] == "completed"
    for entry, (a, b, boundary) in zip(ledger["chunks"], spans, strict=True):
        assert (entry["source_start"], entry["source_end"]) == (a, b)
        assert entry["paragraph_boundary_before"] == boundary
        assert "Alpha" not in str(entry) and "Bravo" not in str(entry)


def test_short_paragraphs_stay_separate_and_soft_wrap_does_not_split():
    assert split_sentences("Short one.\n\nShort two.") == ["Short one.", "Short two."]
    assert split_sentences("This is a\nsoft wrap.") == ["This is a soft wrap."]


def test_pronunciation_dictionary_changes_speech_but_preserves_exact_source_ranges(tmp_path):
    text = "Read Māori, then say MĀORI."
    dictionary = {"māori": "mow-ree"}
    chunks = split_sentences(text, pronunciations=dictionary)

    assert chunks == ["Read Mow-ree, then say MOW-REE."]
    ranges = chunk_source_ranges(text, chunks, pronunciations=dictionary)
    assert len(ranges) == 1
    assert text[ranges[0][0] : ranges[0][1]] == text

    synthesize_chunks(
        text,
        FakeVoice(),
        model="mini",
        voice="Jasper",
        speed=1,
        pause_ms=0,
        cache=tmp_path / "wav",
        pronunciations=dictionary,
        progress_file=tmp_path / "wav" / "progress" / "test.json",
    )
    progress = json.loads(next((tmp_path / "wav" / "progress").glob("*.json")).read_text())
    assert progress["chunks"][0]["source_start"] == 0
    assert progress["chunks"][0]["source_end"] == len(text)
    assert progress["chunks"][0]["text_sha256"] != hashlib.sha256(text.encode()).hexdigest()


def test_paragraph_voice_markers_assign_subsequent_narration_and_preserve_source_offsets(tmp_path):
    text = "Narrator paragraph.\n\n[[voice:OtherVoice]]\n\nDialogue starts here."
    provider = FakeVoice()
    ledger_path = tmp_path / "progress.json"
    audio = synthesize_chunks(
        text,
        provider,
        model="mini",
        voice="DefaultVoice",
        speed=1,
        pause_ms=0,
        cache=tmp_path / "wav",
        progress_file=ledger_path,
    )

    assert audio.size == 4800
    assert provider.calls == [
        ("Narrator paragraph.", "DefaultVoice"),
        ("Dialogue starts here.", "OtherVoice"),
    ]
    ledger = json.loads(ledger_path.read_text())
    dialogue_range = ledger["chunks"][1]
    start = text.index("Dialogue starts here.")
    assert (dialogue_range["source_start"], dialogue_range["source_end"]) == (
        start,
        start + len("Dialogue starts here."),
    )


def test_paragraph_voice_marker_requires_blank_line_boundaries(tmp_path):
    import pytest

    from pdf2audiobook.errors import AudioError

    with pytest.raises(AudioError, match="new paragraph"):
        synthesize_chunks(
            "Narrator.\n[[voice:OtherVoice]]\nDialogue.",
            FakeVoice(),
            model="mini",
            voice="DefaultVoice",
            speed=1,
            pause_ms=0,
            cache=tmp_path / "wav",
        )
