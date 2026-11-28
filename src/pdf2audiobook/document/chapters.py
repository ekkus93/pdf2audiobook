"""Chapter proposal: from heading candidates to the chapters a book is split into."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from pdf2audiobook.config import Chapters as ChapterSettings
from pdf2audiobook.document.bookmarks import _anchor_bookmarks
from pdf2audiobook.document.candidates import (
    _corroborate_numerals,
    _drop_crowded_typography,
    _drop_listed_labels,
    _drop_subtitles,
    _drop_weak_candidates,
    _nest_numbered_subsections,
)
from pdf2audiobook.document.contents import (
    _continued_contents_page,
    _listing_pages,
    _printed_contents,
)
from pdf2audiobook.document.coverage import (
    chapter_has_speakable_text,
)
from pdf2audiobook.document.headings import (
    _HeadingEvidence,
    _space_above,
    _text_headings,
    _typical_body_size,
)
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import Chapter, DocumentBlock, generated_chapter_fingerprint


@dataclass
class ChapterProposal:
    chapters: list[Chapter]
    warnings: list[str]
    review_reasons: set[str]

    def __iter__(self) -> Iterator[list]:
        # Preserve the established ``chapters, warnings = propose_chapters(...)`` API.
        yield self.chapters
        yield self.warnings


def _chapter_starts(evidence: _HeadingEvidence, settings: ChapterSettings) -> list[int]:
    """The first block of each chapter, refusing a book with no usable boundary."""
    blocks = evidence.blocks
    heading_indices = evidence.heading_indices
    if not blocks:
        raise ExtractionError("No text found in PDF; no chapters can be created")
    if not heading_indices and not settings.allow_single_chapter:
        raise ExtractionError(
            "No reliable chapter boundaries found. Edit a manifest or retry "
            "with --allow-single-chapter; no text was silently grouped."
        )
    # Removed pagination noise above the first heading (e.g. a running header)
    # is not front matter. Fold it into the first chapter rather than creating
    # an empty, low-confidence chapter that blocks synthesis.
    noise_prefix = (
        bool(heading_indices)
        and heading_indices[0] != 0
        and all(block.id in evidence.omitted for block in blocks[: heading_indices[0]])
    )
    starts = ([0] if 0 not in heading_indices and not noise_prefix else []) + heading_indices
    if not heading_indices:
        evidence.warnings.append("Single-chapter mode explicitly requested")
    elif starts[0] == 0 and heading_indices[0] != 0:
        evidence.warnings.append("Pre-chapter material retained in its own front-matter chapter")
    return starts


def _heading_name_confidence_evidence(
    evidence: _HeadingEvidence, start: int
) -> tuple[str, float, list[str]]:
    """The title, confidence and evidence list for a chapter opened by a heading."""
    blocks = evidence.blocks
    bookmark_titles = evidence.bookmark_titles
    numeral_titles = evidence.numeral_titles
    contents_titles = evidence.contents_titles
    typography_ids = evidence.typography_ids
    llm_only = evidence.llm_only
    name = (
        bookmark_titles.get(start)
        or numeral_titles.get(start)
        or contents_titles.get(start, blocks[start].text.strip())
    )
    confidence = (
        0.95
        if start in bookmark_titles
        and not any(
            f"TOC entry {bookmark_titles[start]!r} points" in warning
            for warning in evidence.warnings
        )
        else 0.85
        if start in bookmark_titles
        else 0.9
        if start in numeral_titles
        else 0.9
        if start in contents_titles
        else 0.82
        if start in typography_ids
        else 0.8
        if start in llm_only
        else 0.9
    )
    chapter_evidence = (
        ["PDF bookmark matched the numbered chapter heading on its page"]
        if start in evidence.numeral_anchored
        else ["PDF bookmark/TOC matched unique source title"]
        if start in bookmark_titles
        else ["numeral heading corroborated by the printed contents"]
        if start in numeral_titles
        else ["printed contents entry matched unique later heading"]
        if start in contents_titles
        else ["typographic size contrast with body text"]
        if start in typography_ids
        else ["LLM structure classification (advisory)"]
        if start in llm_only
        else ["explicit heading text"]
    )
    space = _space_above(blocks, start, evidence.omitted)
    if space == "page":
        chapter_evidence = [*chapter_evidence, "opens a new page"]
    elif space == "gap":
        chapter_evidence = [*chapter_evidence, "vertical whitespace above"]
    return name, confidence, chapter_evidence


def _build_chapters(evidence: _HeadingEvidence, starts: list[int]) -> list[Chapter]:
    """Build one generated chapter per start, recording its generated fields."""
    blocks = evidence.blocks
    heading_indices = evidence.heading_indices
    chapters = []
    for number, start in enumerate(starts, 1):
        end = starts[number] if number < len(starts) else len(blocks)
        if start == 0 and heading_indices and start != heading_indices[0]:
            name = "Front Matter"
            confidence = 0.7
            chapter_evidence = ["unassigned material before chapter heading"]
        elif start in heading_indices:
            name, confidence, chapter_evidence = _heading_name_confidence_evidence(evidence, start)
        else:
            name = "Full Book"
            confidence = 0.5
            chapter_evidence = ["explicit single chapter override"]
        chapter = Chapter(
            id=f"c{number:04d}",
            number=number,
            title=name,
            start_block=0 if number == 1 else start,
            end_block=end,
            confidence=confidence,
            evidence=chapter_evidence,
        )
        if confidence < 0.85:
            chapter.warnings.append("Chapter boundary has low confidence; verify manually")
        chapter.generated_fingerprint = generated_chapter_fingerprint(chapter)
        chapter.generated_title = chapter.title
        chapter.generated_start_block = chapter.start_block
        chapter.generated_end_block = chapter.end_block
        chapter.generated_voice_id = chapter.voice_id
        chapters.append(chapter)
    return chapters


def propose_chapters(
    blocks: list[DocumentBlock],
    omitted: set[str],
    toc: list[list],
    settings: ChapterSettings,
    extra_heading_ids: set[str] | None = None,
) -> ChapterProposal:
    """Segment by marked or formatted headings; require review if insufficient evidence.

    Steps, in order: typography evidence, the printed contents, text headings,
    contents-run pages, bookmark anchors, crowded large type, numerals named by
    the contents, listed labels, weak candidates, subtitles, numbered subsections,
    then the chapters.
    """
    typical_size = _typical_body_size(blocks, omitted)
    contents_lines, contents_titles = _printed_contents(blocks, omitted, typical_size)
    contents_lines |= _continued_contents_page(blocks, omitted, contents_lines)
    heading_indices, typography_ids = _text_headings(
        blocks, omitted, contents_lines, contents_titles, typical_size, extra_heading_ids
    )
    evidence = _HeadingEvidence(
        blocks=blocks,
        omitted=omitted,
        contents_titles=contents_titles,
        heading_indices=heading_indices,
        typography_ids=typography_ids,
        warnings=[],
    )
    evidence.listing_pages = _listing_pages(blocks, omitted)
    _anchor_bookmarks(evidence, toc)
    _drop_crowded_typography(evidence)
    anchored_keys = _corroborate_numerals(evidence)
    _drop_listed_labels(evidence, anchored_keys)
    _drop_weak_candidates(evidence, extra_heading_ids)
    _drop_subtitles(evidence)
    _nest_numbered_subsections(evidence)
    starts = _chapter_starts(evidence, settings)
    chapters = _build_chapters(evidence, starts)
    empty_chapter = any(
        not chapter_has_speakable_text(
            blocks, chapter.start_block, chapter.end_block, {block_id: "" for block_id in omitted}
        )
        for chapter in chapters
    )
    return ChapterProposal(
        chapters=chapters,
        warnings=evidence.warnings,
        review_reasons={"empty_chapter"} if empty_chapter else set(),
    )
