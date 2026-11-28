"""Numbered sequences of page numbers: finding them, choosing the ones that hold, and deciding removals."""

from __future__ import annotations

from collections import defaultdict

from pdf2audiobook.config import Pdf as PdfSettings
from pdf2audiobook.document.page_candidates import _Candidates, _Pagination, _Series
from pdf2audiobook.document.page_geometry import _PageGeometry
from pdf2audiobook.document.page_numbers import (
    PAGE_NUMBER,
    PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT,
    _aligned_folios,
    _aligned_number_positions,
    _number_value,
    _running_parts,
    _titled,
)
from pdf2audiobook.models import DocumentBlock


def _rank_band_numerals(
    found: _Candidates, geometry: _PageGeometry
) -> tuple[dict[tuple[str, int], set[tuple[int, str]]], set[tuple[str, int]]]:
    """Pick the edge-most numeral where one margin band on a page holds several.

    Returns the preferred (value, notation) per (band, page) and the
    (band, page) pairs whose numerals sit equally near the edge.
    """
    sizes = geometry.sizes
    # More than one candidate numeral in a single margin band on a page is
    # ambiguous. Non-candidates such as table cells are irrelevant here.
    numeric_counts: dict[tuple[str, int], int] = defaultdict(int)
    for block, band in found.blocks.values():
        if _number_value(block.text.strip()) is not None:
            numeric_counts[(band, block.page_index)] += 1
    preferred_numeric: dict[tuple[str, int], set[tuple[int, str]]] = defaultdict(set)
    ambiguous_numeric_bands: set[tuple[str, int]] = set()
    for band_page, count in numeric_counts.items():
        if count < 2:
            continue
        page = band_page[1]
        numerals = [
            (block, _number_value(block.text.strip()))
            for block, block_band in found.blocks.values()
            if block_band == band_page[0]
            and block.page_index == page
            and _number_value(block.text.strip()) is not None
            and block.bbox is not None
        ]
        ranked = sorted(
            (
                min(block.bbox[1], sizes[page][1] - block.bbox[3]),
                parsed,
            )
            for block, parsed in numerals
            if parsed is not None and block.bbox is not None
        )
        if ranked and (
            len(ranked) == 1 or ranked[1][0] - ranked[0][0] >= PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT
        ):
            preferred_numeric[band_page].add(ranked[0][1])
        else:
            ambiguous_numeric_bands.add(band_page)
    return preferred_numeric, ambiguous_numeric_bands


def _find_sequences(
    found: _Candidates,
    preferred_numeric: dict[tuple[str, int], set[tuple[int, str]]],
    ambiguous_numeric_bands: set[tuple[str, int]],
    geometry: _PageGeometry,
) -> tuple[dict[str, set[int]], dict[_Series, set[int]]]:
    """Find folios that continue onto the next page at an aligned position.

    Returns the pages in any sequence per band, and the pages of each
    sequence that qualifies for removal. Arabic numbers need two pages;
    Roman ones need three, and a third page whose label agrees.
    """
    sequential_pages: dict[str, set[int]] = defaultdict(set)
    qualifying_sequences: dict[_Series, set[int]] = defaultdict(set)
    for band, entries in found.numbered.items():
        entries = [
            entry
            for entry in entries
            if (band, entry[0]) not in ambiguous_numeric_bands
            and (
                (band, entry[0]) not in preferred_numeric
                or (entry[1], entry[3]) in preferred_numeric[(band, entry[0])]
            )
        ]
        by_key: dict[tuple[int, int, str], list[tuple[float, float] | None]] = defaultdict(list)
        for page, folio_number, position, notation in entries:
            by_key[(page, folio_number, notation)].append(position)
        for page, folio_number, position, notation in entries:
            successors = by_key.get((page + 1, folio_number + 1, notation), [])
            for next_position in successors:
                if not _aligned_folios(position, next_position):
                    continue
                current_y = found.vertical_positions.get((band, page, folio_number, notation), [])
                next_y = found.vertical_positions.get(
                    (band, page + 1, folio_number + 1, notation), []
                )
                if (
                    current_y
                    and next_y
                    and not any(
                        abs(first_y - second_y) <= 0.025
                        for first_y in current_y
                        for second_y in next_y
                    )
                ):
                    continue
                if notation == "arabic":
                    sequential_pages[band].update((page, page + 1))
                    qualifying_sequences[(band, folio_number - page, notation)].update(
                        (page, page + 1)
                    )
                else:
                    # Two-page Roman sequences may be section markers.
                    final_positions = by_key.get((page + 2, folio_number + 2, notation), [])
                    if any(_aligned_folios(next_position, final) for final in final_positions):
                        sequential_pages[band].update((page, page + 1, page + 2))
                        if geometry.label_matches(page + 2, folio_number + 2, notation):
                            qualifying_sequences[(band, folio_number - page, notation)].update(
                                (page, page + 1, page + 2)
                            )
    return sequential_pages, qualifying_sequences


def _select_sequences(
    qualifying_sequences: dict[_Series, set[int]],
    found: _Candidates,
    geometry: _PageGeometry,
) -> tuple[dict[int, set[_Series]], dict[int, set[_Series]], set[int]]:
    """Choose one sequence per page where several qualify.

    A sequence agreeing with the page label wins, then the one nearest the
    page edge; a tie leaves the page ambiguous. Returns the sequences at each
    page, the selected ones and the ambiguous pages.
    """
    sizes = geometry.sizes
    series_at_page: dict[int, set[_Series]] = defaultdict(set)
    for series, pages in qualifying_sequences.items():
        for page in pages:
            series_at_page[page].add(series)
    selected_sequences: dict[int, set[_Series]] = defaultdict(set)
    ambiguous_sequence_pages: set[int] = set()
    for page, series_set in series_at_page.items():
        if len(series_set) == 1:
            selected_sequences[page].update(series_set)
            continue
        ranked_series = []
        for series in series_set:
            band, offset, notation = series
            distances = []
            for block, block_band in found.blocks.values():
                parsed = _number_value(block.text.strip())
                if (
                    block_band == band
                    and block.page_index == page
                    and parsed == (page + offset, notation)
                    and block.bbox is not None
                ):
                    distances.append(min(block.bbox[1], sizes[page][1] - block.bbox[3]))
            if distances:
                ranked_series.append(
                    (
                        0 if geometry.label_matches(page, page + offset, notation) else 1,
                        min(distances),
                        series,
                    )
                )
        ranked_series.sort(key=lambda item: (item[0], item[1]))
        tied = False
        if len(ranked_series) > 1 and ranked_series[0][0] == ranked_series[1][0]:
            tied = ranked_series[1][1] - ranked_series[0][1] < PAGE_NUMBER_EDGE_TIE_TOLERANCE_PT
        if ranked_series and (len(ranked_series) == 1 or not tied):
            selected_sequences[page].add(ranked_series[0][2])
        else:
            ambiguous_sequence_pages.add(page)
    return series_at_page, selected_sequences, ambiguous_sequence_pages


def _labels_disagree(
    selected_sequences: dict[int, set[_Series]],
    qualifying_sequences: dict[_Series, set[int]],
    geometry: _PageGeometry,
) -> bool:
    """Whether any page of a chosen sequence disagrees with its PDF label."""
    chosen_sequences = {
        series for series_set in selected_sequences.values() for series in series_set
    }
    return geometry.page_labels is not None and any(
        not geometry.label_matches(page, page + offset, notation)
        for (_band, offset, notation) in chosen_sequences
        for page in qualifying_sequences[(_band, offset, notation)]
    )


def _flag_ambiguity(
    message: str, warnings: list[str] | None, review_reasons: set[str] | None
) -> None:
    """Warn that page numbers were kept, and require review."""
    if warnings is not None:
        warnings.append(message)
    if review_reasons is not None:
        review_reasons.add("ambiguous_page_numbers")


def _confirmed_number(block: DocumentBlock, band: str, pagination: _Pagination) -> bool:
    """Whether a numeral is part of the page's selected, unambiguous sequence."""
    return _confirmed_folio(block.text.strip(), block.page_index, band, pagination)


def _confirmed_folio(text: str, page: int, band: str, pagination: _Pagination) -> bool:
    """Whether `text`, a numeral on `page`, is part of that page's selected, unambiguous sequence."""
    parsed = _number_value(text)
    return (
        parsed is not None
        and (band, page) not in pagination.ambiguous_numeric_bands
        and page not in pagination.ambiguous_sequence_pages
        and page in pagination.sequential_pages[band]
        and (
            not pagination.series_at_page.get(page)
            or (band, parsed[0] - page, parsed[1]) in pagination.selected_sequences[page]
        )
    )


def _repeated_in_margin(
    block: DocumentBlock, band: str, title_key: str, found: _Candidates, geometry: _PageGeometry
) -> bool:
    """Whether the same margin text recurs at the same place on another page."""
    assert block.bbox is not None
    bbox = block.bbox
    # Repetition alone is insufficient: separate margin prose may recur
    # at unrelated horizontal or vertical positions on different pages.
    width, height = geometry.sizes[block.page_index]
    if not (width > 0 and height > 0):
        return False
    x_center = (bbox[0] + bbox[2]) / (2 * width)
    y_center = (bbox[1] + bbox[3]) / (2 * height)
    return any(
        page != block.page_index
        and _aligned_number_positions(x_center, other_x)
        and abs(y_center - other_y) <= 0.025
        for page, other_x, other_y in found.text_occurrences[(band, title_key)]
    )


def _removal_reason(
    block: DocumentBlock,
    band: str,
    found: _Candidates,
    pagination: _Pagination,
    running_titles: set[tuple[str, str]],
    geometry: _PageGeometry,
    settings: PdfSettings,
) -> str | None:
    """Why a candidate is removed, or None when the evidence is not enough."""
    if block.bbox is None:
        return None
    value, embedded_folio = _running_parts(block.text)
    if _confirmed_number(block, band, pagination) and settings.remove_page_numbers:
        return "sequential/repeated page number"
    # A running head's page number follows the pages. A number that doesn't ("turn 1" on
    # three pages, "turn 9" beside "turn 22") belongs to something else: labels at the top
    # of a figure that starts a page fell in the header band and repeated in place.
    if embedded_folio is not None and not _confirmed_folio(
        embedded_folio, block.page_index, band, pagination
    ):
        return None
    if (
        not PAGE_NUMBER.fullmatch(block.text.strip())
        and _titled(value)
        and (
            len(block.text.split()) >= 2
            or (block.kind == "heading" and (band, value) in running_titles)
        )
        and _repeated_in_margin(block, band, value, found, geometry)
        and (block.kind != "heading" or (band, value) in running_titles)
        and (
            (band == "header" and settings.remove_headers)
            or (band == "footer" and settings.remove_footers)
        )
    ):
        reason = "repeated running " + band
        if embedded_folio is not None:
            reason += " with page number"
        return reason
    return None
