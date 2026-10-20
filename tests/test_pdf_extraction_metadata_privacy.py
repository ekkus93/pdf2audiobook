"""Advisory PDF metadata and page labels must not expose parser diagnostics."""

from pathlib import Path

import fitz
import pytest

from pdf2audiobook.config import Pdf
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.pdf import extract_pdf

PRIVATE = "SYNTHETIC_PRIVATE_BOOK_CONTENT_507"


@pytest.mark.parametrize("broken_stage", ["outline", "metadata"])
def test_extraction_sanitizes_untrusted_outline_and_metadata_errors(
    monkeypatch, broken_stage: str
) -> None:
    class FaultyDocument:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __len__(self):
            return 1

        def get_toc(self):
            if broken_stage == "outline":
                raise RuntimeError(f"corrupt outline included {PRIVATE}")
            return []

        @property
        def metadata(self):
            if broken_stage == "metadata":
                raise RuntimeError(f"bad metadata included {PRIVATE}")
            return {"title": "Fixture", "author": "Fictional"}

    monkeypatch.setattr("pdf2audiobook.pdf._open", lambda *_args: FaultyDocument())
    with pytest.raises(ExtractionError, match="Failed to read PDF outline or metadata") as err:
        extract_pdf(Path("fixture.pdf"), Pdf(ocr="never"))
    assert PRIVATE not in str(err.value)
    assert err.value.__cause__ is None


def test_unreadable_page_label_preserves_extracted_prose(monkeypatch, tmp_path: Path):
    source = tmp_path / "book.pdf"
    document = fitz.open()
    document.new_page().insert_text((72, 110), "A completely synthetic book passage.")
    document.save(source)
    document.close()

    def broken_label(_page):
        raise RuntimeError(f"page-label parser exposed {PRIVATE}")

    monkeypatch.setattr(fitz.Page, "get_label", broken_label)
    result = extract_pdf(source, Pdf(ocr="never"))
    assert len(result.spans) == 1
    assert result.spans[0].text == "A completely synthetic book passage."
    assert result.spans[0].page_label == "1"
    assert any("could not read PDF page label" in item for item in result.warnings)
    assert all(PRIVATE not in item for item in result.warnings)
