"""Outline (bookmark) entries: matching them to the text and anchoring headings to them."""

from __future__ import annotations

from collections import defaultdict

from pdf2audiobook.document.headings import _HeadingEvidence
from pdf2audiobook.document.labels import _title_key, bare_number, label_number


def _valid_bookmarks(toc: list[list]) -> tuple[list[tuple[str, int]], int]:
    """Keep well-formed outline entries at depth one or two.

    Returns their (title, page number) pairs and the count of malformed records.
    """
    malformed_bookmarks = 0
    valid_bookmarks: list[tuple[str, int]] = []
    for entry in toc:
        # Bookmarks are advisory metadata. Corrupt/third-party TOC records
        # must not abort an otherwise usable source-text chapter analysis.
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            malformed_bookmarks += 1
            continue
        depth, title, page_num = entry[:3]
        if (
            isinstance(depth, bool)
            or not isinstance(depth, int)
            or isinstance(page_num, bool)
            or not isinstance(page_num, int)
            or depth < 1
            or page_num < 1
            or not isinstance(title, str)
        ):
            malformed_bookmarks += 1
            continue
        if depth > 2:
            continue
        valid_bookmarks.append((title, page_num))
    return valid_bookmarks, malformed_bookmarks


def _inferred_bookmark_offset(
    evidence: _HeadingEvidence, valid_bookmarks: list[tuple[str, int]]
) -> int | None:
    """Infer a printed-to-physical page offset for the outline, warning when used."""
    blocks = evidence.blocks
    # A printed TOC can be offset from physical PDF pages by front matter.
    # Infer a nontrivial offset only from at least two distinct, uniquely
    # matched textual headings and no conflicting unique heading evidence.
    offset_evidence: dict[int, set[str]] = defaultdict(set)
    headings_by_title: dict[str, list[int]] = defaultdict(list)
    for i in evidence.heading_indices:
        if blocks[i].id not in evidence.omitted:
            headings_by_title[_title_key(blocks[i].text)].append(i)
    for title, page_num in valid_bookmarks:
        normalized = _title_key(title)
        matches = headings_by_title.get(normalized, [])
        if len(matches) == 1:
            offset = blocks[matches[0]].page_index - (page_num - 1)
            if abs(offset) <= 128:
                offset_evidence[offset].add(normalized)
    inferred_offset: int | None = None
    if len(offset_evidence) == 1:
        offset, titles = next(iter(offset_evidence.items()))
        if abs(offset) > 2 and len(titles) >= 2:
            inferred_offset = offset
            evidence.warnings.append(
                f"PDF bookmark page offset {offset:+d} inferred from "
                f"{len(titles)} unique headings; verify chapter alignment"
            )
    return inferred_offset


def _bookmark_match(
    evidence: _HeadingEvidence,
    blocks_by_title: dict[str, list[int]],
    title: str,
    page_num: int,
    inferred_offset: int | None,
) -> int | None:
    """The block an outline entry opens, or None when no unique match exists."""
    blocks = evidence.blocks
    listing_pages = evidence.listing_pages
    page_index = page_num - 1
    title_normalized = _title_key(title)
    if not title_normalized:
        return None
    matching = blocks_by_title.get(title_normalized, [])
    exact = [i for i in matching if blocks[i].page_index == page_index]
    # A TOC page number may refer to printed rather than physical pages.
    # Correct only a unique nearby title, never a duplicated phrase. A page that
    # lists chapters never opens one, so it is not a candidate.
    nearby = [
        i
        for i in matching
        if abs(blocks[i].page_index - page_index) <= 2 and blocks[i].page_index not in listing_pages
    ]
    match = exact[0] if len(exact) == 1 else None
    wanted = label_number(title)
    if match is None and wanted is not None:
        # Many books open a chapter with only its numeral ("12") while the outline
        # says "Chapter 12". The outline's page is authoritative: take the first
        # line there when it is that chapter's numeral. When the outline uses
        # printed page numbers, the inferred offset locates the physical page.
        candidate_pages = [page_index]
        if inferred_offset is not None:
            candidate_pages.append(page_index + inferred_offset)
        for candidate_page in candidate_pages:
            if candidate_page in listing_pages:
                continue
            first = evidence.first_on_page.get(candidate_page)
            if first is not None and bare_number(blocks[first].text) == wanted:
                match = first
                evidence.numeral_anchored.add(first)
                break
    if match is None and not exact and len(nearby) == 1:
        match = nearby[0]
    if match is None and not exact and not nearby and inferred_offset is not None:
        shifted = [
            i
            for i in matching
            if blocks[i].page_index == page_index + inferred_offset
            and blocks[i].page_index not in listing_pages
        ]
        if len(shifted) == 1:
            match = shifted[0]
    return match


def _anchor_bookmarks(evidence: _HeadingEvidence, toc: list[list]) -> None:
    """Add a heading for each outline entry that uniquely matches the text.

    Fills `bookmark_titles`, `numeral_anchored` and `first_on_page`, and warns
    about entries matched off their page and about malformed records.
    """
    blocks = evidence.blocks
    # Combine confirmed bookmark anchors with textual headings. Some books mix
    # numbered headings and ornamental titles; do not discard the TOC merely
    # because a subset of chapters matched the regular expression.
    valid_bookmarks, malformed_bookmarks = _valid_bookmarks(toc)
    inferred_offset = _inferred_bookmark_offset(evidence, valid_bookmarks)

    # One pass indexes every block by title and every page by its first line, so each
    # outline entry is matched without rescanning the book.
    blocks_by_title: dict[str, list[int]] = defaultdict(list)
    for i, block in enumerate(blocks):
        if block.id in evidence.omitted:
            continue
        blocks_by_title[_title_key(block.text)].append(i)
        if block.text.strip():
            evidence.first_on_page.setdefault(block.page_index, i)
    for title, page_num in valid_bookmarks:
        match = _bookmark_match(evidence, blocks_by_title, title, page_num, inferred_offset)
        if match is not None:
            evidence.heading_indices.append(match)
            evidence.bookmark_titles[match] = title.strip()
            if blocks[match].page_index != page_num - 1:
                evidence.warnings.append(
                    f"TOC entry {title!r} points to PDF page {page_num}; "
                    f"matched unique title on page {blocks[match].page_index + 1}"
                )
    if malformed_bookmarks:
        evidence.warnings.append(
            f"Skipped {malformed_bookmarks} malformed PDF bookmark "
            "record(s); verify chapter boundaries manually"
        )
