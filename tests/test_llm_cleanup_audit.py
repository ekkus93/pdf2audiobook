"""Source-linked LLM cleanup verifier audit never auto-approves or logs prose."""

import hashlib

from pdf2audiobook.llm import propose_llm_cleanup
from pdf2audiobook.models import DocumentBlock


class Stub:
    def __init__(self, edits):
        self.edits = edits

    def complete_json(self, *, instructions, document_text):
        return {"edits": self.edits}


def item(block_id, original, replacement, confidence=0.99):
    return {
        "block_id": block_id,
        "original": original,
        "replacement": replacement,
        "reason": "fix OCR",
        "confidence": confidence,
    }


def test_audit_marks_verified_proposal_accepted_for_manual_review():
    source = DocumentBlock(id="p1", page_index=0, text="A rnisspelled word.")
    decisions = []
    edits, warnings = propose_llm_cleanup(
        [source],
        Stub([item("p1", source.text, "A misspelled word.")]),
        decisions=decisions,
    )
    assert not warnings
    assert len(edits) == 1 and not edits[0].accepted
    assert len(decisions) == 1
    record = decisions[0]
    assert record.status == "accepted"
    assert record.task == "cleanup"
    assert record.proposal_summary == "cleanup proposal"
    assert record.reason_code == "verified_proposal"
    assert record.source_sha256 == hashlib.sha256(source.text.encode()).hexdigest()
    assert source.text not in record.model_dump_json()
    assert record.requires_manual_review


def test_audit_records_rejection_reason_without_accepting_hallucinations():
    source = DocumentBlock(id="p1", page_index=0, text="Real source statement.")
    scenarios = [
        (
            item("unknown", "Real source statement.", "Changed statement."),
            "unknown_or_duplicate_block",
        ),
        (item("p1", "fabricated", "Changed statement."), "source_text_mismatch"),
        (item("p1", source.text, ""), "proposed_deletion"),
        (item("p1", source.text, "Entirely unrelated invented paragraphs."), "excessive_change"),
        (item("p1", source.text, "Real source staternent.", 0.1), "low_confidence"),
    ]
    for proposal, expected in scenarios:
        decisions = []
        edits, _ = propose_llm_cleanup(
            [source],
            Stub([proposal]),
            decisions=decisions,
        )
        assert not edits
        assert decisions and decisions[0].status == "rejected"
        assert decisions[0].reason_code == expected


def test_invalid_schema_rejects_opaque_window_without_source_text():
    source = DocumentBlock(id="p1", page_index=0, text="Private chapter text.")
    decisions = []
    edits, _ = propose_llm_cleanup(
        [source],
        Stub([{"invalid": "payload"}]),
        decisions=decisions,
    )
    assert not edits
    assert decisions[0].reason_code == "invalid_response_schema"
    assert decisions[0].source_sha256 is None
