"""Conservative identification of running headers, footers and folios.

The steps live in `page_numbers`, `page_geometry`, `page_candidates` and `sequences`; this
module holds `pagination_cleanup`, the entry point, and re-exports every name those modules define,
so existing imports keep working."""

from __future__ import annotations

from pdf2audiobook.config import Pdf as PdfSettings
from pdf2audiobook.document.page_candidates import (
    _LIST_LABEL as _LIST_LABEL,
)
from pdf2audiobook.document.page_candidates import (
    _PROSE_CLOSERS as _PROSE_CLOSERS,
)
from pdf2audiobook.document.page_candidates import (
    _PROSE_OPENERS as _PROSE_OPENERS,
)
from pdf2audiobook.document.page_candidates import (
    _SENTENCE_ENDINGS as _SENTENCE_ENDINGS,
)
from pdf2audiobook.document.page_candidates import (
    _VERSE_REFERENCE as _VERSE_REFERENCE,
)
from pdf2audiobook.document.page_candidates import (
    _body_phrase as _body_phrase,
)
from pdf2audiobook.document.page_candidates import (
    _Candidates as _Candidates,
)
from pdf2audiobook.document.page_candidates import _collect_candidates, _Pagination
from pdf2audiobook.document.page_candidates import (
    _extended_prose as _extended_prose,
)
from pdf2audiobook.document.page_candidates import (
    _list_label as _list_label,
)
from pdf2audiobook.document.page_candidates import (
    _NumberedEntry as _NumberedEntry,
)
from pdf2audiobook.document.page_candidates import (
    _protected_kind as _protected_kind,
)
from pdf2audiobook.document.page_candidates import (
    _quoted_or_dialogue as _quoted_or_dialogue,
)
from pdf2audiobook.document.page_candidates import (
    _record_candidate as _record_candidate,
)
from pdf2audiobook.document.page_candidates import (
    _Series as _Series,
)
from pdf2audiobook.document.page_candidates import (
    _speaker_label_or_reference as _speaker_label_or_reference,
)
from pdf2audiobook.document.page_candidates import (
    _unconfirmed_numeral as _unconfirmed_numeral,
)
from pdf2audiobook.document.page_geometry import (
    _adjacent_body_line as _adjacent_body_line,
)
from pdf2audiobook.document.page_geometry import (
    _continuous_with_body as _continuous_with_body,
)
from pdf2audiobook.document.page_geometry import _page_geometry, _running_heads
from pdf2audiobook.document.page_geometry import (
    _PageGeometry as _PageGeometry,
)
from pdf2audiobook.document.page_geometry import (
    _valid_bbox as _valid_bbox,
)
from pdf2audiobook.document.page_numbers import (
    _AMBIGUOUS_NUMERALS as _AMBIGUOUS_NUMERALS,
)
from pdf2audiobook.document.page_numbers import (
    _ROMAN_TITLE as _ROMAN_TITLE,
)
from pdf2audiobook.document.page_numbers import (
    CANONICAL_ROMAN as CANONICAL_ROMAN,
)
from pdf2audiobook.document.page_numbers import (
    CHAPTER_WORD as CHAPTER_WORD,
)
from pdf2audiobook.document.page_numbers import (
    LABELLED_NUMBER as LABELLED_NUMBER,
)
from pdf2audiobook.document.page_numbers import (
    PAGE_NUMBER as PAGE_NUMBER,
)
from pdf2audiobook.document.page_numbers import (
    PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT as PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT,
)
from pdf2audiobook.document.page_numbers import (
    RUNNING_FOLIO as RUNNING_FOLIO,
)
from pdf2audiobook.document.page_numbers import (
    _aligned_folios as _aligned_folios,
)
from pdf2audiobook.document.page_numbers import (
    _aligned_number_positions as _aligned_number_positions,
)
from pdf2audiobook.document.page_numbers import (
    _number_value as _number_value,
)
from pdf2audiobook.document.page_numbers import (
    _running_parts as _running_parts,
)
from pdf2audiobook.document.page_numbers import (
    _titled as _titled,
)
from pdf2audiobook.document.page_numbers import (
    _wordlike as _wordlike,
)
from pdf2audiobook.document.sequences import (
    _confirmed_number as _confirmed_number,
)
from pdf2audiobook.document.sequences import (
    _find_sequences,
    _flag_ambiguity,
    _labels_disagree,
    _rank_band_numerals,
    _removal_reason,
    _select_sequences,
)
from pdf2audiobook.document.sequences import (
    _repeated_in_margin as _repeated_in_margin,
)
from pdf2audiobook.models import CleanupEdit, DocumentBlock


def pagination_cleanup(
    blocks: list[DocumentBlock],
    sizes: list[tuple[float, float]],
    settings: PdfSettings,
    *,
    page_labels: list[str | None] | None = None,
    warnings: list[str] | None = None,
    review_reasons: set[str] | None = None,
) -> list[CleanupEdit]:
    """Remove only corroborated pagination patterns confined to margin bands.

    Steps, in order: page geometry, running heads, margin candidates (after
    the fail-closed rules), numeral ranking within each band, page-number
    sequences, sequence selection, the page-label check and the edits.
    """
    geometry = _page_geometry(blocks, sizes, page_labels)
    running_titles, body_text = _running_heads(blocks, geometry)
    found = _collect_candidates(blocks, geometry, running_titles, body_text)
    preferred_numeric, ambiguous_numeric_bands = _rank_band_numerals(found, geometry)
    if ambiguous_numeric_bands:
        _flag_ambiguity(
            "Equally positioned margin numerals retained; verify page-number candidates",
            warnings,
            review_reasons,
        )
    sequential_pages, qualifying_sequences = _find_sequences(
        found, preferred_numeric, ambiguous_numeric_bands, geometry
    )
    series_at_page, selected_sequences, ambiguous_sequence_pages = _select_sequences(
        qualifying_sequences, found, geometry
    )
    if ambiguous_sequence_pages:
        _flag_ambiguity(
            "Multiple page-number sequences retained; verify pagination", warnings, review_reasons
        )
    if warnings is not None and _labels_disagree(
        selected_sequences, qualifying_sequences, geometry
    ):
        warnings.append("Printed page numbers disagree with PDF page labels")
    pagination = _Pagination(
        sequential_pages,
        series_at_page,
        selected_sequences,
        ambiguous_numeric_bands,
        ambiguous_sequence_pages,
    )
    edits = []
    for block, band in found.blocks.values():
        reason = _removal_reason(block, band, found, pagination, running_titles, geometry, settings)
        if reason is None:
            continue
        edits.append(
            CleanupEdit(
                block_id=block.id,
                original=block.text,
                replacement="",
                reason=reason,
                confidence=0.98,
                accepted=True,
            )
        )
    return edits
