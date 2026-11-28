"""Cleanup and narration share one request per window when both are on (TODO F.07).

The two steps planned identical windows and asked separately, 248 of a 63-page paper's 525
requests. Now one request answers both; each half goes through exactly its own step's checks.
"""

from __future__ import annotations

import json

from pdf2audiobook.errors import LLMAnswerCutOff
from pdf2audiobook.llm import (
    propose_llm_cleanup,
    propose_llm_cleanup_and_narration,
    propose_llm_narration,
)
from pdf2audiobook.models import DocumentBlock

LINES = ["The b00k was very good.", "Dr. Smith arrived at 3 p.m.", "An ordinary line."]


def _blocks() -> list[DocumentBlock]:
    return [DocumentBlock(id=f"p{i}", page_index=0, text=text) for i, text in enumerate(LINES)]


class Shared:
    """Answers each window with an OCR fix for p0 and a spoken form for p1 when present."""

    def __init__(self, answer=None) -> None:
        self.calls: list[str] = []
        self.answer = answer

    def complete_json(self, *, instructions: str, document_text: str) -> dict:
        self.calls.append(instructions)
        if self.answer is not None:
            return self.answer(document_text)
        ids = {r["id"] for r in json.loads(document_text) if not r.get("context_only")}
        answer: dict = {"edits": [], "suggestions": []}
        if "p0" in ids:
            answer["edits"].append(
                {
                    "block_id": "p0",
                    "original": LINES[0],
                    "replacement": "The book was very good.",
                    "reason": "OCR correction",
                    "confidence": 0.98,
                }
            )
        if "p1" in ids:
            answer["suggestions"].append(
                {
                    "block_id": "p1",
                    "original": LINES[1],
                    "spoken": "Doctor Smith arrived at three p m.",
                    "reason": "abbreviations",
                    "confidence": 0.9,
                }
            )
        return answer


def test_one_request_per_window_answers_both_steps() -> None:
    provider = Shared()
    decisions: list = []
    edits, spoken, warnings = propose_llm_cleanup_and_narration(
        _blocks(), provider, window_size=1, decisions=decisions
    )
    assert len(provider.calls) == 3  # one per window, not six
    assert [(e.block_id, e.replacement, e.accepted) for e in edits] == [
        ("p0", "The book was very good.", False)
    ]
    assert [(s.block_id, s.spoken) for s in spoken] == [
        ("p1", "Doctor Smith arrived at three p m.")
    ]
    assert {(d.task, d.reason_code) for d in decisions if d.status == "accepted"} >= {
        ("cleanup", "verified_proposal"),
        ("narration", "verified_narration_suggestion"),
    }
    assert not warnings


def test_the_shared_prompt_asks_both_questions_once() -> None:
    provider = Shared()
    propose_llm_cleanup_and_narration(_blocks()[:1], provider)
    prompt = provider.calls[0]
    assert '"edits"' in prompt and '"suggestions"' in prompt
    assert "OCR or transcription corrections" in prompt
    assert "spoken-text normalization" in prompt


def test_each_half_gets_its_own_steps_checks() -> None:
    # A rewrite that is not an OCR misread, and a spoken form that deletes the line.
    def answer(_text: str) -> dict:
        return {
            "edits": [
                {
                    "block_id": "p0",
                    "original": LINES[0],
                    "replacement": "The novel was excellent.",
                    "reason": "style",
                    "confidence": 0.99,
                }
            ],
            "suggestions": [
                {
                    "block_id": "p0",
                    "original": LINES[0],
                    "spoken": "",
                    "reason": "drop",
                    "confidence": 0.99,
                }
            ],
        }

    decisions: list = []
    edits, spoken, _ = propose_llm_cleanup_and_narration(
        _blocks()[:1], Shared(answer), decisions=decisions
    )
    assert edits == [] and spoken == []
    codes = {(d.task, d.reason_code) for d in decisions}
    assert ("narration", "invalid_spoken_text_length") in codes
    assert any(task == "cleanup" and code != "verified_proposal" for task, code in codes)


def test_a_missing_half_is_no_proposals_and_an_extra_key_rejects_both() -> None:
    decisions: list = []
    propose_llm_cleanup_and_narration(
        _blocks()[:1], Shared(lambda _t: {"edits": []}), decisions=decisions
    )
    assert {(d.task, d.reason_code) for d in decisions} == {
        ("cleanup", "no_proposals"),
        ("narration", "no_proposals"),
    }
    decisions = []
    _e, _s, warnings = propose_llm_cleanup_and_narration(
        _blocks()[:1],
        Shared(lambda _t: {"edits": [], "suggestions": [], "note": "hi"}),
        decisions=decisions,
    )
    assert {(d.task, d.reason_code) for d in decisions} == {
        ("cleanup", "invalid_response_schema"),
        ("narration", "invalid_response_schema"),
    }
    assert len(warnings) == 2


def test_a_cut_off_answer_is_recorded_for_both_steps() -> None:
    def answer(text: str) -> dict:
        primary = [r["id"] for r in json.loads(text) if not r.get("context_only")]
        if "p1" in primary:
            raise LLMAnswerCutOff()
        return {"edits": [], "suggestions": []}

    decisions: list = []
    _e, _s, warnings = propose_llm_cleanup_and_narration(
        _blocks(), Shared(answer), window_size=1, decisions=decisions
    )
    cut = sorted(d.task for d in decisions if d.reason_code == "answer_cut_off")
    assert cut == ["cleanup", "narration"]
    assert any(
        w.startswith("LLM answers cut off: cleanup and narration got no answer for 1 of 3")
        for w in warnings
    )


def test_separate_steps_still_ask_their_own_question() -> None:
    def cleanup_only(_text: str) -> dict:
        return {"edits": []}

    def narration_only(_text: str) -> dict:
        return {"suggestions": []}

    cleanup, narration = Shared(cleanup_only), Shared(narration_only)
    propose_llm_cleanup(_blocks()[:1], cleanup)
    propose_llm_narration(_blocks()[:1], narration)
    assert '"suggestions"' not in cleanup.calls[0]
    assert '"edits"' not in narration.calls[0]


def test_analysis_shares_the_request_only_when_both_steps_are_on(monkeypatch, tmp_path) -> None:
    from pdf2audiobook.analysis import llm as analysis_llm
    from pdf2audiobook.analysis.state import _AnalysisState
    from pdf2audiobook.config import Settings

    used: list[str] = []

    class Services:
        def propose_llm_cleanup(self, *a, **k):
            used.append("cleanup")
            return [], []

        def propose_llm_cleanup_and_narration(self, *a, **k):
            used.append("shared")
            return [], [], []

    def narration(*a, **k):
        used.append("narration")
        return [], []

    monkeypatch.setattr(analysis_llm, "propose_llm_narration", narration)
    for cleanup_on, narration_on, expected in [
        (True, True, ["shared"]),
        (True, False, ["cleanup"]),
        (False, True, ["narration"]),
        (False, False, []),
    ]:
        used.clear()
        settings = Settings()
        settings.llm.cleanup, settings.llm.narration = cleanup_on, narration_on
        run = type("Run", (), {"settings": settings, "services": Services()})()
        state = _AnalysisState(
            edits=[], omitted=set(), footnotes=[], warnings=[], review_reasons=set()
        )
        result = analysis_llm._cleanup_and_narration(run, object(), _blocks(), state)
        assert used == expected
        assert (result is None) is (not narration_on)
