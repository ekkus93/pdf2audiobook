"""Equation candidates are chosen by a deterministic test, never by the LLM (C3)."""

import pytest

from pdf2audiobook.llm.equations import (
    MAX_EQUATION_CANDIDATES,
    equation_candidates,
    looks_mathematical,
)
from pdf2audiobook.models import DocumentBlock


def _block(i: int, text: str, kind: str = "paragraph") -> DocumentBlock:
    return DocumentBlock(id=f"b{i}", page_index=0, text=text, kind=kind)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text",
    [
        "Attention(Q, K, V ) = softmax(QKT √dk )V",
        "lrate = d−0.5",
        "√dk",
        "PE(pos,2i) = sin(pos/100002i/dmodel)",
        "x ≤ y",
        "α = 0.5",
        "E = mc^2",
        "h = 8",
        "∑ i=1 to n",
        "f(x) = x + 1",
        "p ∈ S",
        "β1 = 0.9 and β2 = 0.98",
        "a ± b",
    ],
)
def test_mathematical_notation_is_a_candidate(text: str) -> None:
    assert looks_mathematical(text)


@pytest.mark.parametrize(
    "text",
    [
        "In 2017 the model scored 28.4 BLEU on the test set.",
        "1. Introduction",
        "Table 2: Results of the experiments",
        "(see Figure 3)",
        "Each layer(s) has two sub-layers.",
        "3) the third item in a list",
        "Published in 2017.",
        "an e-mail address",
        "a well-known result",
        "See https://example.com/page?a=1&b=2 for details.",
        "Ordinary prose that mentions the word equals but has no symbols.",
        "",
    ],
)
def test_ordinary_prose_is_not_a_candidate(text: str) -> None:
    assert not looks_mathematical(text)


def test_equation_kind_blocks_are_always_candidates() -> None:
    candidates, capped = equation_candidates([_block(0, "just words", kind="equation")])
    assert [b.id for b in candidates] == ["b0"] and not capped


def test_candidates_keep_document_order_and_skip_headings_and_omitted_blocks() -> None:
    blocks = [
        _block(0, "x = 1"),
        _block(1, "Ordinary prose."),
        _block(2, "3 Model = Architecture", kind="heading"),
        _block(3, "y ≥ 2"),
        _block(4, "z = 3"),
    ]
    candidates, capped = equation_candidates(blocks, omitted={"b4"})
    assert [b.id for b in candidates] == ["b0", "b3"] and not capped


def test_the_candidate_cap_is_applied_and_reported() -> None:
    blocks = [_block(i, f"x{i} = {i}") for i in range(MAX_EQUATION_CANDIDATES + 25)]
    candidates, capped = equation_candidates(blocks)
    assert len(candidates) == MAX_EQUATION_CANDIDATES and capped
    assert [b.id for b in candidates] == [f"b{i}" for i in range(MAX_EQUATION_CANDIDATES)]
