"""Printed contents pages: finding the page and the chapters it lists, and its continuation lines."""

from __future__ import annotations

import re
from collections import defaultdict

from pdf2audiobook.document.labels import (
    CONTENTS_HEADINGS,
    CONTENTS_PAGE_REF,
    NUMBERED_LABEL,
    PAGE_NUMBER,
    PAGE_REFERENCE_END,
    _loose_key,
    _title_key,
    label_key,
)
from pdf2audiobook.models import DocumentBlock


def _printed_contents(
    blocks: list[DocumentBlock], omitted: set[str], typical_size: float | None
) -> tuple[set[int], dict[int, str]]:
    """Find a printed contents page and the unique later headings it lists.

    Returns the contents-page line indices and {later heading index: title}.
    Titles are trusted only when at least two entries match uniquely.
    """
    start = next(
        (
            i
            for i, block in enumerate(blocks)
            if block.id not in omitted and _title_key(block.text) in CONTENTS_HEADINGS
        ),
        None,
    )
    if start is None:
        return set(), {}

    # Entries and their headings are at least body size; smaller lines are
    # running heads, column labels or footnotes.
    def heading_size(index: int) -> bool:
        size = blocks[index].font_size
        return typical_size is None or size is None or float(size) >= typical_size * 0.95

    contents_page = blocks[start].page_index
    lines = {start}
    # (block index, normalized entry, tentative). Entries on the following
    # page are tentative: that page may instead open the first chapter, so
    # they count only if they name a later heading other than themselves.
    entries: list[tuple[int, str, bool]] = []
    for i in range(start + 1, len(blocks)):
        block = blocks[i]
        if block.page_index > contents_page + 1:
            break
        if block.id in omitted:
            continue
        tentative = block.page_index != contents_page
        text = block.text.rstrip()
        if tentative and (
            len(text.split()) > 10
            or text.endswith((".", "?", "!"))
            and not CONTENTS_PAGE_REF.search(text)
        ):
            break
        if not tentative:
            lines.add(i)
        entry = _title_key(CONTENTS_PAGE_REF.sub("", text))
        if (
            heading_size(i)
            and _loose_key(entry)
            and not entry.isdecimal()
            and not PAGE_NUMBER.match(entry)
        ):
            entries.append((i, entry, tentative))
    after = max(lines) + 1

    # Later heading lines, alone or joined with the next line on the same page,
    # since titles may wrap differently on the contents page and in the body.
    # Exact keys are tried first; letters-only keys tolerate OCR noise but
    # collide more easily with body text, so they are only a fallback.
    exact: dict[str, list[tuple[int, int]]] = defaultdict(list)
    loose: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for i in range(after, len(blocks)):
        if blocks[i].id in omitted or not heading_size(i):
            continue
        texts = [(blocks[i].text, 1)]
        j = i + 1
        if (
            j < len(blocks)
            and blocks[j].id not in omitted
            and blocks[j].page_index == blocks[i].page_index
            and heading_size(j)
        ):
            texts.append((f"{blocks[i].text} {blocks[j].text}", 2))
        for text, width in texts:
            exact[_title_key(text)].append((i, width))
            loose[_loose_key(text)].append((i, width))

    def unique(key: str, own: set[int]) -> tuple[int, int] | None:
        for spans, normalized in ((exact, _title_key(key)), (loose, _loose_key(key))):
            found = [span for span in spans.get(normalized, []) if span[0] not in own]
            if len(found) == 1:
                return found[0]
        return None

    titles: dict[int, str] = {}
    position = 0
    while position < len(entries):
        own_index, key, tentative = entries[position]
        own = {own_index}
        match = None
        consumed = 1
        if position + 1 < len(entries):
            next_index, next_key, next_tentative = entries[position + 1]
            match = unique(f"{key} {next_key}", own | {next_index})
            if match is not None:
                consumed = 2
                tentative = tentative or next_tentative
        if match is None:
            match = unique(key, own)
        if match is None or match[0] <= own_index:
            position += 1
            continue
        index, width = match
        if tentative:
            lines.update(entries[k][0] for k in range(position, position + consumed))
        titles[index] = " ".join(blocks[k].text.strip() for k in range(index, index + width))
        position += consumed
    return lines, titles if len(titles) >= 2 else {}


def _continued_contents_page(
    blocks: list[DocumentBlock], omitted: set[str], contents_lines: set[int]
) -> set[int]:
    """Lines of the page after a printed contents page that only continue its labels.

    A contents list split over two pages ("Chapter 1" to "Chapter 3", then
    "Chapter 4" to "Chapter 6") names chapters on both. The second page counts
    only when every line on it is the next numbered label of the same kind, so
    a page that opens a chapter is never taken for contents.
    """
    if not contents_lines:
        return set()
    contents_page = blocks[min(contents_lines)].page_index
    listed = [
        key
        for i in sorted(contents_lines)
        if blocks[i].page_index == contents_page
        and NUMBERED_LABEL.match(blocks[i].text.strip())
        and (key := label_key(blocks[i].text)) is not None
    ]
    if not listed:
        return set()
    kind, number = listed[-1]
    following = [
        i
        for i, block in enumerate(blocks)
        if block.page_index == contents_page + 1
        and block.id not in omitted
        and block.text.strip()
        and i not in contents_lines
    ]
    for i in following:
        number += 1
        if not NUMBERED_LABEL.match(blocks[i].text.strip()) or label_key(blocks[i].text) != (
            kind,
            number,
        ):
            return set()
    return set(following)


def _listing_pages(blocks: list[DocumentBlock], omitted: set[str]) -> set[int]:
    """Pages that list chapters (a contents run), with single-page gaps filled."""
    # Pages that list chapters (a contents run) name chapters; they do not open them.
    lines_on_page: dict[int, list[str]] = defaultdict(list)
    for block in blocks:
        if block.id not in omitted and block.text.strip():
            lines_on_page[block.page_index].append(block.text.strip())
    listing_pages = {
        page
        for page, texts in lines_on_page.items()
        if len(texts) >= 6
        and sum(
            bool(PAGE_REFERENCE_END.search(text) or re.fullmatch(r"\d{1,4}", text))
            for text in texts
        )
        >= 0.3 * len(texts)
    }
    # A contents run spans consecutive pages; fill single-page gaps.
    listing_pages |= {
        page + 1
        for page in listing_pages
        if page + 2 in listing_pages and page + 1 in lines_on_page
    }
    return listing_pages
