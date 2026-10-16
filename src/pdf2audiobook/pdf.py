"""PDF inspection and provenance-preserving embedded-text / OCR extraction."""
from __future__ import annotations

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


def extract_pdf(source: Path, settings: PdfSettings) -> ExtractedDocument:
    """Extract all pages, using OCR only for pages lacking meaningful embedded text."""
    spans: list[SourceSpan] = []
    blocks: list[DocumentBlock] = []
    warnings: list[str] = []
    sizes: list[tuple[float, float]] = []
    with _open(source, settings.password_env) as document:
        if len(document) == 0:
            raise ExtractionError("PDF has no pages")
        toc = document.get_toc()
        title = document.metadata.get("title") or source.stem
        author = document.metadata.get("author") or None
        for page_index, page in enumerate(document):
            sizes.append((float(page.rect.width), float(page.rect.height)))
            page_lines = _lines(page)
            readable = sum(len(line["text"]) for line in page_lines)
            use_ocr = settings.ocr == "always" or (
                settings.ocr == "auto" and readable < 24
            )
            origin = "embedded"
            if use_ocr:
                try:
                    textpage = page.get_textpage_ocr(
                        language=settings.ocr_language,
                        dpi=settings.ocr_dpi,
                        full=True,
                    )
                    page_lines = _lines(page, textpage=textpage)
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
