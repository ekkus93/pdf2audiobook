"""LLM cleanup proposals survive only when every change is an OCR misread."""

import pytest

from pdf2audiobook.llm import propose_llm_cleanup
from pdf2audiobook.models import DocumentBlock


class Stub:
    def __init__(self, original, replacement):
        self.edit = {
            "block_id": "p1",
            "original": original,
            "replacement": replacement,
            "reason": "OCR correction",
            "confidence": 0.98,
        }

    def complete_json(self, *, instructions, document_text):
        return {"edits": [self.edit]}


def review(original, replacement):
    decisions = []
    block = DocumentBlock(id="p1", page_index=0, text=original)
    edits, warnings = propose_llm_cleanup([block], Stub(original, replacement), decisions=decisions)
    return edits, warnings, decisions[0].reason_code


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ("The b00k was very good.", "The book was very good."),
        ("tlie ﬁsh swam inthe pond", "the fish swam in the pond"),
        ("he hade them farewell, and went his way", "he bade them farewell, and went his way"),
        ("the rnodern clerk was a cleric", "the modern clerk was a cleric"),
        ("Tbe sliip sailed for Calcutta at noon.", "The ship sailed for Calcutta at noon."),
        ("the fuch and fo forth of the age", "the such and so forth of the age"),
    ],
)
def test_glyph_confusions_stay_pending_review(original, replacement):
    edits, warnings, reason = review(original, replacement)
    assert reason == "verified_proposal" and not warnings
    assert len(edits) == 1 and not edits[0].accepted


# Real proposals a local model made on a public-domain Hearn scan, all of
# which the earlier similarity-ratio check passed.
@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        # Completing a hyphenated word duplicates text the next line holds.
        (
            "have written pleasant books about Japan, declare that Japanese chil-",
            "have written pleasant books about Japan, declare that Japanese children",
        ),
        # Typographic quotes are the author's (or printer's), not OCR noise.
        (
            "peitaro,” he said as he hade them farewell, and went his way in search",
            'peitaro," he said as he bade them farewell, and went his way in search',
        ),
        # Tense, word choice, spelling modernization, case and punctuation.
        (
            "to some little matter of house cleaning she has on hand.",
            "to some little matter of house cleaning she had on hand.",
        ),
        (
            "young Dragonette just sixteen years old—lovely enough, in very sooth,",
            "young Dragonette just sixteen years old—lovely enough, in very truth,",
        ),
        (
            "about buying his old father for two bu in the Kioto shop. That was",
            "about buying his old father for two bu in the Kyoto shop. That was",
        ),
        (
            "“But I like to be well treated. I am a badger tea-kettle.”",
            "“But I like to be well treated. I am a Badger Tea-Kettle.”",
        ),
        (
            "So the hare did as he was told; and this time he was quite cured,",
            "So the hare did as he was told; and this time he was quite cured.",
        ),
        ("in good hands.”", "in good hands."),
    ],
)
def test_rewrites_that_are_not_misreads_are_rejected(original, replacement):
    edits, warnings, reason = review(original, replacement)
    assert not edits
    assert reason == "not_ocr_correction"
    assert warnings == ["LLM cleanup change is not an OCR misread in p1"]
    assert original not in warnings[0] and replacement not in warnings[0]
