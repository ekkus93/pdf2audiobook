"""Conservative pagination removal and chapter-boundary detection.

Raw blocks are immutable. Cleanup decisions are stored as audited edits.
"""
from __future__ import annotations

import re
from collections import defaultdict

from pdf2audiobook.config import Chapters as ChapterSettings
from pdf2audiobook.config import Pdf as PdfSettings
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import Chapter, CleanupEdit, DocumentBlock

HEADING = re.compile(
    r"^(?:(?:chapter|part)\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|"
    r"seven|eight|nine|ten)\b.*|prologue|epilogue|preface|introduction)$",
    re.IGNORECASE,
)
PAGE_NUMBER = re.compile(r"^(?:\d{1,5}|[ivxlcdm]{1,10})$", re.IGNORECASE)


def pagination_cleanup(
    blocks: list[DocumentBlock],
    sizes: list[tuple[float, float]],
    settings: PdfSettings,
) -> list[CleanupEdit]:
    """Remove only corroborated pagination patterns confined to margin bands."""
    candidates: dict[str, tuple[DocumentBlock, str]] = {}
    text_occurrences: dict[tuple[str, str], set[int]] = defaultdict(set)
    numbered: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for block in blocks:
        if not block.bbox or block.page_index >= len(sizes):
            continue
        height = sizes[block.page_index][1]
        top, bottom = block.bbox[1], block.bbox[3]
        band = "header" if bottom < height * 0.12 else (
            "footer" if top > height * 0.88 else None
        )
        if not band:
            continue
        val = " ".join(block.text.split()).casefold()
        candidates[block.id] = (block, band)
        text_occurrences[(band, val)].add(block.page_index)
        if PAGE_NUMBER.fullmatch(block.text.strip()):
            raw = block.text.strip()
            if raw.isdigit():
                numbered[band].append((block.page_index, int(raw)))
    sequential_pages: dict[str, set[int]] = defaultdict(set)
    for band, values in numbered.items():
        for page, value in values:
            if any(abs(page - p2) == 1 and abs(value - v2) == 1 for p2, v2 in values):
                sequential_pages[band].add(page)
    edits = []
    for block, band in candidates.values():
        value = " ".join(block.text.split()).casefold()
        is_number = PAGE_NUMBER.fullmatch(block.text.strip()) is not None
        confirmed_number = is_number and (
            len(text_occurrences[(band, value)]) >= 2 or
            block.page_index in sequential_pages[band]
        )
        repeated = len(text_occurrences[(band, value)]) >= 2
        if is_number and confirmed_number and settings.remove_page_numbers:
            reason = "sequential/repeated page number"
        elif not is_number and repeated and (
            (band == "header" and settings.remove_headers) or
            (band == "footer" and settings.remove_footers)
        ):
            reason = "repeated running " + band
        else:
            continue
        edits.append(CleanupEdit(
            block_id=block.id, original=block.text, replacement="",
            reason=reason, confidence=0.98, accepted=True
        ))
    return edits


def propose_chapters(
    blocks: list[DocumentBlock],
    omitted: set[str],
    toc: list[list],
    settings: ChapterSettings,
    extra_heading_ids: set[str] | None = None,
) -> tuple[list[Chapter], list[str]]:
    """Segment by marked or formatted headings; require review if insufficient evidence."""
    warnings: list[str] = []
    heading_indices = []
    for i, block in enumerate(blocks):
        if block.id in omitted:
            continue
        text = block.text.strip()
        if HEADING.match(text) or block.id in (extra_heading_ids or set()):
            heading_indices.append(i)
    if not heading_indices and toc:
        # Bookmarks are 1-based page references; choose the first matching text block.
        pages = set()
        for depth, title, page_num, *_ in toc:
            if depth <= 2 and page_num > 0:
                pages.add((page_num - 1, title))
        for page, title in sorted(pages):
            match = next(
                (i for i, block in enumerate(blocks)
                 if block.page_index == page and title.casefold() in block.text.casefold()
                 and block.id not in omitted),
                None,
            )
            if match is not None:
                heading_indices.append(match)
    heading_indices = sorted(set(heading_indices))
    if not blocks:
        raise ExtractionError("No text found in PDF; no chapters can be created")
    if not heading_indices and not settings.allow_single_chapter:
        raise ExtractionError(
            "No reliable chapter boundaries found. Edit a manifest or retry "
            "with --allow-single-chapter; no text was silently grouped."
        )
    starts = ([0] if 0 not in heading_indices else []) + heading_indices
    if not heading_indices:
        warnings.append("Single-chapter mode explicitly requested")
    elif starts[0] == 0 and heading_indices[0] != 0:
        warnings.append("Pre-chapter material retained in its own front-matter chapter")
    chapters = []
    for number, start in enumerate(starts, 1):
        end = starts[number] if number < len(starts) else len(blocks)
        if start == 0 and heading_indices and start != heading_indices[0]:
            name = "Front Matter"
            confidence = 0.7
            evidence = ["unassigned material before chapter heading"]
        elif start in heading_indices:
            name = blocks[start].text.strip()
            confidence = 0.9
            evidence = ["explicit heading text"]
        else:
            name = "Full Book"
            confidence = 0.5
            evidence = ["explicit single chapter override"]
        chapters.append(Chapter(
            id=f"c{number:04d}", number=number, title=name,
            start_block=start, end_block=end, confidence=confidence,
            evidence=evidence
        ))
    return chapters, warnings


def chapter_text(
    blocks: list[DocumentBlock], chapter: Chapter, omitted: set[str]
) -> str:
    """Only audibly retain blocks not removed by accepted audited edits."""
    return "\n".join(
        block.text for block in blocks[chapter.start_block:chapter.end_block]
        if block.id not in omitted
    ).strip() + "\n"
