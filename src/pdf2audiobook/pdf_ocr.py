"""OCR for PDF extraction: when a page needs OCR, the Tesseract engine and its
languages, the OCR line cache, and the fallback that replaces embedded text."""

from __future__ import annotations

import math
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Literal

import pymupdf

from pdf2audiobook.config import Pdf as PdfSettings
from pdf2audiobook.document.structure import is_heading_line
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.jsonio import load_bounded_json
from pdf2audiobook.pdf_layout import _lines, _PageVisuals
from pdf2audiobook.workspace import fingerprint, write_json


def _embedded_text_quality(lines: list[dict]) -> tuple[bool, str | None]:
    """Conservatively reject damaged text layers before choosing OCR in auto mode.

    Quantity alone is insufficient: broken font mappings can yield long strings
    of replacement glyphs or embedded controls. Do not replace a mostly valid
    text layer because of a single isolated bad character.
    """
    text = " ".join(line["text"] for line in lines)
    printable = sum(not char.isspace() for char in text)
    damaged = sum(char == "\ufffd" or (ord(char) < 32 and char not in "\t\n\r") for char in text)
    if damaged >= max(2, math.ceil(printable * 0.05)):
        return False, "damaged selectable-text mapping"
    if printable < 24:
        normalized = " ".join(text.split())
        if is_heading_line(normalized):
            return True, None
        return False, "too little selectable text"
    return True, None


def _page_ocr_strategy(
    page: pymupdf.Page,
    lines: list[dict],
    settings: PdfSettings,
    page_number: int,
    visuals: _PageVisuals | None = None,
) -> tuple[bool, str | None, bool, list[str]]:
    """Select embedded text or OCR for one page and describe the evidence."""
    usable, quality_issue = _embedded_text_quality(lines)
    warnings = []
    if settings.ocr == "auto" and usable:
        printable = sum(not char.isspace() for line in lines for char in line["text"])
        if printable < 120 and _page_has_dominant_raster(page, visuals):
            usable = False
            quality_issue = "sparse selectable text over dominant raster"
            warnings.append(
                f"Page {page_number}: sparse selectable text overlays "
                "a large raster; attempting OCR and requiring coverage review"
            )
    vector_text_page = (
        settings.ocr == "auto" and not usable and _page_has_dense_vector_art(page, visuals)
    )
    if vector_text_page:
        quality_issue = "dense vector artwork without usable text"
        warnings.append(
            f"Page {page_number}: dense vector artwork has no usable text; attempting OCR"
        )
    auto_ocr_needed = not usable and (
        quality_issue == "damaged selectable-text mapping"
        or _page_has_dominant_raster(page, visuals)
        or vector_text_page
    )
    use_ocr = settings.ocr == "always" or (settings.ocr == "auto" and auto_ocr_needed)
    if settings.ocr == "auto" and quality_issue == "damaged selectable-text mapping":
        warnings.append(
            f"Page {page_number}: damaged embedded text layer; "
            "using OCR instead of unreliable selectable text"
        )
    return usable, quality_issue, use_ocr, warnings


def _page_has_dominant_raster(page: pymupdf.Page, visuals: _PageVisuals | None = None) -> bool:
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
        images = visuals.images if visuals is not None else page.get_image_info()
        # Bound worst-case geometric work on adversarial image-heavy PDFs.
        if (visuals.image_count if visuals is not None else len(images)) > 256:
            return False
        regions = []
        for image in images:
            width, height = image.get("width", 0), image.get("height", 0)
            if width < 250 or height < 250:
                continue
            bounds = pymupdf.Rect(image["bbox"])
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


# A page of outlined text is a set of small filled paths, one per glyph. One
# outlined line of prose has more than this many; a rule or a logo has fewer.
_VECTOR_GLYPH_MIN_PATHS = 40


# A glyph path is no wider or taller than this fraction of the page.
_VECTOR_GLYPH_MAX_FRACTION = 0.06


# Dense decorative artwork (many paths of any size) covering this much of the
# page without any usable text is also sent to OCR.
_VECTOR_ARTWORK_MIN_PATHS = 100


_VECTOR_ARTWORK_MIN_COVERAGE = 0.15


def _page_has_dense_vector_art(page: pymupdf.Page, visuals: _PageVisuals | None = None) -> bool:
    """Detect drawing-only pages that may contain outlined text."""
    try:
        width = float(page.cropbox.width)
        height = float(page.cropbox.height)
        drawings = visuals.drawings if visuals is not None else page.get_drawings()
        if width <= 0 or height <= 0 or not isinstance(drawings, (list, tuple)):
            return False
        glyph_like = 0
        covered = 0.0
        for drawing in drawings:
            rect = drawing.get("rect")
            if rect is None:
                continue
            path_width = max(0.0, float(rect.width))
            path_height = max(0.0, float(rect.height))
            covered += path_width * path_height
            if (
                drawing.get("fill") is not None
                and 0 < path_width <= width * _VECTOR_GLYPH_MAX_FRACTION
                and 0 < path_height <= height * _VECTOR_GLYPH_MAX_FRACTION
            ):
                glyph_like += 1
        return glyph_like >= _VECTOR_GLYPH_MIN_PATHS or (
            len(drawings) >= _VECTOR_ARTWORK_MIN_PATHS
            and covered / (width * height) >= _VECTOR_ARTWORK_MIN_COVERAGE
        )
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, OverflowError):
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


def _apply_ocr_fallback(
    page: pymupdf.Page,
    embedded_lines: list[dict],
    settings: PdfSettings,
    *,
    cache_dir: Path | None,
    input_sha256: str | None,
    page_index: int,
    quality_issue: str | None,
) -> tuple[list[dict], Literal["embedded", "ocr"], list[str]]:
    """Run OCR when selected and retain the embedded fallback with review warnings."""
    page_number = page_index + 1
    warnings: list[str] = []
    try:
        lines = _cached_ocr_lines(
            page,
            settings,
            cache_dir=cache_dir,
            input_sha256=input_sha256,
            page_index=page_index,
        )
    except _InvalidOCRGeometry:
        raise ExtractionError(
            f"Page {page_number}: invalid OCR line geometry or metadata"
        ) from None
    except Exception:
        raise ExtractionError(
            f"OCR failed on PDF page {page_number}; verify Tesseract "
            "and the configured OCR language"
        ) from None
    origin: Literal["embedded", "ocr"] = "ocr"
    if not lines:
        warnings.append(f"Page {page_number}: OCR produced no text")
        if settings.ocr == "auto" and embedded_lines:
            lines = embedded_lines
            origin = "embedded"
            warnings.append(
                f"Page {page_number}: retained unverified embedded text "
                "after empty automatic OCR; review against the PDF"
            )
    elif (
        settings.ocr == "auto"
        and quality_issue
        in ("too little selectable text", "sparse selectable text over dominant raster")
        and embedded_lines
    ):
        selectable = " ".join(" ".join(line["text"].split()) for line in embedded_lines).casefold()
        recognized = " ".join(" ".join(line["text"].split()) for line in lines).casefold()
        if selectable and selectable not in recognized:
            warnings.append(
                f"Page {page_number}: automatic OCR did not reproduce "
                "short selectable text; review page coverage before narration"
            )
        elif (
            quality_issue == "sparse selectable text over dominant raster"
            and selectable
            and recognized == selectable
        ):
            warnings.append(
                f"Page {page_number}: OCR found no additional text "
                "beyond the selectable overlay on a large raster; "
                "verify scanned body coverage manually"
            )
    return lines, origin, warnings


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
