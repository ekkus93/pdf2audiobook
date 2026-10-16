"""PDF inspection and provenance-preserving embedded-text / OCR extraction."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import fitz

from pdf2audiobook.config import Pdf as PdfSettings
from pdf2audiobook.errors import ExtractionError, InputError
from pdf2audiobook.models import DocumentBlock, SourceSpan
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


def _ocr_page_lines(page: fitz.Page, settings: PdfSettings) -> list[dict]:
    textpage = page.get_textpage_ocr(
        language=settings.ocr_language, dpi=settings.ocr_dpi, full=True
    )
    return _lines(page, textpage=textpage)


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
            or not isinstance(bbox, (list, tuple))
            or len(bbox) != 4
            or any(
                not isinstance(num, (int, float)) or not math.isfinite(num)
                for num in bbox
            )
            or not isinstance(size, (int, float))
            or not math.isfinite(size)
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
        return _ocr_page_lines(page, settings)
    if input_sha256 is None:
        raise ValueError("OCR caching requires the source PDF SHA-256")
    key = fingerprint(
        "ocr-lines-v1", input_sha256, page_index,
        settings.ocr_language, settings.ocr_dpi,
        str(fitz.VersionBind), int(page.rotation),
    )
    target = cache_dir / (key + ".json")
    if target.is_file():
        try:
            parsed = json.loads(target.read_text(encoding="utf-8"))
            lines = _valid_cached_lines(parsed)
            if lines is not None:
                return lines
        except (OSError, UnicodeError, ValueError, TypeError):
            pass
    lines = _ocr_page_lines(page, settings)
    verified = _valid_cached_lines({"schema_version": 1, "lines": lines})
    if verified is not None:
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
            origin = "embedded"
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
            warnings.extend(
                page_review_warnings(page_lines, page_number=page_index + 1, origin=origin)
            )
            for line_index, line in enumerate(page_lines):
                ident = f"p{page_index + 1:05d}-l{line_index + 1:05d}"
                bounds = line["bbox"]
                bbox = tuple(float(n) for n in bounds) if bounds else None
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
                        kind="heading"
                        if re.match(
                            r"^(?:chapter\s+[\divxlcdm]+|prologue|epilogue|"
                            r"introduction|preface|part\s+[\divxlcdm]+)\b",
                            line["text"],
                            re.IGNORECASE,
                        )
                        else "unknown",
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
