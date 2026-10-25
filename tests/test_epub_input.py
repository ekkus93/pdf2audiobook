"""Synthetic EPUB files exercise the same traceable extraction pipeline as PDFs."""

from zipfile import ZIP_STORED, ZipFile

from pdf2audiobook.config import Settings
from pdf2audiobook.pdf import extract_pdf, inspect_pdf
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest


def _write_epub(path):
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="3.0" unique-identifier="id"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">fixture'
            "</dc:identifier><dc:title>EPUB Fixture</dc:title><dc:language>en</dc:language>"
            '</metadata><manifest><item id="c1" href="c1.xhtml" '
            'media-type="application/xhtml+xml"/><item id="c2" href="c2.xhtml" '
            'media-type="application/xhtml+xml"/></manifest><spine>'
            '<itemref idref="c1"/><itemref idref="c2"/></spine></package>',
        )
        archive.writestr(
            "OEBPS/c1.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>First</title>'
            "</head><body><h1>Chapter One</h1><p>First chapter text remains intact.</p>"
            "</body></html>",
        )
        archive.writestr(
            "OEBPS/c2.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Second</title>'
            "</head><body><h1>Chapter Two</h1><p>Second chapter text remains intact.</p>"
            "</body></html>",
        )


def test_epub_inspection_and_extraction_preserve_order_and_text(tmp_path):
    source = tmp_path / "fixture.epub"
    _write_epub(source)

    info = inspect_pdf(source)
    result = extract_pdf(source, Settings().pdf)

    assert info["title"] == "EPUB Fixture"
    assert info["pages"] == 2
    assert "First chapter text remains intact." in "\n".join(block.text for block in result.blocks)
    assert "Second chapter text remains intact." in "\n".join(block.text for block in result.blocks)
    assert [span.page_index for span in result.spans] == sorted(
        span.page_index for span in result.spans
    )


def test_epub_analyze_creates_standard_manifest_and_chapter_text(tmp_path):
    source = tmp_path / "fixture.epub"
    _write_epub(source)
    settings = Settings.model_validate(
        {
            "general": {"output_dir": str(tmp_path / "out")},
            "llm": {"enabled": False},
            "chapters": {"allow_single_chapter": True},
        }
    )

    manifest_path = analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(manifest_path.parent.glob("chapters/*.txt"))
    )

    assert manifest.title == "EPUB Fixture"
    assert "First chapter text remains intact." in text
    assert "Second chapter text remains intact." in text
