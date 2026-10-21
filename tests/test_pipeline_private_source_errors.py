"""Analysis input errors must not disclose local document filenames."""

from pathlib import Path

import pytest

from pdf2audiobook import pipeline
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import InputError


def test_missing_pdf_path_is_not_exposed(tmp_path):
    source = tmp_path / "PRIVATE_BOOK_NAME" / "PRIVATE_AUTHOR.pdf"
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "output")
    with pytest.raises(InputError, match="PDF not found") as caught:
        pipeline.analyze_book(source, settings)
    assert "PRIVATE_BOOK_NAME" not in str(caught.value)
    assert "PRIVATE_AUTHOR" not in str(caught.value)
    assert not (tmp_path / "output").exists()


def test_unreadable_pdf_digest_failure_is_sanitized(tmp_path, monkeypatch):
    source = tmp_path / "PRIVATE_BOOK_NAME.pdf"
    source.write_bytes(b"%PDF-1.4 synthetic")
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "output")

    def raise_secret_path(_source: Path):
        raise OSError("PRIVATE_BOOK_NAME.pdf: permission denied")

    monkeypatch.setattr(pipeline, "digest_file", raise_secret_path)
    with pytest.raises(InputError, match="Cannot access PDF") as caught:
        pipeline.analyze_book(source, settings)
    assert caught.value.__suppress_context__ is True
    assert "PRIVATE_BOOK_NAME" not in str(caught.value)
    assert not (tmp_path / "output").exists()
