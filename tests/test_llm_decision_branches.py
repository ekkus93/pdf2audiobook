"""The LLM decision branches for an unchanged narration and a low-confidence classification
(coverage round 3, TC2 / R2).

A suggestion that changes nothing, and a classification below the confidence threshold, are
rejected and recorded. The book text must not reach the warnings or the decision records.
"""

from pdf2audiobook.llm import propose_llm_classification, propose_llm_narration
from pdf2audiobook.models import DocumentBlock


class Stub:
    def __init__(self, output):
        self.output = output

    def complete_json(self, *, instructions, document_text):
        return self.output


def _decision_text(decisions):
    return "\n".join(decision.model_dump_json() for decision in decisions)


def test_a_narration_identical_to_its_source_is_rejected_as_no_change():
    source = [DocumentBlock(id="b2", page_index=0, text="Nothing changes here.")]
    provider = Stub(
        {
            "suggestions": [
                {
                    "block_id": "b2",
                    "original": "Nothing changes here.",
                    "spoken": "Nothing changes here.",
                    "reason": "no edit needed",
                    "confidence": 0.99,
                }
            ]
        }
    )
    decisions = []

    suggestions, warnings = propose_llm_narration(source, provider, decisions=decisions)

    assert suggestions == []
    assert warnings == []  # a no-op is a quiet rejection, not a warning
    assert [(d.task, d.block_id, d.status, d.reason_code) for d in decisions] == [
        ("narration", "b2", "rejected", "no_change")
    ]
    assert source[0].text == "Nothing changes here."
    assert "Nothing changes here." not in _decision_text(decisions)


def test_a_classification_below_the_threshold_is_rejected_and_warned_about():
    source = [DocumentBlock(id="b1", page_index=0, text="Header words")]
    secret = "CONFIDENTIAL BOOK SENTENCE"
    provider = Stub(
        {
            "labels": [
                {
                    "block_id": "b1",
                    "category": "running_header",
                    "confidence": 0.5,
                    "reason": secret,
                }
            ]
        }
    )
    decisions = []

    labels, warnings = propose_llm_classification(source, provider, decisions=decisions)

    assert labels == []
    assert warnings == ["LLM classification low confidence: b1"]
    assert [(d.task, d.block_id, d.status, d.reason_code) for d in decisions] == [
        ("classification", "b1", "rejected", "low_confidence")
    ]
    assert source[0].text == "Header words"
    assert secret not in "\n".join(warnings)
    assert secret not in _decision_text(decisions)
    assert "Header words" not in "\n".join(warnings) + _decision_text(decisions)


def test_a_classification_at_the_threshold_is_kept():
    # The branch rejects strictly below 0.75; a label at exactly 0.75 is accepted.
    source = [DocumentBlock(id="b1", page_index=0, text="Header words")]
    provider = Stub(
        {
            "labels": [
                {"block_id": "b1", "category": "running_header", "confidence": 0.75, "reason": "r"}
            ]
        }
    )
    decisions = []

    labels, warnings = propose_llm_classification(source, provider, decisions=decisions)

    assert [label.block_id for label in labels] == ["b1"]
    assert warnings == []
    assert not any(d.reason_code == "low_confidence" for d in decisions)
