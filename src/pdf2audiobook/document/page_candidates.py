"""Page-number candidates: the records kept for each numeral and the rules that accept or reject one."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from pdf2audiobook.document.page_geometry import _continuous_with_body, _PageGeometry, _valid_bbox
from pdf2audiobook.document.page_numbers import PAGE_NUMBER, _number_value, _running_parts
from pdf2audiobook.models import DocumentBlock

_Series = tuple[str, int, str]


_NumberedEntry = tuple[int, int, tuple[float, float] | None, str]


_PROSE_OPENERS = ('"', "'", "“", "‘", "«", "‹", "„", "‚", "「", "『", "《", "•", "—", "–", "(", "[")


_PROSE_CLOSERS = ('"', "'", "”", "’", "»", "›", "“", "‘", "」", "』", "》", ",", ";", "—")


_SENTENCE_ENDINGS = (".", "?", "!", "…")


_VERSE_REFERENCE = re.compile(r"\b\d{1,3}:\d{1,3}\b")


_LIST_LABEL = re.compile(r"^(?:\(?\d{1,3}|[A-Za-z]|[IVXLCDMivxlcdm]{1,7})[.)](?:\s|$)")


@dataclass
class _Candidates:
    """Margin blocks that passed the fail-closed rules, with their evidence.

    `blocks` maps block id to (block, band). `text_occurrences` records where
    each (band, title key) appears; `numbered` and `vertical_positions` record
    each folio value for sequencing.
    """

    blocks: dict[str, tuple[DocumentBlock, str]]
    text_occurrences: dict[tuple[str, str], list[tuple[int, float, float]]]
    numbered: dict[str, list[_NumberedEntry]]
    vertical_positions: dict[tuple[str, int, int, str], list[float]]


@dataclass
class _Pagination:
    """The confirmed page-number sequences, and where numbering stayed ambiguous."""

    sequential_pages: dict[str, set[int]]
    series_at_page: dict[int, set[_Series]]
    selected_sequences: dict[int, set[_Series]]
    ambiguous_numeric_bands: set[tuple[str, int]]
    ambiguous_sequence_pages: set[int]


def _protected_kind(block: DocumentBlock, *, running_title: bool) -> bool:
    """Fail closed on lists, tables, notes, captions, equations and headings."""
    # Fail closed on standalone quotations, numbered list markers and
    # headings. These can legitimately occur in a page's margin band.
    # A heading-styled line repeated as a running head is the exception.
    if block.kind in {"list", "table", "footnote", "caption", "equation", "figure_text"}:
        return True
    return block.kind == "heading" and not running_title


def _quoted_or_dialogue(raw: str) -> bool:
    """Fail closed on quotations, dialogue, bullets and complete sentences."""
    if raw.startswith(_PROSE_OPENERS):
        return True
    if raw.startswith(("- ", "− ")):
        # Hyphen-led dialogue is substantive even when it repeats in margins.
        return True
    # A closing quote or unfinished dialogue clause is also prose, not
    # a title/folio, even when a short fragment repeats in a margin.
    if raw.endswith(_PROSE_CLOSERS):
        return True
    # Short one-word dialogue or complete sentences can recur in page
    # margins; punctuation is stronger evidence of prose than repetition
    # is evidence of a running title. Fail closed instead of deleting it.
    return raw.endswith(_SENTENCE_ENDINGS)


def _speaker_label_or_reference(raw: str) -> bool:
    """Fail closed on speaker labels and chapter-and-verse references."""
    # A repeated dialogue/speaker label or chapter-and-verse reference
    # can be isolated at the top or bottom of multiple pages. Repetition
    # is not sufficient evidence to delete these source text blocks.
    return raw.endswith((":", "：")) or _VERSE_REFERENCE.search(raw) is not None


def _body_phrase(raw: str, body_text: set[str], *, styled_title: bool) -> bool:
    """Fail closed on a margin phrase that also appears inside a page body."""
    # A phrase appearing in the interior of any page is substantive text
    # somewhere in the book; do not delete identical margin occurrences.
    # Folio numerals are exempt: contents pages and cross-references
    # repeat them in body text, and they still need a page sequence.
    # A heading-styled running title, or one carrying its folio, also
    # appears once in the body as its section's own heading; repetition
    # on three or more margins outweighs that. Plain phrases stay.
    return (
        " ".join(raw.split()).casefold() in body_text
        and not PAGE_NUMBER.fullmatch(raw)
        and not styled_title
    )


def _extended_prose(raw: str) -> bool:
    """Fail closed on a full sentence or extended prose in the margin."""
    # A full sentence or extended prose in the margin is not safe to
    # classify as a running title based on repetition alone.
    return len(raw.split()) >= 8 or (len(raw.split()) >= 3 and raw.endswith(_SENTENCE_ENDINGS))


def _list_label(raw: str) -> bool:
    """Fail closed on isolated list labels, which can repeat at page starts."""
    return _LIST_LABEL.match(raw) is not None


def _unconfirmed_numeral(
    block: DocumentBlock,
    raw: str,
    band: str,
    geometry: _PageGeometry,
    running_titles: set[tuple[str, str]],
) -> bool:
    """Fail closed on a standalone numeral that may be a heading or list label."""
    if not PAGE_NUMBER.fullmatch(raw):
        return False
    assert block.bbox is not None
    # Standalone numerals may be section headings or list labels. Large
    # display type is not a folio; a same-line continuation suggests a
    # numbered list rather than a page number.
    if block.font_size is not None and block.font_size > 14:
        return True
    same_line = [
        other
        for other in geometry.blocks_by_page[block.page_index]
        if other.id != block.id
        and other.bbox is not None
        and _valid_bbox(other.bbox)
        and other.text.strip()
        and other.bbox[0] >= block.bbox[2]
        and 0 <= other.bbox[0] - block.bbox[2] <= geometry.sizes[block.page_index][0] * 0.12
        and abs(other.bbox[1] - block.bbox[1]) <= max(5.0, block.bbox[3] - block.bbox[1])
    ]
    # "28   THE DECLINE AND FALL": a folio beside a running title,
    # rather than a list number beside its item.
    beside_title = bool(same_line) and all(
        (band, _running_parts(other.text)[0]) in running_titles for other in same_line
    )
    if same_line and not beside_title:
        return True
    # A lone numeric line at ordinary body indentation is not sufficient
    # evidence of pagination, even if another page starts with "2".
    return not beside_title and not any(
        position <= 0.09 or position >= 0.91 or 0.38 <= position <= 0.62
        for position in geometry.positions(block)
    )


def _record_candidate(
    found: _Candidates,
    block: DocumentBlock,
    band: str,
    geometry: _PageGeometry,
    *,
    title_key: str,
    embedded_folio: str | None,
    running_title: bool,
) -> None:
    """Record a surviving margin block, its position and any folio value."""
    assert block.bbox is not None
    raw = block.text.strip()
    width, height = geometry.sizes[block.page_index][0], geometry.sizes[block.page_index][1]
    found.blocks[block.id] = (block, band)
    if width > 0 and height > 0:
        x_center = (block.bbox[0] + block.bbox[2]) / (2 * width)
        y_center = (block.bbox[1] + block.bbox[3]) / (2 * height)
        found.text_occurrences[(band, title_key)].append((block.page_index, x_center, y_center))
    parsed = _number_value(raw)
    if parsed is not None:
        found.numbered[band].append(
            (block.page_index, parsed[0], geometry.positions(block), parsed[1])
        )
        found.vertical_positions[(band, block.page_index, parsed[0], parsed[1])].append(
            ((block.bbox[1] + block.bbox[3]) / 2) / height
        )
    elif embedded_folio is not None and running_title:
        # The folio inside a running head still sequences its neighbours;
        # its position is the title's, so alignment is not compared.
        embedded = _number_value(embedded_folio)
        if embedded is not None:
            found.numbered[band].append((block.page_index, embedded[0], None, embedded[1]))


def _collect_candidates(
    blocks: list[DocumentBlock],
    geometry: _PageGeometry,
    running_titles: set[tuple[str, str]],
    body_text: set[str],
) -> _Candidates:
    """Collect the margin-band blocks that could be running heads or folios.

    Each block in a header or footer band must pass every fail-closed rule
    before it is recorded; the rules only keep text, never remove it.
    """
    found = _Candidates({}, defaultdict(list), defaultdict(list), defaultdict(list))
    for block in blocks:
        if (
            not block.bbox
            or not _valid_bbox(block.bbox)
            or not geometry.valid_page(block.page_index)
        ):
            continue
        height = geometry.sizes[block.page_index][1]
        top, bottom = block.bbox[1], block.bbox[3]
        band = "header" if bottom < height * 0.12 else ("footer" if top > height * 0.88 else None)
        if not band:
            continue
        raw = block.text.strip()
        val, embedded_folio = _running_parts(raw)
        running_title = (band, val) in running_titles
        styled_title = running_title and (block.kind == "heading" or embedded_folio is not None)
        if (
            _continuous_with_body(
                block, band, geometry, running_title=running_title, embedded_folio=embedded_folio
            )
            or _protected_kind(block, running_title=running_title)
            or _quoted_or_dialogue(raw)
            or _speaker_label_or_reference(raw)
            or _body_phrase(raw, body_text, styled_title=styled_title)
            or _extended_prose(raw)
            or _list_label(raw)
            or _unconfirmed_numeral(block, raw, band, geometry, running_titles)
        ):
            continue
        _record_candidate(
            found,
            block,
            band,
            geometry,
            title_key=val,
            embedded_folio=embedded_folio,
            running_title=running_title,
        )
    return found
