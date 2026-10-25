"""Each LLM task records accepted and rejected verifier outcomes without prose."""

import json

import pytest

from pdf2audiobook.llm import (
    detect_llm_headings,
    propose_llm_classification,
    propose_llm_cleanup,
    propose_llm_narration,
)
from pdf2audiobook.models import DocumentBlock


class Response:
    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, *, instructions, document_text):
        return self.payload


@pytest.mark.parametrize(
    ("task", "run", "payload"),
    [
        (
            "heading",
            detect_llm_headings,
            {
                "headings": [
                    {"block_id": "p1", "title": "PRIVATE_CHAPTER", "confidence": 0.95},
                    {"block_id": "p2", "title": "Invented title", "confidence": 0.99},
                ]
            },
        ),
        (
            "cleanup",
            propose_llm_cleanup,
            {
                "edits": [
                    {
                        "block_id": "p1",
                        "original": "PRIVATE rnisspelled word.",
                        "replacement": "PRIVATE misspelled word.",
                        "reason": "OCR correction",
                        "confidence": 0.99,
                    },
                    {
                        "block_id": "unknown",
                        "original": "PRIVATE rnisspelled word.",
                        "replacement": "PRIVATE misspelled word.",
                        "reason": "OCR correction",
                        "confidence": 0.99,
                    },
                ]
            },
        ),
        (
            "classification",
            propose_llm_classification,
            {
                "labels": [
                    {
                        "block_id": "p1",
                        "category": "footnote",
                        "confidence": 0.99,
                        "reason": "layout",
                    },
                    {
                        "block_id": "unknown",
                        "category": "caption",
                        "confidence": 0.99,
                        "reason": "layout",
                    },
                ]
            },
        ),
        (
            "narration",
            propose_llm_narration,
            {
                "suggestions": [
                    {
                        "block_id": "p1",
                        "original": "PRIVATE Dr Smith arrived.",
                        "spoken": "PRIVATE Doctor Smith arrived.",
                        "reason": "pronunciation",
                        "confidence": 0.99,
                    },
                    {
                        "block_id": "unknown",
                        "original": "PRIVATE Dr Smith arrived.",
                        "spoken": "PRIVATE Doctor Smith arrived.",
                        "reason": "pronunciation",
                        "confidence": 0.99,
                    },
                ]
            },
        ),
    ],
)
def test_task_records_accepted_and_rejected_decisions_without_source_text(task, run, payload):
    source_text = "PRIVATE rnisspelled word." if task == "cleanup" else "PRIVATE Dr Smith arrived."
    if task == "heading":
        source_text = "PRIVATE_CHAPTER"
        blocks = [
            DocumentBlock(id="p1", page_index=0, text=source_text),
            DocumentBlock(id="p2", page_index=0, text="PRIVATE body prose."),
        ]
    else:
        blocks = [DocumentBlock(id="p1", page_index=0, text=source_text)]
    decisions = []

    run(blocks, Response(payload), decisions=decisions)

    assert {item.task for item in decisions} == {task}
    assert {item.status for item in decisions} == {"accepted", "rejected"}
    serialized = json.dumps([item.model_dump() for item in decisions])
    assert "PRIVATE" not in serialized
    assert "rnisspelled" not in serialized
