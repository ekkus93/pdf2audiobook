"""PDF inspection and provenance-preserving embedded-text / OCR extraction."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import statistics
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import fitz  # type: ignore[import-untyped]

from pdf2audiobook.config import Pdf as PdfSettings
from pdf2audiobook.errors import ExtractionError, InputError
from pdf2audiobook.models import DocumentBlock, SourceSpan
from pdf2audiobook.reading_order import order_two_columns
from pdf2audiobook.special_material import (
    caption_line_indices,
    equation_line_indices,
    vector_artwork_warnings,
)
from pdf2audiobook.workspace import digest_file, fingerprint, write_json


@dataclass
class ExtractedDocument:
    title: str
    author: str | None
    toc: list[list]
    spans: list[SourceSpan]
    blocks: list[DocumentBlock]
    warnings: list[str]
    page_sizes: list[tuple[float, float]]


def _open(source: Path, password_env: str | None = None) -> fitz.Document:
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise InputError(f"not a readable PDF file: {source}")
    try:
        document = fitz.open(source)
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
    except Exception as exc:
        raise InputError(f"cannot open PDF: {exc}") from exc


def inspect_pdf(source: Path, password_env: str | None = None) -> dict:
    with _open(source, password_env) as document:
        return {
            "title": document.metadata.get("title") or source.stem,
            "author": document.metadata.get("author") or None,
            "pages": len(document),
            "outline": document.get_toc(),
            "page_label_rules": document.get_page_labels(),
            # PyMuPDF text bounding boxes use the unrotated page coordinate
            # space, even when the viewer displays a rotated page.
            "page_rotations": [page.rotation for page in document],
            "page_sizes": [
                (float(page.cropbox.width), float(page.cropbox.height))
                for page in document
            ],
        }


def _lines(page: fitz.Page, textpage: fitz.TextPage | None = None) -> list[dict]:
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
            largest = max((float(span.get("size", 0)) for span in spans), default=0)
            font = spans[0].get("font") if spans else None
            extracted.append(
                {"text": text, "bbox": bbox, "font": font, "size": largest}
            )
    return extracted



def page_review_warnings(
    lines: list[dict], *, page_number: int, origin: str
) -> list[str]:
    """Flag suspicious extraction without silently discarding any source text.

    These are review heuristics, not Tesseract confidence scores. In particular,
    horizontally separated text at matching heights may be two columns whose
    reading order cannot be established reliably from sorted PDF lines alone.
    """
    warnings: list[str] = []
    text = " ".join(line["text"] for line in lines)
    if text.count("\ufffd") >= 2 or sum(
        ord(char) < 32 and char not in "\t\n\r" for char in text
    ) >= 2:
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
        left, right = first.get("bbox"), second.get("bbox")
        if not left or not right:
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
    page: fitz.Page, *, page_number: int
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
        boxes = []
        for table in found.tables:
            bounds = tuple(float(n) for n in table.bbox)
            if len(bounds) != 4 or not all(math.isfinite(n) for n in bounds):
                continue
            if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                continue
            boxes.append(bounds)
    except Exception:
        return [], [
            f"Page {page_number}: table detection unavailable; "
            "review complex layouts manually"
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
        bbox[0] >= x0 - 2 and bbox[1] >= y0 - 2
        and bbox[2] <= x1 + 2 and bbox[3] <= y1 + 2
        for x0, y0, x1, y1 in regions
    )


def _special_material_warnings(
    page: fitz.Page, lines: list[dict], *, page_number: int
) -> list[str]:
    """Report likely non-prose content without deleting or inventing narration.

    Image presence, small bottom-margin text and mathematical symbols are
    evidence for review, not proof of an image caption, footnote or equation.
    """
    result: list[str] = []
    try:
        images = page.get_image_info()
    except Exception:
        result.append(
            f"Page {page_number}: could not inspect embedded images; "
            "verify non-text content manually"
        )
    else:
        page_area = max(1.0, float(page.cropbox.width * page.cropbox.height))
        if any(
            isinstance(info.get("bbox"), (tuple, list))
            and len(info["bbox"]) == 4
            and max(0.0, info["bbox"][2] - info["bbox"][0])
            * max(0.0, info["bbox"][3] - info["bbox"][1]) / page_area >= 0.01
            for info in images
        ):
            result.append(
                f"Page {page_number}: embedded image detected; "
                "OCR does not describe figures or diagrams; review manually"
            )
    sizes = [
        float(line["size"]) for line in lines
        if isinstance(line.get("size"), (int, float))
        and float(line["size"]) > 0
    ]
    if len(sizes) >= 3:
        median_size = statistics.median(sizes)
        height = float(page.cropbox.height)
        if any(
            isinstance(line.get("bbox"), (tuple, list))
            and len(line["bbox"]) == 4
            and isinstance(line.get("size"), (int, float))
            and 0 < float(line["size"]) <= 0.78 * median_size
            and line["bbox"][1] >= 0.7 * height
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
    lines: list[dict], *, page_height: float,
    table_regions: list[tuple[float, float, float, float]],
) -> set[int]:
    """Conservatively tag numbered small-type notes separated from body prose.

    Never classify by small font or bottom position alone: a short numbered
    list or ordinary paragraph near the page bottom must remain body text.
    Uncertain notes are preserved as untyped source blocks for review.
    """
    body_sizes = [
        float(line["size"]) for line in lines
        if line.get("bbox") and line["bbox"][1] < page_height * 0.65
        and isinstance(line.get("size"), (int, float))
        and math.isfinite(float(line["size"])) and line["size"] > 0
    ]
    if len(body_sizes) < 2:
        return set()
    body_size = statistics.median(body_sizes)
    result: set[int] = set()
    for index, line in enumerate(lines):
        bounds = line.get("bbox")
        size = line.get("size")
        if (
            not bounds or len(bounds) != 4
            or not isinstance(size, (int, float))
            or not math.isfinite(float(size))
            or size <= 0 or size > 0.78 * body_size
            or bounds[1] < page_height * 0.70
            or _inside_table(tuple(bounds), table_regions)
            or not re.match(r"^(?:\d{1,2}[.)]?|[*†‡])\s+\S", line["text"])
        ):
            continue
        # A genuine footnote is typically separated from the main text.
        # Require clear whitespace above the note, not just a font change.
        preceding_bottom = max(
            (other["bbox"][3] for other in lines
             if other is not line and other.get("bbox")
             and other["bbox"][3] <= bounds[1]),
            default=None,
        )
        if preceding_bottom is None or bounds[1] - preceding_bottom < max(18.0, body_size * 1.5):
            continue
        result.add(index)

    # Extend confirmed footnotes through adjacent, same-column small-type
    # continuation lines only. Never infer a note from small text alone.
    for anchor_index in sorted(result):
        anchor_box = lines[anchor_index]["bbox"]
        previous_box = anchor_box
        for next_index in range(anchor_index + 1, len(lines)):
            if next_index in result:
                break
            item = lines[next_index]
            bounds, size, text = item.get("bbox"), item.get("size"), item.get("text")
            if (
                not bounds or len(bounds) != 4
                or not isinstance(size, (int, float)) or isinstance(size, bool)
                or not math.isfinite(float(size))
                or size <= 0 or size > 0.78 * body_size
                or not isinstance(text, str) or not text.strip()
                or bounds[1] < page_height * 0.70
                or _inside_table(tuple(bounds), table_regions)
            ):
                break
            # A fresh number/symbol needs separate anchor evidence.
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
    return result



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
    damaged = sum(
        char == "\ufffd" or (ord(char) < 32 and char not in "\t\n\r")
        for char in text
    )
    if damaged >= max(2, math.ceil(printable * 0.05)):
        return False, "damaged selectable-text mapping"
    return True, None


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
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "tesseract-cli-unknown"
    if result.returncode != 0:
        return "tesseract-cli-unknown"
    # A successful CLI invocation may still produce no version text.
    return next(
        (line.strip() for line in (result.stdout + "\n" + result.stderr).splitlines()
         if line.strip()),
        "tesseract-cli-unknown",
    )


def _ocr_page_lines(page: fitz.Page, settings: PdfSettings) -> list[dict]:
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
                or not math.isfinite(num)
                or abs(num) > 1_000_000
                for num in bbox
            )
            or bbox[0] >= bbox[2]
            or bbox[1] >= bbox[3]
            or isinstance(size, bool)
            or not isinstance(size, (int, float))
            or not math.isfinite(size)
            or size < 0
            or font is not None and not isinstance(font, str)
        ):
            return None
        checked.append({
            "text": text, "bbox": bbox, "font": font, "size": size
        })
    return checked


def _cached_ocr_lines(
    page: fitz.Page, settings: PdfSettings, *,
    cache_dir: Path | None, input_sha256: str | None, page_index: int,
) -> list[dict]:
    """Cache OCR by exact source bytes, page index, language, DPI and engine version.

    Cache files contain only local transcribed text. Invalid or unreadable data
    triggers a fresh OCR and an atomic replacement, never silent empty output.
    """
    if cache_dir is None:
        lines = _ocr_page_lines(page, settings)
        uncached_verified = _valid_cached_lines({"schema_version": 1, "lines": lines})
        if uncached_verified is None:
            raise ValueError("invalid OCR line geometry or metadata; no cache entry written")
        return uncached_verified
    if input_sha256 is None:
        raise ValueError("OCR caching requires the source PDF SHA-256")
    key = fingerprint(
        "ocr-lines-v1", input_sha256, page_index,
        settings.ocr_language, settings.ocr_dpi,
        str(fitz.VersionBind), _ocr_engine_version(), int(page.rotation),
    )
    target = cache_dir / (key + ".json")
    if target.is_file():
        try:
            # Avoid reading arbitrarily large or attacker-modified cache entries.
            if target.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("oversized OCR cache")
            parsed = json.loads(target.read_text(encoding="utf-8"))
            cached_lines = _valid_cached_lines(parsed)
            if cached_lines:
                return cached_lines
        except (OSError, UnicodeError, ValueError, TypeError):
            pass
    lines = _ocr_page_lines(page, settings)
    verified = _valid_cached_lines({"schema_version": 1, "lines": lines})
    # Invalid fresh OCR must not silently enter the transcript or poison
    # a future cache hit. An empty result is allowed but never cached.
    if verified is None:
        raise ValueError("invalid OCR line geometry or metadata; no cache entry written")
    if verified:
        write_json(target, {"schema_version": 1, "lines": verified})
    return lines


def extract_pdf(
    source: Path, settings: PdfSettings, *,
    ocr_cache_dir: Path | None = None, source_sha256: str | None = None,
) -> ExtractedDocument:
    """Extract all pages, using OCR only for pages lacking meaningful embedded text."""
    spans: list[SourceSpan] = []
    blocks: list[DocumentBlock] = []
    warnings: list[str] = []
    sizes: list[tuple[float, float]] = []
    with _open(source, settings.password_env) as document:
        if len(document) == 0:
            raise ExtractionError("PDF has no pages")
        if ocr_cache_dir is not None and source_sha256 is None:
            source_sha256 = digest_file(source)
        toc = document.get_toc()
        title = document.metadata.get("title") or source.stem
        author = document.metadata.get("author") or None
        for page_index, page in enumerate(document):
            # page.get_text() coordinates are unrotated, unlike page.rect.
            # Margin cleanup must use the same coordinate system as spans.
            sizes.append((float(page.cropbox.width), float(page.cropbox.height)))
            try:
                page_lines = _lines(page)
            except Exception as exc:
                raise ExtractionError(
                    f"Failed to extract embedded text from PDF page {page_index + 1}: "
                    f"{type(exc).__name__}"
                ) from exc
            usable, quality_issue = _embedded_text_quality(page_lines)
            use_ocr = settings.ocr == "always" or (
                settings.ocr == "auto" and not usable
            )
            if settings.ocr == "auto" and quality_issue == "damaged selectable-text mapping":
                warnings.append(
                    f"Page {page_index + 1}: damaged embedded text layer; "
                    "using OCR instead of unreliable selectable text"
                )
            origin: Literal["embedded", "ocr"] = "embedded"
            if use_ocr:
                try:
                    page_lines = _cached_ocr_lines(
                        page, settings, cache_dir=ocr_cache_dir,
                        input_sha256=source_sha256, page_index=page_index,
                    )
                except Exception as exc:
                    raise ExtractionError(
                        f"OCR failed on PDF page {page_index + 1}; verify Tesseract "
                        f"and language '{settings.ocr_language}': {exc}"
                    ) from exc
                origin = "ocr"
                if not page_lines:
                    warnings.append(f"Page {page_index + 1}: OCR produced no text")
            if not page_lines and not use_ocr:
                warnings.append(f"Page {page_index + 1}: no readable text (OCR disabled)")
            # Preserve table cell text and annotate only contained blocks.
            table_regions, table_warnings = _table_regions(
                page, page_number=page_index + 1
            )
            warnings.extend(table_warnings)
            warnings.extend(vector_artwork_warnings(page, page_number=page_index + 1))
            # Surface non-prose material without changing the raw transcript.
            warnings.extend(
                _special_material_warnings(
                    page, page_lines, page_number=page_index + 1
                )
            )
            # Diagnose the original extraction order before changing it.
            warnings.extend(
                page_review_warnings(page_lines, page_number=page_index + 1, origin=origin)
            )
            page_lines, reordered = order_two_columns(
                page_lines, float(page.cropbox.width)
            )
            if reordered:
                warnings.append(
                    f"Page {page_index + 1}: reconstructed two-column reading order; "
                    "review the transcript against the source page"
                )
            caption_indices, caption_warnings = caption_line_indices(
                page, page_lines, table_regions, page_number=page_index + 1,
            )
            warnings.extend(caption_warnings)
            footnote_indices = _footnote_line_indices(
                page_lines, page_height=float(page.cropbox.height),
                table_regions=table_regions,
            )
            equation_indices, equation_warnings = equation_line_indices(
                page_lines, page_number=page_index + 1,
            )
            warnings.extend(equation_warnings)
            if footnote_indices:
                warnings.append(
                    f"Page {page_index + 1}: {len(footnote_indices)} "
                    "likely footnote anchor(s)/continuation line(s) classified; verify against PDF"
                )
            for line_index, line in enumerate(page_lines):
                ident = f"p{page_index + 1:05d}-l{line_index + 1:05d}"
                bounds = line["bbox"]
                bbox: tuple[float, float, float, float] | None = None
                if isinstance(bounds, (tuple, list)) and len(bounds) == 4:
                    if all(
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and math.isfinite(value)
                        for value in bounds
                    ):
                        x0, y0, x1, y1 = (float(value) for value in bounds)
                        if x0 <= x1 and y0 <= y1:
                            bbox = (x0, y0, x1, y1)
                spans.append(
                    SourceSpan(
                        id=ident,
                        page_index=page_index,
                        page_label=page.get_label() or str(page_index + 1),
                        text=line["text"],
                        bbox=bbox,
                        origin=origin,
                        font=line["font"],
                        font_size=line["size"],
                    )
                )
                blocks.append(
                    DocumentBlock(
                        id=ident,
                        span_ids=[ident],
                        text=line["text"],
                        page_index=page_index,
                        bbox=bbox,
                        font_size=line["size"],
                        order=len(blocks),
                        kind=(
                            "table" if _inside_table(bbox, table_regions)
                            else "footnote" if line_index in footnote_indices
                            else "caption" if line_index in caption_indices
                            else "equation" if line_index in equation_indices
                            else "heading" if re.match(
                                r"^(?:chapter\s+[\divxlcdm]+|prologue|epilogue|"
                                r"introduction|preface|part\s+[\divxlcdm]+)\b",
                                line["text"],
                                re.IGNORECASE,
                            )
                            else "unknown"
                        ),
                    )
                )
        return ExtractedDocument(
            title=title, author=author, toc=toc, spans=spans,
            blocks=blocks, warnings=warnings, page_sizes=sizes
        )



def tesseract_languages() -> list[str] | None:
    """List installed Tesseract language packs without opening or exporting PDF text."""
    if shutil.which("tesseract") is None:
        return None
    try:
        run = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if run.returncode != 0:
        return []
    output = run.stdout + "\n" + run.stderr
    return sorted({
        line.strip() for line in output.splitlines()
        if line.strip() and not line.startswith("List of available languages")
    })


def missing_ocr_languages(configured: str, installed: list[str] | None) -> list[str]:
    if installed is None:
        return [lang for lang in configured.split("+") if lang]
    return sorted(set(configured.split("+")) - set(installed))
