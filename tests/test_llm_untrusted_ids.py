"""Untrusted LLM-provided IDs must not enter persisted review diagnostics."""

import pytest

from pdf2audiobook.llm import (
    detect_llm_headings,
    propose_llm_classification,
    propose_llm_cleanup,
    propose_llm_narration,
)
from pdf2audiobook.models import DocumentBlock


@pytest.mark.parametrize("kind", ["headings", "edits", "labels", "suggestions"])
def test_unknown_model_identifier_is_not_reflected_in_warnings_or_audit(kind):
    marker = "PRIVATE_MODEL_ECHO_SHOULD_NOT_APPEAR"
    forged = marker + " " + ("sensitive " * 40)
    block = DocumentBlock(id="b1", page_index=0, text="Chapter One.")

    class ForgedResponse:
        def complete_json(self, *, instructions, document_text):
            if kind == "headings":
                item = {"block_id": forged, "title": block.text, "confidence": 0.99}
            elif kind == "edits":
                item = {
                    "block_id": forged, "original": block.text,
                    "replacement": "A different chapter.", "confidence": 0.99,
                    "reason": "OCR correction",
                }
            elif kind == "labels":
                item = {
                    "block_id": forged, "category": "heading",
                    "confidence": 0.99, "reason": "layout evidence",
                }
            else:
                item = {
                    "block_id": forged, "original": block.text,
                    "spoken": "Chapter one.", "confidence": 0.99,
                    "reason": "pronunciation guidance",
                }
            return {kind: [item]}

    decisions = []
    provider = ForgedResponse()
    if kind == "headings":
        result, warnings = detect_llm_headings([block], provider)
    elif kind == "edits":
        result, warnings = propose_llm_cleanup(
            [block], provider, decisions=decisions,
        )
    elif kind == "labels":
        result, warnings = propose_llm_classification([block], provider)
    else:
        result, warnings = propose_llm_narration([block], provider)
    assert not result
    assert len(warnings) == 1
    assert "unrecognized" in warnings[0]
    assert marker not in warnings[0]
    if kind == "edits":
        assert len(decisions) == 1
        assert decisions[0].block_id == "<unrecognized>"
        assert decisions[0].reason_code == "unknown_or_duplicate_block"
