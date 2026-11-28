"""An answer cut off at the output cap fails its own window, not the whole analysis.

A local model asked for OCR corrections echoed every line of a research paper back as a no-op
edit, and a line full of invisible direction marks became dozens of escapes; either way one
window's answer ran past the cap and the analysis stopped. Now that window gets no proposals
(with a warning and a recorded reason) and the task carries on. A cap spent before any answer,
or a cap every window hits, still stops the run with the actionable error.
"""

from __future__ import annotations

import json

import httpx
import pytest

from pdf2audiobook.errors import LLMAnswerCutOff, LLMError
from pdf2audiobook.llm import (
    OpenAICompatibleProvider,
    detect_llm_headings,
    propose_llm_classification,
    propose_llm_cleanup,
    propose_llm_contents_boundaries,
    propose_llm_narration,
)
from pdf2audiobook.llm.advisory_common import CUT_OFF_SUMMARY, WindowAnswers
from pdf2audiobook.llm.equations import propose_llm_equation_readings
from pdf2audiobook.models import DocumentBlock

PRIVATE = "PRIVATE_SYNTHETIC_CUT_OFF_TEXT_41"


class Stub:
    """Answers each window with `empty`, except windows whose own lines include one in `cut`."""

    def __init__(self, empty: dict, cut: set[str]) -> None:
        self.empty = empty
        self.cut = cut
        self.calls = 0

    def complete_json(self, *, instructions: str, document_text: str) -> dict:
        self.calls += 1
        primary = [r["id"] for r in json.loads(document_text) if not r.get("context_only")]
        if self.cut.intersection(primary):
            raise LLMAnswerCutOff()
        return self.empty


def _blocks(texts: list[str]) -> list[DocumentBlock]:
    return [
        DocumentBlock(id=f"p{index}", page_index=0, text=text) for index, text in enumerate(texts)
    ]


PROSE = [f"Line {index} of {PRIVATE} prose." for index in range(4)]
MATH = [f"x^{index} + y^2 = z^2 where {PRIVATE}" for index in range(2, 6)]

TASKS = [
    ("cleanup", propose_llm_cleanup, {"edits": []}, PROSE),
    ("narration", propose_llm_narration, {"suggestions": []}, PROSE),
    ("classification", propose_llm_classification, {"labels": []}, PROSE),
    ("heading", detect_llm_headings, {"headings": []}, PROSE),
    ("contents", propose_llm_contents_boundaries, {"entries": [], "boundaries": []}, PROSE),
    ("equation", propose_llm_equation_readings, {"readings": []}, MATH),
]


@pytest.mark.parametrize(("task", "propose", "empty", "texts"), TASKS, ids=[t[0] for t in TASKS])
def test_a_cut_off_window_is_skipped_and_the_task_carries_on(task, propose, empty, texts) -> None:
    decisions: list = []
    stub = Stub(empty, cut={"p1"})
    _result, warnings = propose(_blocks(texts), stub, window_size=1, decisions=decisions)
    assert stub.calls == 4
    cut = [warning for warning in warnings if "cut off at the output cap" in warning]
    assert cut == [cut[0]] and "window 1" in cut[0]
    assert PRIVATE not in " ".join(warnings)
    rejected = [d for d in decisions if d.reason_code == "answer_cut_off"]
    assert [(d.block_id, d.status, d.task) for d in rejected] == [("window:1", "rejected", task)]


@pytest.mark.parametrize(("task", "propose", "empty", "texts"), TASKS, ids=[t[0] for t in TASKS])
def test_when_every_window_is_cut_off_the_error_stands(task, propose, empty, texts) -> None:
    stub = Stub(empty, cut={"p0", "p1", "p2", "p3"})
    with pytest.raises(LLMAnswerCutOff, match="raise llm.max_output_tokens") as raised:
        propose(_blocks(texts), stub, window_size=1)
    assert raised.value.error_reason == "llm_output_cap"
    assert stub.calls == 4


def test_other_llm_errors_still_stop_the_task() -> None:
    class Down:
        def complete_json(self, *, instructions: str, document_text: str) -> dict:
            raise LLMError("Could not reach the LLM", error_reason="llm_unreachable")

    with pytest.raises(LLMError, match="Could not reach"):
        propose_llm_cleanup(_blocks(PROSE), Down(), window_size=1)


def test_window_answers_count_answers_and_cut_offs() -> None:
    answers = WindowAnswers(Stub({"ok": True}, cut={"p1"}))
    assert answers.ask(instructions="x", document_text='[{"id":"p0"}]') == {"ok": True}
    assert answers.ask(instructions="x", document_text='[{"id":"p1"}]') is None
    assert (answers.answered, answers.cut_off) == (1, 1)
    answers.finish()  # one answer is enough


def _provider(content: str | None) -> OpenAICompatibleProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1024, "total_tokens": 1034},
            },
        )

    return OpenAICompatibleProvider(
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model="mock",
        allow_remote=False,
        max_retries=0,
        max_context_tokens=16384,
        transport=httpx.MockTransport(handler),
    )


def test_the_provider_tells_a_cut_off_answer_from_a_cap_spent_before_answering() -> None:
    with _provider('{"edits":[{"block_id":"p0","original":"' + PRIVATE) as provider:
        with pytest.raises(LLMAnswerCutOff) as raised:
            provider.complete_json(instructions="x", document_text="y")
    assert PRIVATE not in str(raised.value)
    with _provider("") as provider:
        with pytest.raises(LLMError) as raised:
            provider.complete_json(instructions="x", document_text="y")
    assert not isinstance(raised.value, LLMAnswerCutOff)
    assert "before any answer" in str(raised.value)


def test_the_cleanup_prompt_asks_only_for_lines_that_change() -> None:
    # The model that echoed every line as a no-op edit was answering an ambiguous prompt.
    seen: list[str] = []

    class Recording:
        def complete_json(self, *, instructions: str, document_text: str) -> dict:
            seen.append(instructions)
            return {"edits": []}

    propose_llm_cleanup(_blocks(PROSE[:1]), Recording())
    assert "leave out every line that is already right" in seen[0]
    assert '{"edits":[]}' in seen[0]


def test_a_step_with_cut_off_windows_says_how_many_and_logs_a_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pdf2audiobook import logging as app_logging

    monkeypatch.setattr(app_logging, "_CLI_ACTIVE", True)
    monkeypatch.setattr(app_logging, "_OUTPUT_MODE", "json")
    monkeypatch.setattr(app_logging, "_VERBOSE", False)
    monkeypatch.setattr(app_logging, "_EXPLICIT_LOG_LEVEL", False)
    monkeypatch.setattr(app_logging, "_QUIET", False)
    monkeypatch.setattr(app_logging, "_WARNING_CODES", [])
    _edits, warnings = propose_llm_classification(
        _blocks(PROSE), Stub({"labels": []}, cut={"p1", "p3"}), window_size=1
    )
    summary = [w for w in warnings if w.startswith(CUT_OFF_SUMMARY)]
    assert summary == [
        "LLM answers cut off: classification got no answer for 2 of 4 windows; "
        "raise llm.max_output_tokens to include them"
    ]
    assert app_logging.take_warning_codes() == ["llm_answers_cut_off"]


def test_a_step_without_cut_offs_adds_no_summary() -> None:
    _edits, warnings = propose_llm_cleanup(_blocks(PROSE), Stub({"edits": []}, cut=set()))
    assert not [w for w in warnings if w.startswith(CUT_OFF_SUMMARY)]


def test_analyze_reports_the_summary_lines_as_notices(tmp_path) -> None:
    from pdf2audiobook.cli.analyze import llm_notices
    from pdf2audiobook.models import BookManifest
    from pdf2audiobook.workspace import write_manifest

    line = (
        "LLM answers cut off: classification got no answer for 2 of 4 windows; "
        "raise llm.max_output_tokens to include them"
    )
    path = tmp_path / "manifest.json"
    write_manifest(
        path,
        BookManifest(
            schema_version=3,
            input_sha256="x",
            title="Book",
            source_path="source.pdf",
            warnings=["LLM cleanup change is not an OCR misread in p1", line],
        ),
    )
    assert llm_notices(path) == [line]
    assert llm_notices(tmp_path / "missing.json") == []


def test_the_classification_prompt_asks_only_for_blocks_that_are_not_body_text() -> None:
    # The same model labelled every line "body", and its answers outgrew the cap.
    seen: list[str] = []

    class Recording:
        def complete_json(self, *, instructions: str, document_text: str) -> dict:
            seen.append(instructions)
            return {"labels": []}

    propose_llm_classification(_blocks(PROSE[:1]), Recording())
    assert "leave out every body line" in seen[0]
    assert '{"labels":[]}' in seen[0]


@pytest.mark.parametrize(
    ("chunk", "cap", "window"),
    [
        (4000, 1024, 512),
        (4000, 2048, 1024),
        (4000, 32768, 4000),
        (4000, 100, 256),
        (400, 1024, 400),
    ],
)
def test_equation_windows_are_sized_so_their_answers_fit_the_cap(chunk, cap, window) -> None:
    # A reading repeats its record twice, so its answer is about twice the window's size.
    from pdf2audiobook.llm.equations import equation_window_bytes

    assert equation_window_bytes(chunk, cap) == window
