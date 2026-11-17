"""Filters that drop heading candidates which other evidence contradicts."""

from __future__ import annotations

from collections import defaultdict

from pdf2audiobook.document.headings import _HeadingEvidence
from pdf2audiobook.document.labels import (
    NUMBERED_LABEL,
    _label_key,
    bare_number,
    contents_label_title,
    is_heading_line,
    label_key,
)


def _drop_crowded_typography(evidence: _HeadingEvidence) -> None:
    """Drop large-type candidates when four or more crowd one page."""
    blocks = evidence.blocks
    # Large type crowding one page (a contents listing, an advert, a scanned
    # cover read as text) is layout, not a run of chapter openings.
    per_page: dict[int, list[int]] = defaultdict(list)
    for i in evidence.typography_ids:
        per_page[blocks[i].page_index].append(i)
    crowded = {i for ids in per_page.values() if len(ids) >= 4 for i in ids}
    if crowded:
        evidence.typography_ids -= crowded
        evidence.heading_indices = [
            i
            for i in evidence.heading_indices
            if i not in crowded or is_heading_line(blocks[i].text) or i in evidence.contents_titles
        ]


def _corroborate_numerals(evidence: _HeadingEvidence) -> set[tuple[str, int]]:
    """Promote bare page-opening numerals that the printed contents names.

    Fills `numeral_titles` and adds those headings. Returns the (kind, number)
    labels that open a chapter outside the contents pages.
    """
    blocks = evidence.blocks
    listing_pages = evidence.listing_pages
    # Books often open a chapter with only its numeral. When the printed contents names
    # "Chapter N" and numerals then open pages in order, those numerals are the chapter
    # headings and the contents labels are references to them. Parts and chapters are
    # numbered separately, so labels are keyed by (kind, number).
    listed_by_kind: dict[str, dict[int, int]] = defaultdict(dict)
    for i, block in enumerate(blocks):
        if block.id in evidence.omitted or block.page_index not in listing_pages:
            continue
        key = label_key(block.text)
        if key is not None and NUMBERED_LABEL.match(block.text.strip()):
            listed_by_kind[key[0]].setdefault(key[1], i)
    numeral_kind = "chapter" if listed_by_kind.get("chapter") else "part"
    listed_labels = listed_by_kind.get(numeral_kind, {})
    corroborated: dict[int, int] = {}
    last_number = 0
    for page in sorted(evidence.first_on_page):
        i = evidence.first_on_page[page]
        if page in listing_pages or i in evidence.bookmark_titles:
            continue
        number = bare_number(blocks[i].text)
        if number is not None and number > last_number and number in listed_labels:
            corroborated[i] = number
            last_number = number
    # Running page numbers advance one per page; chapters rarely do. When most
    # consecutive numerals are exactly that far apart, they are page numbers, even if
    # an unnumbered page somewhere shifts the offset.
    steps = sorted((blocks[i].page_index, number) for i, number in corroborated.items())
    pairs = list(zip(steps, steps[1:]))
    lockstep = sum(
        1 for (page_a, num_a), (page_b, num_b) in pairs if page_b - page_a == num_b - num_a
    )
    page_numbers = bool(pairs) and 2 * lockstep >= len(pairs)
    if not page_numbers and len(corroborated) >= 3 and 2 * len(corroborated) >= len(listed_labels):
        for i, number in corroborated.items():
            evidence.numeral_titles[i] = contents_label_title(blocks[listed_labels[number]].text)
            if i not in evidence.heading_indices:
                evidence.heading_indices.append(i)
    return {
        key
        for i, title in evidence.bookmark_titles.items()
        if blocks[i].page_index not in listing_pages and (key := label_key(title)) is not None
    } | {
        (numeral_kind, number)
        for number in (corroborated.values() if evidence.numeral_titles else ())
    }


def _drop_listed_labels(evidence: _HeadingEvidence, anchored_keys: set[tuple[str, int]]) -> None:
    """Drop chapter labels on contents pages that are references, not headings."""
    blocks = evidence.blocks
    listing_pages = evidence.listing_pages
    # A chapter label on a contents-style page (most lines end in a page
    # reference) is a listing when the same label opens a chapter later.
    label_positions: dict[str, list[int]] = defaultdict(list)
    for i in evidence.heading_indices:
        if NUMBERED_LABEL.match(blocks[i].text.strip()):
            label_positions[_label_key(blocks[i].text)].append(i)
    listed = {
        i
        for positions in label_positions.values()
        for i in positions[:-1]
        if blocks[i].page_index in listing_pages and i not in evidence.bookmark_titles
    }
    # A listed label whose chapter opens elsewhere is a reference to it, not a heading.
    listed |= {
        i
        for i in evidence.heading_indices
        if blocks[i].page_index in listing_pages
        and i not in evidence.bookmark_titles
        and label_key(blocks[i].text) in anchored_keys
    }
    evidence.heading_indices = [i for i in evidence.heading_indices if i not in listed]


def _drop_weak_candidates(evidence: _HeadingEvidence, extra_heading_ids: set[str] | None) -> None:
    """Drop font-size-only and LLM-only candidates when stronger evidence exists.

    Sets `llm_only` and warns about each kind of candidate it ignores.
    """
    blocks = evidence.blocks
    numbered_labels = sum(
        1 for i in evidence.heading_indices if NUMBERED_LABEL.match(blocks[i].text.strip())
    )
    # Candidates supported only by font size or by LLM classification.
    llm_ids = extra_heading_ids or set()
    weak = {
        i
        for i in evidence.heading_indices
        if (i in evidence.typography_ids or blocks[i].id in llm_ids)
        and i not in evidence.bookmark_titles
        and i not in evidence.contents_titles
        and i not in evidence.numeral_titles
        and not is_heading_line(blocks[i].text)
    }
    llm_only = {i for i in weak if i not in evidence.typography_ids}
    evidence.llm_only = llm_only
    if (
        len(evidence.bookmark_titles) >= 2
        or evidence.contents_titles
        or numbered_labels >= 3
        or len(evidence.numeral_titles) >= 3
    ):
        # A PDF outline or printed contents that matches the text is stronger
        # evidence than font size or LLM classification. Do not let material
        # it omits (catalogue entries, scene breaks, stray running heads)
        # split the book into spurious chapters.
        if weak:
            evidence.heading_indices = [i for i in evidence.heading_indices if i not in weak]
            if weak - llm_only:
                evidence.warnings.append(
                    f"Ignored {len(weak - llm_only)} font-size-only heading candidate(s) "
                    "not in the PDF outline, printed contents or numbered chapter labels; "
                    "verify chapter boundaries"
                )
            if llm_only:
                evidence.warnings.append(
                    f"Ignored {len(llm_only)} LLM-proposed heading(s) not in the PDF "
                    "outline, printed contents or numbered chapter labels; "
                    "verify chapter boundaries"
                )


def _drop_subtitles(evidence: _HeadingEvidence) -> None:
    """Drop contents entries that title the line right after another heading."""
    blocks = evidence.blocks
    # A contents entry naming the line right after another heading is that
    # chapter's subtitle ("CHAPTER III." / "ON RELATIVE GROWINGS."), not a
    # new boundary.
    detected = set(evidence.heading_indices)
    subtitles = set()
    for i in evidence.contents_titles:
        previous = next(
            (j for j in range(i - 1, -1, -1) if blocks[j].id not in evidence.omitted), None
        )
        if previous in detected and previous not in evidence.contents_titles:
            subtitles.add(i)
    heading_indices = [i for i in evidence.heading_indices if i not in subtitles]
    evidence.heading_indices = sorted(set(heading_indices))
