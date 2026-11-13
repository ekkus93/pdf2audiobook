"""PDF inspection and provenance-preserving embedded-text / OCR extraction."""

from __future__ import annotations

import math
import os
import re
import sys
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import pymupdf

from pdf2audiobook.config import Pdf as PdfSettings
from pdf2audiobook.errors import ExtractionError, InputError
from pdf2audiobook.models import DocumentBlock, SourceSpan
from pdf2audiobook.pdf_layout import (
    _background_only,
    _classify_block_kind,
    _footnote_line_indices,
    _lines,
    _page_visuals,
    _PageVisuals,
    _positive_finite_number,
    _special_material_warnings,
    _table_regions,
    page_review_warnings,
)
from pdf2audiobook.pdf_ocr import (
    _apply_ocr_fallback,
    _page_ocr_strategy,
)
from pdf2audiobook.pdf_ocr import (
    missing_ocr_languages as missing_ocr_languages,
)
from pdf2audiobook.pdf_ocr import (
    tesseract_languages as tesseract_languages,
)
from pdf2audiobook.reading_order import merge_line_fragments, order_two_columns
from pdf2audiobook.special_material import (
    caption_line_indices,
    equation_line_indices,
    vector_artwork_warnings,
)
from pdf2audiobook.workspace import digest_file

# PyMuPDF prints advisory messages to stdout, which would corrupt --json
# reports. Route its messages to stderr and skip the layout-package advert.
pymupdf.set_messages(stream=sys.stderr)
pymupdf.no_recommend_layout()


@dataclass
class ExtractedDocument:
    title: str
    author: str | None
    toc: list[list]
    spans: list[SourceSpan]
    blocks: list[DocumentBlock]
    warnings: list[str]
    page_sizes: list[tuple[float, float]]
    page_labels: list[str | None] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)


@runtime_checkable
class DocumentExtractor(Protocol):
    """Replaceable PDF backend: page inspection plus provenance-preserving extraction."""

    name: str

    def inspect(self, source: Path, password_env: str | None = None) -> dict:
        """Return content-free document metadata, outline and page geometry."""

    def extract(
        self,
        source: Path,
        settings: PdfSettings,
        *,
        ocr_cache_dir: Path | None = None,
        source_sha256: str | None = None,
    ) -> ExtractedDocument:
        """Return source spans and ordered blocks, with OCR only where needed."""


class PyMuPDFExtractor:
    """Default extractor: PyMuPDF text geometry with Tesseract OCR fallback."""

    name = "pymupdf"

    def inspect(self, source: Path, password_env: str | None = None) -> dict:
        return inspect_pdf(source, password_env=password_env)

    def extract(
        self,
        source: Path,
        settings: PdfSettings,
        *,
        ocr_cache_dir: Path | None = None,
        source_sha256: str | None = None,
    ) -> ExtractedDocument:
        return extract_pdf(
            source, settings, ocr_cache_dir=ocr_cache_dir, source_sha256=source_sha256
        )


def _open(source: Path, password_env: str | None = None) -> pymupdf.Document:
    if not source.is_file() or source.suffix.lower() not in {".pdf", ".epub"}:
        raise InputError("not a readable PDF or EPUB book; verify input path and permissions")
    try:
        document = pymupdf.open(source)
        if document.needs_pass:
            password = os.environ.get(password_env, "") if password_env else ""
            if not password or not document.authenticate(password):
                document.close()
                raise InputError(
                    "PDF requires a valid password; set --pdf-password-env "
                    "to the name of an environment variable holding the password"
                )
        return document
    except InputError:
        raise
    except Exception:
        # PDF parsers may echo document paths or embedded content in errors.
        raise InputError("cannot open PDF; verify file integrity and permissions") from None


def inspect_pdf(source: Path, password_env: str | None = None) -> dict:
    with _open(source, password_env) as document:
        try:
            reflowable = bool(getattr(document, "is_reflowable", False))
            return {
                "title": document.metadata.get("title") or source.stem,
                "author": document.metadata.get("author") or None,
                "pages": len(document),
                "outline": document.get_toc(),
                "page_label_rules": [] if reflowable else document.get_page_labels(),
                # PyMuPDF text bounding boxes use the unrotated page coordinate
                # space, even when the viewer displays a rotated page.
                "page_rotations": [page.rotation for page in document],
                "page_sizes": [_inspection_page_size(page) for page in document],
                "page_labels": [
                    _inspection_label(page, index) for index, page in enumerate(document)
                ],
                # Content-free counts only: how much selectable text each page
                # carries and how many images, i.e. where OCR may be needed.
                "embedded_text": _embedded_text_summary([page for page in document]),
            }
        except Exception:
            # Malformed PDF metadata or backend diagnostics can echo private
            # document paths or content; inspection is read-only and fail-closed.
            raise ExtractionError("Failed to inspect PDF metadata or page geometry") from None


def _inspection_label(page: pymupdf.Page, index: int) -> str:
    try:
        return page.get_label() or str(index + 1)
    except Exception:
        # Page labels are advisory; fall back to the physical page number.
        return str(index + 1)


def _embedded_text_summary(pages: list[pymupdf.Page]) -> dict:
    characters = []
    images = []
    for page in pages:
        characters.append(sum(not char.isspace() for char in page.get_text("text")))
        images.append(len(page.get_images(full=False)))
    return {
        "pages_with_text": sum(count > 0 for count in characters),
        "pages_without_text": sum(count == 0 for count in characters),
        "image_only_pages": sum(
            count == 0 and image > 0 for count, image in zip(characters, images)
        ),
        "characters_per_page": characters,
        "images_per_page": images,
    }


def _inspection_page_size(page: pymupdf.Page) -> tuple[float, float]:
    """Require usable, finite PDF dimensions even for metadata-only inspection."""
    width = _positive_finite_number(page.cropbox.width)
    height = _positive_finite_number(page.cropbox.height)
    if width is None or height is None:
        raise ValueError("invalid PDF page geometry")
    return width, height


def _finite_bbox(bounds: object) -> tuple[float, float, float, float] | None:
    if isinstance(bounds, (tuple, list)) and len(bounds) == 4:
        if all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            for value in bounds
        ):
            x0, y0, x1, y1 = (float(value) for value in bounds)
            if x0 <= x1 and y0 <= y1:
                return (x0, y0, x1, y1)
    return None


def _build_page_blocks(
    lines: list[dict],
    *,
    page_index: int,
    page_label: str,
    origin: Literal["embedded", "ocr"],
    order_offset: int,
    table_regions: list[tuple[float, float, float, float]],
    footnote_indices: set[int],
    caption_indices: set[int],
    equation_indices: set[int],
) -> tuple[list[SourceSpan], list[DocumentBlock]]:
    """Build source-aligned spans and classified blocks for one extracted page."""
    spans: list[SourceSpan] = []
    blocks: list[DocumentBlock] = []
    marker_re = re.compile(r"^\s*(\d+|[A-Za-z]|[ivxlcdm]+)[.)]\s+", re.I)
    marked = [(marker_re.match(str(line.get("text", ""))), line) for line in lines]
    sizes = sorted(
        float(line["size"]) for line in lines if isinstance(line.get("size"), (int, float))
    )
    typical_size = sizes[(len(sizes) - 1) // 2] if sizes else 0.0
    for line_index, line in enumerate(lines):
        ident = f"p{page_index + 1:05d}-l{line_index + 1:05d}"
        bbox = _finite_bbox(line["bbox"])
        parts = line.get("parts") or [line]
        span_ids = [ident] + [f"{ident}-f{n:03d}" for n in range(2, len(parts) + 1)]
        for span_id, part in zip(span_ids, parts):
            spans.append(
                SourceSpan(
                    id=span_id,
                    page_index=page_index,
                    page_label=page_label,
                    text=part["text"],
                    bbox=bbox if part is line else _finite_bbox(part.get("bbox")),
                    origin=origin,
                    font=part.get("font"),
                    font_size=part.get("size"),
                )
            )
        marker = marked[line_index][0]
        display_heading = (
            marker is not None
            and typical_size > 0
            and float(line["size"]) >= typical_size * 1.35
            and not line["text"].rstrip().endswith((".", "?", "!", ",", ";", ":"))
        )
        kind = _classify_block_kind(
            line["text"],
            line_index,
            bbox,
            table_regions,
            footnote_indices,
            caption_indices,
            equation_indices,
            previous_text=(str(lines[line_index - 1].get("text", "")) if line_index else None),
            next_text=(
                str(lines[line_index + 1].get("text", "")) if line_index + 1 < len(lines) else None
            ),
            display_heading=display_heading,
        )
        blocks.append(
            DocumentBlock(
                id=ident,
                span_ids=span_ids,
                text=line["text"],
                page_index=page_index,
                bbox=bbox,
                font_size=line["size"],
                order=order_offset + len(blocks),
                kind=kind,
            )
        )
    return spans, blocks


@dataclass
class _ExtractionRun:
    """Settings and accumulated output for one document extraction.

    `spans`, `blocks`, `warnings`, `review_reasons`, `sizes` and `page_labels`
    grow page by page in document order and become the `ExtractedDocument`.
    """

    settings: PdfSettings
    ocr_cache_dir: Path | None
    source_sha256: str | None
    reflowable: bool
    explicit_page_labels: bool
    spans: list[SourceSpan] = field(default_factory=list)
    blocks: list[DocumentBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    sizes: list[tuple[float, float]] = field(default_factory=list)
    page_labels: list[str | None] = field(default_factory=list)
    reflowable_labels_noted: bool = False

    def note_damaged_source(self) -> None:
        """Require review for a damaged source, once."""
        if "damaged_source" not in self.review_reasons:
            self.review_reasons.append("damaged_source")


@dataclass
class _PageAnnotations:
    """Line indices of the special material found on one page."""

    table_regions: list[tuple[float, float, float, float]]
    caption_indices: set[int]
    footnote_indices: set[int]
    equation_indices: set[int]


def _start_extraction(
    document: Any,
    source: Path,
    settings: PdfSettings,
    ocr_cache_dir: Path | None,
    source_sha256: str | None,
) -> tuple[_ExtractionRun, list[list], str, str | None]:
    """Validate the opened document and read its outline, metadata and label flag.

    Returns the run state, the outline, the title and the author.
    """
    warnings: list[str] = []
    review_reasons: list[str] = []
    if len(document) == 0:
        raise ExtractionError("Book has no extractable pages")
    try:
        repaired = bool(getattr(document, "is_repaired", False))
    except Exception:
        repaired = True
    if repaired:
        warnings.append("source PDF was damaged and repaired; verify page coverage")
        review_reasons.append("damaged_source")
    reflowable = bool(getattr(document, "is_reflowable", False))
    if reflowable:
        warnings.append(
            "EPUB pages use generated reflowable layout; page numbers can vary by renderer"
        )
    if ocr_cache_dir is not None and source_sha256 is None:
        source_sha256 = digest_file(source)
    try:
        toc = document.get_toc()
        metadata = document.metadata
        title = metadata.get("title") or source.stem
        author = metadata.get("author") or None
    except Exception:
        # PyMuPDF parser failures can include embedded text or file paths.
        raise ExtractionError("Failed to read PDF outline or metadata") from None
    try:
        explicit_page_labels = bool(document.get_page_labels())
    except Exception:
        explicit_page_labels = False
    run = _ExtractionRun(
        settings=settings,
        ocr_cache_dir=ocr_cache_dir,
        source_sha256=source_sha256,
        reflowable=reflowable,
        explicit_page_labels=explicit_page_labels,
        warnings=warnings,
        review_reasons=review_reasons,
    )
    return run, toc, title, author


def _load_page(run: _ExtractionRun, document: Any, page_index: int) -> Any | None:
    """Load one page, or record it as unloadable and return None."""
    load_page = getattr(document, "load_page", None)
    if callable(load_page):
        try:
            return load_page(page_index)
        except Exception:
            run.warnings.append(f"Page {page_index + 1}: could not be loaded; verify coverage")
            run.note_damaged_source()
            run.sizes.append((0.0, 0.0))
            return None
    return next(islice(iter(document), page_index, page_index + 1))


def _page_size(page: Any, page_index: int) -> tuple[float, float]:
    """The page's cropbox size, refusing unreadable or invalid geometry."""
    # page.get_text() coordinates are unrotated, unlike page.rect.
    # Margin cleanup must use the same coordinate system as spans.
    try:
        width = float(page.cropbox.width)
        height = float(page.cropbox.height)
    except Exception:
        # Untrusted page geometry can include document paths/content
        # in parser exceptions. Fail before source-block creation.
        raise ExtractionError(f"Page {page_index + 1}: cannot read PDF page geometry") from None
    if not (math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0):
        raise ExtractionError(f"Page {page_index + 1}: invalid PDF page geometry")
    return width, height


def _no_text_reason(run: _ExtractionRun, page: Any, visuals: _PageVisuals) -> str:
    """Explain why a page without OCR has no text, flagging possible damage."""
    if run.settings.ocr == "never":
        return "OCR disabled"
    if visuals.drawings_unavailable:
        run.note_damaged_source()
        return "drawing information unavailable; verify coverage"
    if (
        run.reflowable
        and visuals.image_count
        and len(visuals.drawings) == visuals.drawing_count
        and _background_only(page.rect, visuals.drawings)
    ):
        # An EPUB cover or plate: an image on a page-sized background fill.
        return "image-only page; the image is not narrated"
    if visuals.drawing_count:
        run.note_damaged_source()
        return "drawings present but not text-like; verify coverage"
    return "no text or drawings found"


def _page_text_lines(
    run: _ExtractionRun, page: Any, page_index: int
) -> tuple[list[dict], Literal["embedded", "ocr"], _PageVisuals]:
    """Read a page's embedded lines, falling back to OCR where its strategy says so.

    Returns the merged lines, their origin and the page's visuals.
    """
    settings = run.settings
    try:
        page_lines = _lines(page)
    except Exception:
        # Suppress parser exception details that may include book content.
        raise ExtractionError(
            f"Failed to extract embedded text from PDF page {page_index + 1}; check PDF integrity"
        ) from None
    visuals = _page_visuals(page)
    usable, quality_issue, use_ocr, strategy_warnings = _page_ocr_strategy(
        page, page_lines, settings, page_index + 1, visuals
    )
    run.warnings.extend(strategy_warnings)
    origin: Literal["embedded", "ocr"] = "embedded"
    if use_ocr:
        page_lines, origin, ocr_warnings = _apply_ocr_fallback(
            page,
            page_lines,
            settings,
            cache_dir=run.ocr_cache_dir,
            input_sha256=run.source_sha256,
            page_index=page_index,
            quality_issue=quality_issue,
        )
        run.warnings.extend(ocr_warnings)
    if not page_lines and not use_ocr:
        reason = _no_text_reason(run, page, visuals)
        run.warnings.append(f"Page {page_index + 1}: no readable text ({reason})")
    return merge_line_fragments(page_lines), origin, visuals


def _annotate_page(
    run: _ExtractionRun,
    page: Any,
    page_lines: list[dict],
    page_index: int,
    *,
    origin: Literal["embedded", "ocr"],
    visuals: _PageVisuals,
    width: float,
    height: float,
) -> tuple[list[dict], _PageAnnotations]:
    """Find tables, artwork, special material, reading order, captions, notes and equations.

    Returns the lines in reading order and the indices of special material.
    """
    warnings = run.warnings
    page_number = page_index + 1
    # Preserve table cell text and annotate only contained blocks.
    table_regions, table_warnings = _table_regions(page, page_number=page_number)
    warnings.extend(table_warnings)
    warnings.extend(
        vector_artwork_warnings(
            page,
            page_number=page_number,
            drawings=visuals.drawings,
            unavailable=visuals.drawings_unavailable,
            drawing_count=visuals.drawing_count,
        )
    )
    # Surface non-prose material without changing the raw transcript.
    warnings.extend(
        _special_material_warnings(page, page_lines, page_number=page_number, visuals=visuals)
    )
    # Diagnose the original extraction order before changing it.
    warnings.extend(page_review_warnings(page_lines, page_number=page_number, origin=origin))
    page_lines, reordered = order_two_columns(page_lines, width)
    if reordered:
        warnings.append(
            f"Page {page_number}: reconstructed two-column reading order; "
            "review the transcript against the source page"
        )
    caption_indices, caption_warnings = caption_line_indices(
        page,
        page_lines,
        table_regions,
        page_number=page_number,
        image_info=visuals.images,
        drawings=visuals.drawings,
    )
    warnings.extend(caption_warnings)
    footnote_indices = _footnote_line_indices(
        page_lines,
        page_height=height,
        table_regions=table_regions,
    )
    equation_indices, equation_warnings = equation_line_indices(
        page_lines,
        page_number=page_number,
    )
    warnings.extend(equation_warnings)
    if footnote_indices:
        warnings.append(
            f"Page {page_number}: {len(footnote_indices)} "
            "likely footnote anchor(s)/continuation line(s) classified; verify against PDF"
        )
    return page_lines, _PageAnnotations(
        table_regions, caption_indices, footnote_indices, equation_indices
    )


def _page_label(run: _ExtractionRun, page: Any, page_index: int) -> str:
    """The page's printed label, recorded when the document has explicit labels."""
    try:
        page_label = page.get_label() or str(page_index + 1)
        if run.explicit_page_labels:
            run.page_labels[page_index] = page_label
    except Exception:
        # Page labels are advisory; keep the transcript and provenance.
        page_label = str(page_index + 1)
        if not run.reflowable:
            run.warnings.append(
                f"Page {page_index + 1}: could not read PDF page label; using physical page number"
            )
        elif not run.reflowable_labels_noted:
            # Generated EPUB pages never have labels: say so once, not per page.
            run.reflowable_labels_noted = True
            run.warnings.append(
                "EPUB pages have no printed page labels; physical page numbers are used"
            )
    return page_label


def _extract_page(run: _ExtractionRun, document: Any, page_index: int) -> None:
    """Extract one page's spans and blocks into the run."""
    run.page_labels.append(None)
    page = _load_page(run, document, page_index)
    if page is None:
        return
    width, height = _page_size(page, page_index)
    run.sizes.append((width, height))
    page_lines, origin, visuals = _page_text_lines(run, page, page_index)
    page_lines, annotations = _annotate_page(
        run,
        page,
        page_lines,
        page_index,
        origin=origin,
        visuals=visuals,
        width=width,
        height=height,
    )
    page_label = _page_label(run, page, page_index)
    page_spans, page_blocks = _build_page_blocks(
        page_lines,
        page_index=page_index,
        page_label=page_label,
        origin=origin,
        order_offset=len(run.blocks),
        table_regions=annotations.table_regions,
        footnote_indices=annotations.footnote_indices,
        caption_indices=annotations.caption_indices,
        equation_indices=annotations.equation_indices,
    )
    run.spans.extend(page_spans)
    run.blocks.extend(page_blocks)


def extract_pdf(
    source: Path,
    settings: PdfSettings,
    *,
    ocr_cache_dir: Path | None = None,
    source_sha256: str | None = None,
    progress: Any = None,
) -> ExtractedDocument:
    """Extract all pages, using OCR only for pages lacking meaningful embedded text.

    Steps: open and validate the document, then per page load it, choose its
    strategy and build its lines (with the OCR fallback), annotate special
    material and reading order, read its label and build its blocks.
    """
    with _open(source, settings.password_env) as document:
        run, toc, title, author = _start_extraction(
            document, source, settings, ocr_cache_dir, source_sha256
        )
        page_progress = (
            progress.stage("Extracting pages", len(document), "page")
            if progress is not None
            else None
        )
        for page_index in range(len(document)):
            if page_progress is not None and page_index:
                page_progress.advance()  # the previous page is finished
            _extract_page(run, document, page_index)
        if page_progress is not None:
            page_progress.advance()  # the final page
            page_progress.close()
        return ExtractedDocument(
            title=title,
            author=author,
            toc=toc,
            spans=run.spans,
            blocks=run.blocks,
            warnings=run.warnings,
            page_sizes=run.sizes,
            page_labels=run.page_labels,
            review_reasons=run.review_reasons,
        )
