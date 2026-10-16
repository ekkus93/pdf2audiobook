"""PDF metadata inspection (page extraction follows separately)."""
from pathlib import Path

import fitz

from pdf2audiobook.errors import InputError


def inspect_pdf(source: Path) -> dict:
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise InputError(f"not a readable PDF: {source}")
    try:
        with fitz.open(source) as pdf:
            if pdf.needs_pass:
                raise InputError("PDF is password protected")
            return {
                "title": pdf.metadata.get("title") or source.stem,
                "author": pdf.metadata.get("author") or None,
                "pages": len(pdf),
                "outline": pdf.get_toc(),
            }
    except InputError:
        raise
    except Exception as exc:
        raise InputError(f"could not read PDF: {exc}") from exc
