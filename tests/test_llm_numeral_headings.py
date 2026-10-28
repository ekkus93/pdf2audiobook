"""An LLM that names a numeral chapter opening "Chapter N" is correct, not a mismatch (E3)."""

from typing import Any

import pytest

from pdf2audiobook.llm.structure import detect_llm_headings
from pdf2audiobook.models import DocumentBlock


class Proposer:
    def __init__(self, title_by_id: dict[str, str]) -> None:
        self.title_by_id = title_by_id

    def complete_json(self, *, instructions: str, document_text: str) -> dict[str, Any]:
        return {
            "headings": [
                {"block_id": block_id, "title": title, "confidence": 0.9}
                for block_id, title in self.title_by_id.items()
            ]
        }


def _blocks(*texts: str) -> list[DocumentBlock]:
    return [
        DocumentBlock(id=f"b{i}", page_index=i, text=text, kind="paragraph")
        for i, text in enumerate(texts)
    ]


def _run(texts: list[str], titles: dict[str, str]):
    decisions: list = []
    ids, warnings = detect_llm_headings(
        _blocks(*texts), Proposer(titles), chunk_tokens=4000, decisions=decisions
    )
    return ids, warnings, decisions


@pytest.mark.parametrize(
    ("source", "title"),
    [
        ("2", "Chapter 2"),
        ("2.", "Chapter 2"),
        ("XII", "Chapter 12"),
        ("12", "Chapter XII"),
        ("12", "CHAPTER TWELVE"),
        ("3", "Part 3"),
    ],
)
def test_a_label_for_the_numeral_on_the_line_is_accepted(source: str, title: str) -> None:
    ids, warnings, decisions = _run([source, "Opening prose."], {"b0": title})
    assert ids == {"b0"} and warnings == []
    assert [d.reason_code for d in decisions if d.status == "accepted"] == ["verified_heading"]


@pytest.mark.parametrize(
    ("source", "title"),
    [
        ("2", "Chapter 3"),  # wrong number
        ("2", "The Beginning"),  # prose for a numeral
        ("Some prose line", "Chapter 2"),  # label for a non-numeral line
        ("2", "Chapter"),  # no number at all
        ("1234", "Chapter 1234"),  # not a chapter numeral
        ("xii", "Chapter 12"),  # lower-case roman is not a numeral line
    ],
)
def test_any_other_mismatch_is_still_rejected(source: str, title: str) -> None:
    ids, warnings, decisions = _run([source, "Opening prose."], {"b0": title})
    assert ids == set()
    assert warnings == ["LLM heading text mismatched source: b0"]
    assert [d.reason_code for d in decisions if d.status == "rejected"] == ["source_text_mismatch"]


def test_exact_matches_behave_as_before() -> None:
    ids, warnings, _ = _run(["Prologue", "Opening prose."], {"b0": "prologue"})
    assert ids == {"b0"} and warnings == []


def test_the_source_text_is_never_changed_and_warnings_hold_no_text() -> None:
    blocks = _blocks("2", "Opening prose.")
    detect_llm_headings(blocks, Proposer({"b0": "Chapter 2"}), chunk_tokens=4000, decisions=[])
    assert blocks[0].text == "2"
    _ids, warnings, _decisions = _run(["Secret prose", "x"], {"b0": "Chapter 2 Secret"})
    assert all("Secret" not in warning for warning in warnings)
