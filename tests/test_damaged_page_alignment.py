"""A failed page load keeps later page geometry aligned to physical indices."""

import fitz

from pdf2audiobook.config import Pdf
from pdf2audiobook.pdf import extract_pdf


def test_failed_page_load_adds_placeholder_size(monkeypatch, tmp_path):
    document = fitz.open()
    document.new_page(width=300, height=400)
    document.new_page(width=500, height=600)
    document.new_page(width=700, height=800)

    class BrokenDocument:
        is_repaired = False
        is_reflowable = False
        metadata = {"title": "Synthetic", "author": None}

        def __len__(self):
            return len(document)

        def get_toc(self):
            return []

        def get_page_labels(self):
            return []

        def load_page(self, index):
            if index == 0:
                raise RuntimeError("private parser detail")
            return document.load_page(index)

        def close(self):
            document.close()

    class Context:
        def __enter__(self):
            return BrokenDocument()

        def __exit__(self, *_args):
            document.close()

    monkeypatch.setattr("pdf2audiobook.pdf._open", lambda *_args, **_kwargs: Context())
    result = extract_pdf(tmp_path / "synthetic.pdf", Pdf(ocr="never"))
    assert result.page_sizes == [(0.0, 0.0), (500.0, 600.0), (700.0, 800.0)]
    assert any("Page 1: could not be loaded" in warning for warning in result.warnings)
    assert all(block.page_index != 0 for block in result.blocks)
