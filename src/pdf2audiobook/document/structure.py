"""Chapter structure: the facade over the topic modules that find chapters in a book.

The steps live in `labels` (numbers, labels and heading lines), `contents` (printed contents
pages), `headings` (heading candidates), `bookmarks` (outline entries), `candidates` (filters)
and `chapters` (proposal). Pagination, coverage and narration are their own modules too. This
module re-exports every name they define, so existing imports keep working.

Raw blocks are immutable. Cleanup decisions are stored as audited edits.
"""

from __future__ import annotations

from pdf2audiobook.document.bookmarks import (
    _anchor_bookmarks as _anchor_bookmarks,
)
from pdf2audiobook.document.bookmarks import (
    _bookmark_match as _bookmark_match,
)
from pdf2audiobook.document.bookmarks import (
    _inferred_bookmark_offset as _inferred_bookmark_offset,
)
from pdf2audiobook.document.bookmarks import (
    _valid_bookmarks as _valid_bookmarks,
)
from pdf2audiobook.document.candidates import (
    _corroborate_numerals as _corroborate_numerals,
)
from pdf2audiobook.document.candidates import (
    _drop_crowded_typography as _drop_crowded_typography,
)
from pdf2audiobook.document.candidates import (
    _drop_listed_labels as _drop_listed_labels,
)
from pdf2audiobook.document.candidates import (
    _drop_subtitles as _drop_subtitles,
)
from pdf2audiobook.document.candidates import (
    _drop_weak_candidates as _drop_weak_candidates,
)
from pdf2audiobook.document.chapters import (
    ChapterProposal as ChapterProposal,
)
from pdf2audiobook.document.chapters import (
    _build_chapters as _build_chapters,
)
from pdf2audiobook.document.chapters import (
    _chapter_starts as _chapter_starts,
)
from pdf2audiobook.document.chapters import (
    _heading_name_confidence_evidence as _heading_name_confidence_evidence,
)
from pdf2audiobook.document.chapters import (
    propose_chapters as propose_chapters,
)
from pdf2audiobook.document.contents import (
    _continued_contents_page as _continued_contents_page,
)
from pdf2audiobook.document.contents import (
    _listing_pages as _listing_pages,
)
from pdf2audiobook.document.contents import (
    _printed_contents as _printed_contents,
)
from pdf2audiobook.document.coverage import (
    chapter_coverage_report as chapter_coverage_report,
)
from pdf2audiobook.document.coverage import (
    chapter_has_speakable_text as chapter_has_speakable_text,
)
from pdf2audiobook.document.coverage import (
    validate_chapter_coverage as validate_chapter_coverage,
)
from pdf2audiobook.document.headings import (
    _HeadingEvidence as _HeadingEvidence,
)
from pdf2audiobook.document.headings import (
    _is_typographic_heading as _is_typographic_heading,
)
from pdf2audiobook.document.headings import (
    _space_above as _space_above,
)
from pdf2audiobook.document.headings import (
    _text_headings as _text_headings,
)
from pdf2audiobook.document.headings import (
    _typical_body_size as _typical_body_size,
)
from pdf2audiobook.document.labels import (
    _LEADER_PAGE_REF as _LEADER_PAGE_REF,
)
from pdf2audiobook.document.labels import (
    _NUMBER_WORDS as _NUMBER_WORDS,
)
from pdf2audiobook.document.labels import (
    _TENS_WORDS as _TENS_WORDS,
)
from pdf2audiobook.document.labels import (
    CANONICAL_ROMAN as CANONICAL_ROMAN,
)
from pdf2audiobook.document.labels import (
    CHAPTER_TEXT_NAME as CHAPTER_TEXT_NAME,
)
from pdf2audiobook.document.labels import (
    CHAPTER_WORD as CHAPTER_WORD,
)
from pdf2audiobook.document.labels import (
    CONTENTS_HEADINGS as CONTENTS_HEADINGS,
)
from pdf2audiobook.document.labels import (
    CONTENTS_PAGE_REF as CONTENTS_PAGE_REF,
)
from pdf2audiobook.document.labels import (
    HEADING as HEADING,
)
from pdf2audiobook.document.labels import (
    LABEL_NUMBER as LABEL_NUMBER,
)
from pdf2audiobook.document.labels import (
    LABEL_PROSE as LABEL_PROSE,
)
from pdf2audiobook.document.labels import (
    LABELLED_NUMBER as LABELLED_NUMBER,
)
from pdf2audiobook.document.labels import (
    NUMBERED_LABEL as NUMBERED_LABEL,
)
from pdf2audiobook.document.labels import (
    PAGE_NUMBER as PAGE_NUMBER,
)
from pdf2audiobook.document.labels import (
    PAGE_REFERENCE_END as PAGE_REFERENCE_END,
)
from pdf2audiobook.document.labels import (
    ROMAN as ROMAN,
)
from pdf2audiobook.document.labels import (
    WRAPPED_LINE_END as WRAPPED_LINE_END,
)
from pdf2audiobook.document.labels import (
    _label_key as _label_key,
)
from pdf2audiobook.document.labels import (
    _loose_key as _loose_key,
)
from pdf2audiobook.document.labels import (
    _ordinal_value as _ordinal_value,
)
from pdf2audiobook.document.labels import (
    _roman_value as _roman_value,
)
from pdf2audiobook.document.labels import (
    _title_key as _title_key,
)
from pdf2audiobook.document.labels import (
    bare_number as bare_number,
)
from pdf2audiobook.document.labels import (
    contents_label_title as contents_label_title,
)
from pdf2audiobook.document.labels import (
    is_heading_line as is_heading_line,
)
from pdf2audiobook.document.labels import (
    label_key as label_key,
)
from pdf2audiobook.document.labels import (
    label_number as label_number,
)
from pdf2audiobook.document.labels import (
    labelled_heading as labelled_heading,
)
from pdf2audiobook.document.labels import (
    roman_sequence_heading_indices as roman_sequence_heading_indices,
)
from pdf2audiobook.document.listing import is_list_line as is_list_line
from pdf2audiobook.document.narration import (
    footnote_anchor_edits as footnote_anchor_edits,
)
from pdf2audiobook.document.narration import (
    footnote_omit_edits as footnote_omit_edits,
)
from pdf2audiobook.document.narration import (
    place_footnotes as place_footnotes,
)
from pdf2audiobook.document.narration import (
    reflow_narration_lines as reflow_narration_lines,
)
from pdf2audiobook.document.narration import (
    render_chapter_narration as render_chapter_narration,
)
from pdf2audiobook.document.narration import (
    render_chapter_texts as render_chapter_texts,
)
from pdf2audiobook.document.pagination import (
    _AMBIGUOUS_NUMERALS as _AMBIGUOUS_NUMERALS,
)
from pdf2audiobook.document.pagination import (
    _ROMAN_TITLE as _ROMAN_TITLE,
)
from pdf2audiobook.document.pagination import (
    PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT as PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT,
)
from pdf2audiobook.document.pagination import (
    _number_value as _number_value,
)
from pdf2audiobook.document.pagination import (
    _valid_bbox as _valid_bbox,
)
from pdf2audiobook.document.pagination import (
    _wordlike as _wordlike,
)
from pdf2audiobook.document.pagination import (
    pagination_cleanup as pagination_cleanup,
)
