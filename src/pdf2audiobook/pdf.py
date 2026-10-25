"""PDF inspection and provenance-preserving embedded-text / OCR extraction."""

from __future__ import annotations

import math
import os
import re
import shutil
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import islice
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

import pymupdf

from pdf2audiobook.config import Pdf as PdfSettings
from pdf2audiobook.document.structure import is_heading_line, is_list_line
from pdf2audiobook.errors import ExtractionError, InputError
from pdf2audiobook.jsonio import load_bounded_json
from pdf2audiobook.models import DocumentBlock, SourceSpan
from pdf2audiobook.reading_order import merge_line_fragments, order_two_columns
from pdf2audiobook.special_material import (
    _valid_box,
    caption_line_indices,
    equation_line_indices,
    vector_artwork_warnings,
)
from pdf2audiobook.workspace import digest_file, fingerprint, write_json

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


def _positive_finite_number(value: object) -> float | None:
    """Convert advisory PDF numeric metadata without trusting its magnitude."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


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


def _lines(page: pymupdf.Page, textpage: pymupdf.TextPage | None = None) -> list[dict]:
    structure = page.get_text("dict", sort=True, textpage=textpage)
    extracted = []
    for region in structure["blocks"]:
        if "lines" not in region:
            continue
        for line in region["lines"]:
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            bbox = line.get("bbox")
            largest = max(
                (_positive_finite_number(span.get("size")) or 0.0 for span in spans),
                default=0.0,
            )
            font = spans[0].get("font") if spans else None
            extracted.append({"text": text, "bbox": bbox, "font": font, "size": largest})
    return extracted


def page_review_warnings(lines: list[dict], *, page_number: int, origin: str) -> list[str]:
    """Flag suspicious extraction without silently discarding any source text.

    These are review heuristics, not Tesseract confidence scores. In particular,
    horizontally separated text at matching heights may be two columns whose
    reading order cannot be established reliably from sorted PDF lines alone.
    """
    warnings: list[str] = []
    text = " ".join(line["text"] for line in lines)
    if (
        text.count("\ufffd") >= 2
        or sum(ord(char) < 32 and char not in "\t\n\r" for char in text) >= 2
    ):
        warnings.append(
            f"Page {page_number}: suspicious replacement/control characters; "
            "review extracted text against the PDF"
        )
    if origin == "ocr" and lines and len(text.strip()) < 24:
        warnings.append(
            f"Page {page_number}: OCR produced very little text; "
            "verify recognition and page coverage"
        )

    aligned_separate_lines = 0
    for first, second in zip(lines, lines[1:]):
        left, right = _valid_box(first.get("bbox")), _valid_box(second.get("bbox"))
        if left is None or right is None:
            continue
        overlap = min(left[3], right[3]) - max(left[1], right[1])
        shortest_height = min(left[3] - left[1], right[3] - right[1])
        separated = left[2] + 8 < right[0] or right[2] + 8 < left[0]
        if shortest_height > 0 and overlap > shortest_height * 0.5 and separated:
            aligned_separate_lines += 1
    if aligned_separate_lines >= 2:
        warnings.append(
            f"Page {page_number}: possible multi-column or side-by-side text; "
            "verify reading order before narration"
        )
    return warnings


def _table_regions(
    page: pymupdf.Page, *, page_number: int
) -> tuple[list[tuple[float, float, float, float]], list[str]]:
    """Locate high-confidence table rectangles without altering their text.

    The geometry is used only to label contained source blocks for review.
    Never discard text, synthesize cell descriptions or infer reading order.
    """
    detector = getattr(page, "find_tables", None)
    if not callable(detector):
        return [], []
    try:
        found = detector()
        boxes: list[tuple[float, float, float, float]] = []
        # Table geometry is advisory. Third-party iterators and bbox objects
        # must not hang extraction or exhaust memory on malformed documents.
        for index, table in enumerate(islice(found.tables, 501)):
            if index == 500:
                return boxes, [
                    f"Page {page_number}: table inspection truncated; "
                    "review complex layouts manually"
                ]
            bounds = _valid_box(getattr(table, "bbox", None))
            if bounds is not None:
                boxes.append(bounds)
    except Exception:
        return [], [
            f"Page {page_number}: table detection unavailable; review complex layouts manually"
        ]
    if not boxes:
        return [], []
    return boxes, [
        f"Page {page_number}: possible table detected; "
        "verify cell order and narration; source text preserved"
    ]


def _inside_table(
    bbox: tuple[float, float, float, float] | None,
    regions: list[tuple[float, float, float, float]],
) -> bool:
    if bbox is None:
        return False
    return any(
        bbox[0] >= x0 - 2 and bbox[1] >= y0 - 2 and bbox[2] <= x1 + 2 and bbox[3] <= y1 + 2
        for x0, y0, x1, y1 in regions
    )


def _special_material_warnings(
    page: pymupdf.Page, lines: list[dict], *, page_number: int
) -> list[str]:
    """Report likely non-prose content without deleting or inventing narration.

    Image presence, small bottom-margin text and mathematical symbols are
    evidence for review, not proof of an image caption, footnote or equation.
    """
    result: list[str] = []
    try:
        images = page.get_image_info()
        if not isinstance(images, (list, tuple)):
            raise ValueError("uninspectable image metadata")
        if len(images) > 5000:
            result.append(
                f"Page {page_number}: embedded image inventory truncated; "
                "review complex image layouts manually"
            )
        boxes = []
        for info in images[:5000]:
            if not isinstance(info, dict):
                raise ValueError("uninspectable image metadata")
            box = _valid_box(info.get("bbox"))
            if box is None:
                raise ValueError("invalid image geometry")
            boxes.append(box)
        page_area = max(1.0, float(page.cropbox.width * page.cropbox.height))
        large_image = any(
            (box[2] - box[0]) * (box[3] - box[1]) / page_area >= 0.01 for box in boxes
        )
    except Exception:
        result.append(
            f"Page {page_number}: could not inspect embedded images; "
            "verify non-text content manually"
        )
    else:
        if large_image:
            result.append(
                f"Page {page_number}: embedded image detected; "
                "OCR does not describe figures or diagrams; review manually"
            )
    # Font and bbox metadata is advisory; reject unrepresentable numeric
    # values rather than allowing malformed PDF metadata to crash inspection.
    sizes = [
        size for line in lines if (size := _positive_finite_number(line.get("size"))) is not None
    ]
    if len(sizes) >= 3:
        median_size = statistics.median(sizes)
        height = _positive_finite_number(page.cropbox.height)
        if height is not None and any(
            (bounds := _valid_box(line.get("bbox"))) is not None
            and (size := _positive_finite_number(line.get("size"))) is not None
            and size <= 0.78 * median_size
            and bounds[1] >= 0.7 * height
            for line in lines
        ):
            result.append(
                f"Page {page_number}: possible small-font footnote or endnote; "
                "preserved verbatim for review"
            )
    math_symbols = set("∑∫√≈≤≥∞∂∇∈∉⊂⊆≠∝")
    if any(math_symbols.intersection(line["text"]) for line in lines):
        result.append(
            f"Page {page_number}: mathematical notation detected; "
            "verify spoken rendering against source"
        )
    return result


def _footnote_line_indices(
    lines: list[dict],
    *,
    page_height: float,
    table_regions: list[tuple[float, float, float, float]],
) -> set[int]:
    """Conservatively tag numbered small-type notes separated from body prose.

    Never classify by small font or bottom position alone: a short numbered
    list or ordinary paragraph near the page bottom must remain body text.
    Uncertain notes are preserved as untyped source blocks for review.
    """
    # Geometry is advisory and may originate in a malformed PDF or adapter.
    # A nonfinite page size or unrepresentable coordinate must not interrupt
    # extraction or cause an unverified footnote classification.
    if isinstance(page_height, bool):
        return set()
    try:
        height = float(page_height)
    except (TypeError, ValueError, OverflowError):
        return set()
    if not math.isfinite(height) or height <= 0:
        return set()

    validated: list[tuple[tuple[float, float, float, float] | None, float | None]] = []
    for line in lines:
        bounds = _valid_box(line.get("bbox"))
        raw_size = line.get("size")
        size: float | None = None
        if not isinstance(raw_size, bool) and isinstance(raw_size, (int, float)):
            try:
                candidate = float(raw_size)
            except (TypeError, ValueError, OverflowError):
                pass
            else:
                if math.isfinite(candidate) and candidate > 0:
                    size = candidate
        validated.append((bounds, size))

    body_sizes = [
        size
        for bounds, size in validated
        if bounds is not None and size is not None and bounds[1] < height * 0.65
    ]
    if len(body_sizes) < 2:
        return set()
    body_size = statistics.median(body_sizes)
    result: set[int] = set()
    for index, line in enumerate(lines):
        bounds, size = validated[index]
        text = line.get("text")
        if (
            bounds is None
            or size is None
            or size > 0.78 * body_size
            or bounds[1] < height * 0.70
            or _inside_table(bounds, table_regions)
            or not isinstance(text, str)
            or not re.match(r"^(?:\d{1,2}[.)]?|[*†‡])\s+\S", text)
        ):
            continue
        # Require a clear gap from preceding valid text, not merely small font.
        preceding_bottom = max(
            (
                other_bounds[3]
                for other_index, (other_bounds, _) in enumerate(validated)
                if other_index != index
                and other_bounds is not None
                and other_bounds[3] <= bounds[1]
            ),
            default=None,
        )
        if preceding_bottom is None or bounds[1] - preceding_bottom < max(18.0, body_size * 1.5):
            continue
        result.add(index)

    # Extend confirmed footnotes through adjacent, same-column small-type
    # continuation lines only. Never infer a note from small text alone.
    for anchor_index in sorted(result):
        anchor_box = validated[anchor_index][0]
        if anchor_box is None:
            continue
        previous_box = anchor_box
        for next_index in range(anchor_index + 1, len(lines)):
            if next_index in result:
                break
            item = lines[next_index]
            bounds, size = validated[next_index]
            text = item.get("text")
            if (
                bounds is None
                or size is None
                or size > 0.78 * body_size
                or not isinstance(text, str)
                or not text.strip()
                or bounds[1] < height * 0.70
                or _inside_table(bounds, table_regions)
            ):
                break
            if re.match(r"^(?:\d{1,2}[.)]?|[*†‡])\s+\S", text):
                break
            gap = bounds[1] - previous_box[3]
            overlap = min(bounds[2], previous_box[2]) - max(bounds[0], previous_box[0])
            if (
                not -2.0 <= gap <= max(8.0, 0.8 * body_size)
                or overlap <= 0
                or abs(bounds[0] - anchor_box[0]) > max(24.0, 2 * body_size)
            ):
                break
            result.add(next_index)
            previous_box = bounds
    return result | _footnote_zone(lines, validated, height, body_size, table_regions)


_NOTE_ANCHOR = re.compile(r"^(?:\d{1,3}[.)]?\s+\S|\d{1,3}(?=[A-Z])|[*†‡§]\s*\S)")


def _footnote_zone(
    lines: list[dict],
    validated: list[tuple[tuple[float, float, float, float] | None, float | None]],
    height: float,
    body_size: float,
    table_regions: list[tuple[float, float, float, float]],
) -> set[int]:
    """Tag the run of small-type notes that closes a page.

    Scanned books set notes only slightly smaller than the body and close
    beneath it, so a per-line test misses them. Instead require the whole
    run: it starts low on the page after a visible gap, holds at least one
    note marker, is set in smaller type overall and continues to the foot
    of the page. Unnumbered lines at its top continue a note from the
    previous page. A small-type passage followed by body text is not a zone.
    """
    # Unverifiable geometry anywhere on the page: keep every line as text.
    if any(bounds is None or size is None for bounds, size in validated):
        return set()
    boxes = {
        index: (bounds, size)
        for index, (bounds, size) in enumerate(validated)
        if bounds is not None and size is not None
    }
    order = sorted(boxes, key=lambda index: boxes[index][0][1])
    position = len(order) - 1
    # Big-type furniture (a printer's signature mark) may sit under the notes.
    while position >= 0 and boxes[order[position]][1] > 0.95 * body_size:
        if boxes[order[position]][0][1] < height * 0.85:
            return set()
        position -= 1
    zone: list[int] = []
    while position >= 0:
        index = order[position]
        bounds, size = boxes[index]
        text = lines[index].get("text")
        if (
            size > 0.95 * body_size
            or bounds[1] < height * 0.5
            or not isinstance(text, str)
            or not text.strip()
            or _inside_table(bounds, table_regions)
        ):
            break
        if zone:
            # Notes are one tight, single-column run; a gap or a side column
            # ends it.
            below = boxes[zone[-1]][0]
            overlap = min(bounds[2], below[2]) - max(bounds[0], below[0])
            if below[1] - bounds[3] > max(8.0, body_size) or overlap <= 0:
                return set()
        zone.append(index)
        position -= 1
    if not zone or position < 0:
        return set()
    above_bounds, above_size = boxes[order[position]]
    top = boxes[zone[-1]][0]
    if above_size <= 0.95 * body_size or top[1] - above_bounds[3] < max(4.0, 0.5 * body_size):
        return set()
    if statistics.median(boxes[index][1] for index in zone) > 0.86 * body_size:
        return set()
    if not any(_NOTE_ANCHOR.match(str(lines[index]["text"]).strip()) for index in zone):
        return set()
    return set(zone)


def _embedded_text_quality(lines: list[dict]) -> tuple[bool, str | None]:
    """Conservatively reject damaged text layers before choosing OCR in auto mode.

    Quantity alone is insufficient: broken font mappings can yield long strings
    of replacement glyphs or embedded controls. Do not replace a mostly valid
    text layer because of a single isolated bad character.
    """
    text = " ".join(line["text"] for line in lines)
    printable = sum(not char.isspace() for char in text)
    if printable < 24:
        return False, "too little selectable text"
    damaged = sum(char == "\ufffd" or (ord(char) < 32 and char not in "\t\n\r") for char in text)
    if damaged >= max(2, math.ceil(printable * 0.05)):
        return False, "damaged selectable-text mapping"
    return True, None


def _page_has_dominant_raster(page: pymupdf.Page) -> bool:
    """Find scan-sized raster coverage, including pages assembled from tiles.

    Compute the union of visible image rectangles so overlapping artwork cannot
    be counted multiple times. Require plausible pixel density on each tile:
    tiny decorative images stretched across a page are not scan evidence.
    This is only an OCR trigger; the transcript still needs coverage review.
    """
    try:
        # Image bounds use unrotated page coordinates even when page.rect
        # reflects a 90/270-degree viewer rotation. Compare in one frame.
        page_bounds = pymupdf.Rect(0, 0, page.cropbox.width, page.cropbox.height)
        page_area = float(page_bounds.get_area())
        if page_area <= 0:
            return False
        images = page.get_image_info()
        # Bound worst-case geometric work on adversarial image-heavy PDFs.
        if len(images) > 256:
            return False
        regions = []
        for image in images:
            width, height = image.get("width", 0), image.get("height", 0)
            if width < 250 or height < 250:
                continue
            bounds = pymupdf.Rect(image["bbox"])
            corners = (bounds.x0, bounds.y0, bounds.x1, bounds.y1)
            if not all(math.isfinite(float(value)) for value in corners):
                continue
            if bounds.width <= 0 or bounds.height <= 0:
                continue
            if width / bounds.width < 1.0 or height / bounds.height < 1.0:
                continue
            visible = bounds & page_bounds
            if visible.get_area() > 0:
                regions.append(visible)
        if not regions:
            return False

        x_coords = sorted({edge for rect in regions for edge in (rect.x0, rect.x1)})
        covered = 0.0
        for left, right in zip(x_coords, x_coords[1:]):
            intervals = sorted(
                (rect.y0, rect.y1) for rect in regions if rect.x0 < right and rect.x1 > left
            )
            if not intervals:
                continue
            start, end = intervals[0]
            covered_height = 0.0
            for y0, y1 in intervals[1:]:
                if y0 > end:
                    covered_height += end - start
                    start, end = y0, y1
                else:
                    end = max(end, y1)
            covered_height += end - start
            covered += (right - left) * covered_height
            if covered >= page_area * 0.65:
                return True
    except (KeyError, TypeError, ValueError, RuntimeError, OverflowError, ZeroDivisionError):
        # Uninspectable image metadata must not replace selectable text.
        return False
    return False


@lru_cache(maxsize=1)
def _ocr_engine_version() -> str:
    """Bind cached recognition to the installed Tesseract engine build.

    Failure to query the CLI is nonfatal: PyMuPDF can use its own Tesseract
    integration. The PyMuPDF version remains an independent cache component.
    """
    if shutil.which("tesseract") is None:
        return "tesseract-cli-unavailable"
    try:
        result = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "tesseract-cli-unknown"

    if result.returncode != 0:
        return "tesseract-cli-unknown"
    # A successful CLI invocation may still produce no version text.
    return next(
        (
            line.strip()
            for line in (result.stdout + "\n" + result.stderr).splitlines()
            if line.strip()
        ),
        "tesseract-cli-unknown",
    )


def _ocr_page_lines(page: pymupdf.Page, settings: PdfSettings) -> list[dict]:
    # OCR is performed in the PDF page's unrotated coordinate system, just
    # like embedded text and span bboxes. PyMuPDF's OCR otherwise rasterizes
    # the page rotation and can pass sideways text to Tesseract, which returns
    # plausible-looking garbage rather than a reliable transcription.
    rotation = page.rotation
    try:
        if rotation:
            page.set_rotation(0)
        textpage = page.get_textpage_ocr(
            language=settings.ocr_language, dpi=settings.ocr_dpi, full=True
        )
        return _lines(page, textpage=textpage)
    finally:
        if rotation:
            page.set_rotation(rotation)


def _valid_cached_lines(data: object) -> list[dict] | None:
    """Reject incomplete or malformed cache entries; never trust saved OCR blindly."""
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return None
    lines = data.get("lines")
    if not isinstance(lines, list) or len(lines) > 200000:
        return None
    checked = []
    for line in lines:
        if not isinstance(line, dict):
            return None
        text = line.get("text")
        bbox = line.get("bbox")
        font = line.get("font")
        size = line.get("size")
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > 1_000_000
            or not isinstance(bbox, (list, tuple))
            or len(bbox) != 4
            or any(
                isinstance(num, bool)
                or not isinstance(num, (int, float))
                # Check magnitude before converting arbitrary-size integers
                # to float inside isfinite (which can raise OverflowError).
                or abs(num) > 1_000_000
                or not math.isfinite(num)
                for num in bbox
            )
            or bbox[0] >= bbox[2]
            or bbox[1] >= bbox[3]
            or isinstance(size, bool)
            or not isinstance(size, (int, float))
            or size < 0
            or size > 1_000_000
            or not math.isfinite(size)
            or font is not None
            and not isinstance(font, str)
        ):
            return None
        checked.append({"text": text, "bbox": list(bbox), "font": font, "size": size})
    return checked


class _InvalidOCRGeometry(ValueError):
    """Trusted, content-free failure from local OCR validation only."""


def _cached_ocr_lines(
    page: pymupdf.Page,
    settings: PdfSettings,
    *,
    cache_dir: Path | None,
    input_sha256: str | None,
    page_index: int,
) -> list[dict]:
    """Cache OCR by exact source bytes, page index, language, DPI and engine version.

    Cache files contain only local transcribed text. Invalid or unreadable data
    triggers a fresh OCR and an atomic replacement, never silent empty output.
    """
    if cache_dir is None:
        lines = _ocr_page_lines(page, settings)
        uncached_verified = _valid_cached_lines({"schema_version": 1, "lines": lines})
        if uncached_verified is None:
            raise _InvalidOCRGeometry(
                "invalid OCR line geometry or metadata; no cache entry written"
            )
        return uncached_verified
    if input_sha256 is None:
        raise ValueError("OCR caching requires the source PDF SHA-256")
    key = fingerprint(
        "ocr-lines-v1",
        input_sha256,
        page_index,
        settings.ocr_language,
        settings.ocr_dpi,
        str(pymupdf.VersionBind),
        _ocr_engine_version(),
        int(page.rotation),
    )
    target = cache_dir / (key + ".json")
    if target.is_file():
        parsed = load_bounded_json(target, max_bytes=32 * 1024 * 1024, max_depth=64)
        cached_lines = _valid_cached_lines(parsed)
        if cached_lines:
            return cached_lines
    lines = _ocr_page_lines(page, settings)
    verified = _valid_cached_lines({"schema_version": 1, "lines": lines})
    # Invalid fresh OCR must not silently enter the transcript or poison
    # a future cache hit. An empty result is allowed but never cached.
    if verified is None:
        raise _InvalidOCRGeometry("invalid OCR line geometry or metadata; no cache entry written")
    if verified:
        write_json(target, {"schema_version": 1, "lines": verified})
    # Return the same validated, allowlisted fields on cache miss and hit.
    # Never leak incidental OCR-engine metadata into downstream stages.
    return verified


def extract_pdf(
    source: Path,
    settings: PdfSettings,
    *,
    ocr_cache_dir: Path | None = None,
    source_sha256: str | None = None,
) -> ExtractedDocument:
    """Extract all pages, using OCR only for pages lacking meaningful embedded text."""
    spans: list[SourceSpan] = []
    blocks: list[DocumentBlock] = []
    warnings: list[str] = []
    sizes: list[tuple[float, float]] = []
    page_labels: list[str | None] = []
    with _open(source, settings.password_env) as document:
        if len(document) == 0:
            raise ExtractionError("Book has no extractable pages")
        try:
            repaired = bool(getattr(document, "is_repaired", False))
        except Exception:
            repaired = True
        if repaired:
            warnings.append("source PDF was damaged and repaired; verify page coverage")
        if bool(getattr(document, "is_reflowable", False)):
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
        for page_index in range(len(document)):
            page_labels.append(None)
            load_page = getattr(document, "load_page", None)
            if callable(load_page):
                try:
                    page = load_page(page_index)
                except Exception:
                    warnings.append(f"Page {page_index + 1}: could not be loaded; verify coverage")
                    continue
            else:
                page = next(islice(iter(document), page_index, page_index + 1))
            # page.get_text() coordinates are unrotated, unlike page.rect.
            # Margin cleanup must use the same coordinate system as spans.
            try:
                width = float(page.cropbox.width)
                height = float(page.cropbox.height)
            except Exception:
                # Untrusted page geometry can include document paths/content
                # in parser exceptions. Fail before source-block creation.
                raise ExtractionError(
                    f"Page {page_index + 1}: cannot read PDF page geometry"
                ) from None
            if not (math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0):
                raise ExtractionError(f"Page {page_index + 1}: invalid PDF page geometry")
            sizes.append((width, height))
            try:
                page_lines = _lines(page)
            except Exception:
                # Suppress parser exception details that may include book content.
                raise ExtractionError(
                    f"Failed to extract embedded text from PDF page {page_index + 1}; "
                    "check PDF integrity"
                ) from None
            usable, quality_issue = _embedded_text_quality(page_lines)
            # A scanned body can coexist with a short, perfectly valid
            # selectable heading. Character quality alone misses that body.
            if settings.ocr == "auto" and usable:
                printable = sum(not char.isspace() for line in page_lines for char in line["text"])
                if printable < 120 and _page_has_dominant_raster(page):
                    usable = False
                    quality_issue = "sparse selectable text over dominant raster"
                    warnings.append(
                        f"Page {page_index + 1}: sparse selectable text overlays "
                        "a large raster; attempting OCR and requiring coverage review"
                    )
            auto_ocr_needed = not usable and (
                quality_issue == "damaged selectable-text mapping"
                or _page_has_dominant_raster(page)
            )
            use_ocr = settings.ocr == "always" or (settings.ocr == "auto" and auto_ocr_needed)
            if settings.ocr == "auto" and quality_issue == "damaged selectable-text mapping":
                warnings.append(
                    f"Page {page_index + 1}: damaged embedded text layer; "
                    "using OCR instead of unreliable selectable text"
                )
            origin: Literal["embedded", "ocr"] = "embedded"
            if use_ocr:
                # Retain the original text layer until OCR actually produces
                # text. A short selectable heading can be the only prose on
                # a page, and an empty OCR result must not silently erase it.
                embedded_lines = page_lines
                try:
                    page_lines = _cached_ocr_lines(
                        page,
                        settings,
                        cache_dir=ocr_cache_dir,
                        input_sha256=source_sha256,
                        page_index=page_index,
                    )
                except _InvalidOCRGeometry:
                    # Only our own validator can produce this safe, fixed error.
                    # Never inspect or echo arbitrary OCR backend diagnostics.
                    raise ExtractionError(
                        f"Page {page_index + 1}: invalid OCR line geometry or metadata"
                    ) from None
                except Exception:
                    # OCR failures can include recognized text and local paths.
                    raise ExtractionError(
                        f"OCR failed on PDF page {page_index + 1}; verify Tesseract "
                        "and the configured OCR language"
                    ) from None
                origin = "ocr"
                if not page_lines:
                    warnings.append(f"Page {page_index + 1}: OCR produced no text")
                    if settings.ocr == "auto" and embedded_lines:
                        page_lines = embedded_lines
                        origin = "embedded"
                        warnings.append(
                            f"Page {page_index + 1}: retained unverified embedded text "
                            "after empty automatic OCR; review against the PDF"
                        )
                elif (
                    settings.ocr == "auto"
                    and quality_issue
                    in (
                        "too little selectable text",
                        "sparse selectable text over dominant raster",
                    )
                    and embedded_lines
                ):
                    # A nonempty OCR result can still omit a short genuine
                    # heading or other selectable text. Do not merge both text
                    # layers (which may duplicate prose); require explicit review
                    # when the original line sequence is absent from OCR.
                    selectable = " ".join(
                        " ".join(line["text"].split()) for line in embedded_lines
                    ).casefold()
                    recognized = " ".join(
                        " ".join(line["text"].split()) for line in page_lines
                    ).casefold()
                    if selectable and selectable not in recognized:
                        warnings.append(
                            f"Page {page_index + 1}: automatic OCR did not reproduce "
                            "short selectable text; review page coverage before narration"
                        )
                    elif (
                        quality_issue == "sparse selectable text over dominant raster"
                        and selectable
                        and recognized == selectable
                    ):
                        # Recognition may have recovered only the selectable
                        # overlay, leaving the scan's prose completely unread.
                        warnings.append(
                            f"Page {page_index + 1}: OCR found no additional text "
                            "beyond the selectable overlay on a large raster; "
                            "verify scanned body coverage manually"
                        )
            if not page_lines and not use_ocr:
                reason = "OCR disabled" if settings.ocr == "never" else "OCR not needed"
                warnings.append(f"Page {page_index + 1}: no readable text ({reason})")
            page_lines = merge_line_fragments(page_lines)
            # Preserve table cell text and annotate only contained blocks.
            table_regions, table_warnings = _table_regions(page, page_number=page_index + 1)
            warnings.extend(table_warnings)
            warnings.extend(vector_artwork_warnings(page, page_number=page_index + 1))
            # Surface non-prose material without changing the raw transcript.
            warnings.extend(
                _special_material_warnings(page, page_lines, page_number=page_index + 1)
            )
            # Diagnose the original extraction order before changing it.
            warnings.extend(
                page_review_warnings(page_lines, page_number=page_index + 1, origin=origin)
            )
            page_lines, reordered = order_two_columns(page_lines, width)
            if reordered:
                warnings.append(
                    f"Page {page_index + 1}: reconstructed two-column reading order; "
                    "review the transcript against the source page"
                )
            caption_indices, caption_warnings = caption_line_indices(
                page,
                page_lines,
                table_regions,
                page_number=page_index + 1,
            )
            warnings.extend(caption_warnings)
            footnote_indices = _footnote_line_indices(
                page_lines,
                page_height=height,
                table_regions=table_regions,
            )
            equation_indices, equation_warnings = equation_line_indices(
                page_lines,
                page_number=page_index + 1,
            )
            warnings.extend(equation_warnings)
            if footnote_indices:
                warnings.append(
                    f"Page {page_index + 1}: {len(footnote_indices)} "
                    "likely footnote anchor(s)/continuation line(s) classified; verify against PDF"
                )
            try:
                page_label = page.get_label() or str(page_index + 1)
                if explicit_page_labels:
                    page_labels[page_index] = page_label
            except Exception:
                # Page labels are advisory; keep the transcript and provenance.
                page_label = str(page_index + 1)
                warnings.append(
                    f"Page {page_index + 1}: could not read PDF page label; "
                    "using physical page number"
                )
            for line_index, line in enumerate(page_lines):
                ident = f"p{page_index + 1:05d}-l{line_index + 1:05d}"
                bbox = _finite_bbox(line["bbox"])
                # A merged printed line keeps one source span per fragment.
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
                blocks.append(
                    DocumentBlock(
                        id=ident,
                        span_ids=span_ids,
                        text=line["text"],
                        page_index=page_index,
                        bbox=bbox,
                        font_size=line["size"],
                        order=len(blocks),
                        kind=(
                            "table"
                            if _inside_table(bbox, table_regions)
                            else "footnote"
                            if line_index in footnote_indices
                            else "caption"
                            if line_index in caption_indices
                            else "equation"
                            if line_index in equation_indices
                            else "list"
                            if is_list_line(line["text"])
                            else "heading"
                            if is_heading_line(line["text"])
                            else "unknown"
                        ),
                    )
                )
        return ExtractedDocument(
            title=title,
            author=author,
            toc=toc,
            spans=spans,
            blocks=blocks,
            warnings=warnings,
            page_sizes=sizes,
            page_labels=page_labels,
        )


def tesseract_languages() -> list[str] | None:
    """List installed Tesseract language packs without opening or exporting PDF text."""
    if shutil.which("tesseract") is None:
        return None
    try:
        run = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if run.returncode != 0:
        return []
    output = run.stdout + "\n" + run.stderr
    return sorted(
        {
            line.strip()
            for line in output.splitlines()
            if line.strip() and not line.startswith("List of available languages")
        }
    )


def missing_ocr_languages(configured: str, installed: list[str] | None) -> list[str]:
    if installed is None:
        return [lang for lang in configured.split("+") if lang]
    return sorted(set(configured.split("+")) - set(installed))
