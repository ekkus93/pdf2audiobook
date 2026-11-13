"""TOC entries and chapter boundaries require exact source anchors."""

import json

import fitz
import pytest

from pdf2audiobook.config import LLM, Chapters, General, Pdf, Settings
from pdf2audiobook.llm import propose_llm_contents_boundaries
from pdf2audiobook.models import DocumentBlock
from pdf2audiobook.pipeline import analyze_book


class Stub:
    def __init__(self, response):
        self.response = response

    def complete_json(self, *, instructions, document_text):
        assert "untrusted data" in instructions
        return self.response


def source_blocks():
    return [
        DocumentBlock(id="contents", page_index=0, text="Contents"),
        DocumentBlock(id="entry", page_index=0, text="Chapter Two ........ 9"),
        DocumentBlock(id="body", page_index=2, text="Chapter Two"),
        DocumentBlock(id="paragraph", page_index=2, text="A real chapter starts here."),
    ]


def test_verified_contents_entry_maps_to_unique_later_heading():
    decisions = []
    ids, warnings = propose_llm_contents_boundaries(
        source_blocks(),
        Stub(
            {
                "entries": [
                    {
                        "block_id": "entry",
                        "title": "Chapter Two",
                        "page_reference": "9",
                        "confidence": 0.95,
                    }
                ],
                "boundaries": [],
            }
        ),
        decisions=decisions,
    )
    assert ids == {"body"}
    assert warnings == []
    assert decisions[0].task == "contents"
    assert decisions[0].status == "accepted"
    assert decisions[0].reason_code == "verified_contents_entry"
    assert decisions[0].source_sha256


def test_verified_boundary_candidates_are_weak_heading_evidence():
    decisions = []
    ids, warnings = propose_llm_contents_boundaries(
        source_blocks(),
        Stub(
            {
                "entries": [],
                "boundaries": [{"block_id": "body", "title": "Chapter Two", "confidence": 0.9}],
            }
        ),
        decisions=decisions,
    )
    assert ids == {"body"}
    assert warnings == []
    assert decisions[0].reason_code == "verified_boundary_candidate"


def test_unknown_ids_and_invented_text_are_rejected():
    decisions = []
    ids, warnings = propose_llm_contents_boundaries(
        source_blocks(),
        Stub(
            {
                "entries": [
                    {
                        "block_id": "PRIVATE_UNKNOWN_ID",
                        "title": "Chapter Two",
                        "page_reference": "9",
                        "confidence": 0.99,
                    },
                    {
                        "block_id": "entry",
                        "title": "Invented Title",
                        "page_reference": "9",
                        "confidence": 0.99,
                    },
                ],
                "boundaries": [
                    {"block_id": "body", "title": "Invented Title", "confidence": 0.99},
                    {
                        "block_id": "PRIVATE_MISSING_ID",
                        "title": "Missing",
                        "confidence": 0.99,
                    },
                ],
            }
        ),
        decisions=decisions,
    )
    assert ids == set()
    for private in ("Invented", "PRIVATE_UNKNOWN_ID", "PRIVATE_MISSING_ID"):
        assert all(private not in warning for warning in warnings)
    assert {decision.status for decision in decisions} == {"rejected"}
    assert {decision.reason_code for decision in decisions} == {
        "unknown_or_duplicate_contents_block",
        "contents_title_mismatch",
        "boundary_text_mismatch",
        "unknown_or_duplicate_boundary_block",
    }
    assert all("Invented" not in decision.model_dump_json() for decision in decisions)


def test_out_of_window_boundary_is_rejected_and_recorded():
    decisions = []

    class FirstWindowStub:
        calls = 0

        def complete_json(self, *, instructions, document_text):
            self.calls += 1
            if self.calls == 1:
                return {
                    "entries": [],
                    "boundaries": [
                        {
                            "block_id": "paragraph",
                            "title": "A real chapter starts here.",
                            "confidence": 0.99,
                        }
                    ],
                }
            return {"entries": [], "boundaries": []}

    ids, _ = propose_llm_contents_boundaries(
        source_blocks(),
        FirstWindowStub(),
        window_size=1,
        decisions=decisions,
    )
    assert ids == set()
    assert any(item.reason_code == "unknown_or_duplicate_boundary_block" for item in decisions)


def test_context_only_lookback_and_sentence_proposals_are_rejected():
    calls = 0

    class LookbackStub:
        def complete_json(self, *, instructions, document_text):
            nonlocal calls
            calls += 1
            if calls == 2:
                return {
                    "entries": [],
                    "boundaries": [
                        {"block_id": "contents", "title": "Contents", "confidence": 0.99}
                    ],
                }
            return {"entries": [], "boundaries": []}

    decisions = []
    ids, _ = propose_llm_contents_boundaries(
        source_blocks(), LookbackStub(), window_size=1, decisions=decisions
    )
    assert ids == set()
    assert any(item.reason_code == "unknown_or_duplicate_boundary_block" for item in decisions)

    decisions = []
    prose = DocumentBlock(id="prose", page_index=0, text="This sentence looks like a heading.")
    ids, _ = propose_llm_contents_boundaries(
        [prose],
        Stub(
            {
                "entries": [],
                "boundaries": [{"block_id": "prose", "title": prose.text, "confidence": 0.99}],
            }
        ),
        decisions=decisions,
    )
    assert ids == set()
    assert decisions[-1].reason_code == "boundary_not_heading_like"


def test_contents_task_runs_independently_and_writes_report(tmp_path, monkeypatch):
    class ContentsOnlyStub:
        calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def complete_json(self, *, instructions, document_text):
            self.calls += 1
            return {"entries": [], "boundaries": []}

    stub = ContentsOnlyStub()
    monkeypatch.setattr("pdf2audiobook.pipeline.create_provider", lambda _settings: stub)
    source = tmp_path / "contents-task.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((60, 80), "Ordinary prose for an isolated contents task.")
    doc.save(source)
    doc.close()
    settings = Settings(
        general=General(output_dir=str(tmp_path / "out")),
        pdf=Pdf(ocr="never"),
        chapters=Chapters(allow_single_chapter=True),
        llm=LLM(
            enabled=True,
            structure=False,
            contents=True,
            cleanup=False,
            classification=False,
            narration=False,
        ),
    )

    manifest_path = analyze_book(source, settings)
    report = json.loads((manifest_path.parent / "reports" / "llm_decisions.json").read_text())

    assert stub.calls == 1
    assert report["decisions"]
    assert {decision["task"] for decision in report["decisions"]} == {"contents"}


def test_contents_toggle_changes_analysis_fingerprint():
    from pdf2audiobook.pipeline import _analysis_stage_fingerprints

    settings = Settings()
    enabled = settings.model_copy(deep=True)
    enabled.llm.contents = True
    assert (
        _analysis_stage_fingerprints("book", settings, None)["llm-analysis"]
        != (_analysis_stage_fingerprints("book", enabled, None)["llm-analysis"])
    )


# --- Rejections (test coverage round 2, U4) ------------------------------------


def _entry(block_id="entry", title="Chapter Two", page="9", confidence=0.95):
    return {"block_id": block_id, "title": title, "page_reference": page, "confidence": confidence}


def _contents(entries=(), boundaries=(), blocks=None):
    decisions = []
    ids, warnings = propose_llm_contents_boundaries(
        blocks or source_blocks(),
        Stub({"entries": list(entries), "boundaries": list(boundaries)}),
        decisions=decisions,
    )
    return ids, warnings, decisions


def _codes(decisions):
    return [(item.block_id, item.status, item.reason_code) for item in decisions]


def test_contents_line_without_a_page_number_is_rejected():
    """U4.a: a line that doesn't end in a page number can't be a contents entry."""
    blocks = source_blocks()
    blocks[1] = DocumentBlock(id="entry", page_index=0, text="Chapter Two")

    ids, warnings, decisions = _contents([_entry()], blocks=blocks)

    assert ids == set()
    assert _codes(decisions) == [("entry", "rejected", "contents_title_mismatch")]
    assert warnings == ["LLM contents entry did not match its source line"]


def test_contents_line_that_is_only_a_page_number_is_rejected():
    """U4.a: leaders with no title before the number don't make an entry."""
    blocks = source_blocks()
    blocks[1] = DocumentBlock(id="entry", page_index=0, text="........ 9")

    ids, _, decisions = _contents([_entry()], blocks=blocks)

    assert ids == set()
    assert _codes(decisions) == [("entry", "rejected", "contents_title_mismatch")]


def test_contents_entry_with_a_different_page_is_rejected():
    """U4.a: the page the model reports must be the page printed on the line."""
    ids, warnings, decisions = _contents([_entry(page="19")])

    assert ids == set()
    assert _codes(decisions) == [("entry", "rejected", "contents_page_reference_mismatch")]
    assert warnings == ["LLM contents page reference did not match its source line"]


@pytest.mark.parametrize(("confidence", "accepted"), [(0.74, False), (0.75, True)])
def test_contents_entry_needs_confidence_of_at_least_three_quarters(confidence, accepted):
    """U4.a: a verified line with low confidence is rejected without a warning."""
    ids, warnings, decisions = _contents([_entry(confidence=confidence)])

    assert ids == ({"body"} if accepted else set())
    assert warnings == []
    expected = "verified_contents_entry" if accepted else "low_confidence"
    assert _codes(decisions) == [("entry", "accepted" if accepted else "rejected", expected)]


@pytest.mark.parametrize(("confidence", "accepted"), [(0.74, False), (0.75, True)])
def test_boundary_needs_confidence_of_at_least_three_quarters(confidence, accepted):
    """U4.b: a heading-like boundary with low confidence adds no evidence."""
    boundary = {"block_id": "body", "title": "Chapter Two", "confidence": confidence}

    ids, warnings, decisions = _contents(boundaries=[boundary])

    assert ids == ({"body"} if accepted else set())
    assert warnings == []
    expected = "verified_boundary_candidate" if accepted else "low_confidence"
    assert _codes(decisions) == [("body", "accepted" if accepted else "rejected", expected)]


class _Script:
    """Return one scripted answer per window, recording what each window held."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.snippets = []

    def complete_json(self, *, instructions, document_text):
        self.snippets.append(document_text)
        return self.answers.pop(0)


def test_oversized_block_window_is_skipped_and_the_next_window_runs():
    """U4.c: a block too large for any window is recorded; later windows still run."""
    blocks = [
        DocumentBlock(id="huge", page_index=0, text="x" * 5000),
        DocumentBlock(id="body", page_index=1, text="Chapter Two"),
    ]
    provider = _Script(
        {
            "entries": [],
            "boundaries": [{"block_id": "body", "title": "Chapter Two", "confidence": 0.9}],
        }
    )
    decisions = []

    ids, warnings = propose_llm_contents_boundaries(
        blocks, provider, window_size=1, chunk_tokens=400, decisions=decisions
    )

    assert ids == {"body"}
    assert ("window:0", "rejected", "oversized_source_block") in _codes(decisions)
    assert warnings == ["LLM contents analysis skipped oversized block at index 0"]
    assert len(provider.snippets) == 1
    assert "x" * 100 not in provider.snippets[0]


@pytest.mark.parametrize(
    "answer",
    [
        {"entries": "none"},
        {"entries": [], "boundaries": [], "extra": 1},
        {"entries": [{"block_id": "entry"}], "boundaries": []},
        ["not", "an", "object"],
    ],
    ids=["entries-not-a-list", "extra-key", "entry-missing-fields", "not-an-object"],
)
def test_schema_invalid_answer_is_recorded_and_the_next_window_runs(answer):
    """U4.c: an answer that fails the schema is recorded against its window."""
    provider = _Script(
        answer,
        {
            "entries": [],
            "boundaries": [{"block_id": "body", "title": "Chapter Two", "confidence": 0.9}],
        },
    )
    decisions = []

    ids, warnings = propose_llm_contents_boundaries(
        source_blocks(), provider, window_size=2, decisions=decisions
    )

    assert ids == {"body"}
    assert _codes(decisions)[0] == ("window:0", "rejected", "invalid_response_schema")
    assert warnings == ["LLM contents response rejected at block window 0"]
    assert len(provider.snippets) == 2


@pytest.mark.parametrize(("confidence", "approved"), [(0.74, False), (0.75, True)])
def test_low_confidence_heading_is_not_approved(confidence, approved):
    """U4.d: a heading that names its line still needs confidence of at least 0.75."""
    from pdf2audiobook.llm import detect_llm_headings

    decisions = []
    ids, warnings = detect_llm_headings(
        source_blocks(),
        _Script(
            {"headings": [{"block_id": "body", "title": "Chapter Two", "confidence": confidence}]}
        ),
        decisions=decisions,
    )

    assert ids == ({"body"} if approved else set())
    assert warnings == []
    assert [(d.block_id, d.status, d.reason_code) for d in decisions] == [
        (
            "body",
            "accepted" if approved else "rejected",
            "verified_heading" if approved else "low_confidence",
        )
    ]
