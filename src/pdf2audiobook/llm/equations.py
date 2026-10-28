"""Spoken readings of mathematical notation, proposed by the model and never auto-applied.

Candidates are chosen deterministically. Every proposal is verified against its source
block and stored as a pending edit that only a person can accept.
"""

from __future__ import annotations

import re
from collections.abc import Collection

from pdf2audiobook.models import DocumentBlock

MAX_EQUATION_CANDIDATES = 500

_MATH_SYMBOLS = frozenset("=+−×÷√∑∏∫≤≥≠≈∈∞±∂∇^")
_GREEK = re.compile("[Ͱ-Ͽ]")
# A function-call form is only mathematical when it is being defined: "f(x) = ...".
_CALL_EQUALS = re.compile(r"\b[A-Za-z]\w*\s*\([^()]*\)\s*=")


def looks_mathematical(text: str) -> bool:
    """Whether a line contains mathematical notation, by symbols alone (no model)."""
    if "://" in text:
        return False  # URLs carry "=" and "+" without being mathematics
    return (
        any(char in _MATH_SYMBOLS for char in text)
        or _GREEK.search(text) is not None
        or _CALL_EQUALS.search(text) is not None
    )


def equation_candidates(
    blocks: list[DocumentBlock], omitted: Collection[str] = ()
) -> tuple[list[DocumentBlock], bool]:
    """Blocks to offer the model, in document order, and whether the cap cut the list."""
    candidates: list[DocumentBlock] = []
    for block in blocks:
        if block.id in omitted or block.kind == "heading":
            continue
        if block.kind == "equation" or looks_mathematical(block.text):
            if len(candidates) >= MAX_EQUATION_CANDIDATES:
                return candidates, True
            candidates.append(block)
    return candidates, False
