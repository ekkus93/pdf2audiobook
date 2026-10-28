"""Synthetic novel-shaped EPUB used to reproduce chapter detection problems.

It mimics the structure of commercial trade EPUBs without any real text: a cover
image on a full-page background, title and copyright pages, a contents list split
over two spine files, and chapters that open with a bare numeral line. An optional
NCX outline points an ``Chapter N`` entry at each chapter's first page.
"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pymupdf

XHTML = '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml">'


def _cover_png() -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 180), False)
    pixmap.set_rect(pixmap.irect, (40, 90, 160))
    return pixmap.tobytes("png")


def _page(title: str, body: str, head: str = "") -> str:
    return f"{XHTML}<head><title>{title}</title>{head}</head><body>{body}</body></html>"


def chapter_body(number: int, paragraphs: int = 3) -> str:
    """Chapter text that never repeats the words 'Chapter' or the chapter number."""
    openers = [
        "WHEN THE LAMPS were lit along the quiet road, the household began to stir.",
        "IT WAS HARDLY surprising that the letters arrived so late in the season.",
        "HE TAPPED his companion on the shoulder and pointed toward the far water.",
    ]
    lines = [
        f"<h2>{number}</h2>",
        f"<p>{openers[number % len(openers)]} Invented sentence {number}.</p>",
    ]
    for index in range(1, paragraphs):
        lines.append(
            f"<p>Paragraph {index} of the invented passage {number} continues with plain "
            "narrative prose that is long enough to read as ordinary running text.</p>"
        )
    return "".join(lines)


def write_novel_epub(
    path: Path,
    *,
    chapters: int = 6,
    outline: bool = True,
    cover: bool = True,
    contents: bool = True,
    body_numerals: bool = True,
) -> Path:
    """Write the fixture; returns ``path``.

    ``body_numerals=False`` makes each chapter open with a heading that repeats the
    outline title, as many ordinary EPUBs do.
    """
    items: list[tuple[str, str, str]] = []  # (id, href, xhtml)
    if cover:
        items.append(
            (
                "cover",
                "cover.xhtml",
                _page(
                    "Cover",
                    '<div><img src="cover.png" alt="" width="120" height="180"/></div>',
                    "<style>body{background-color:#ffffff;margin:0}</style>",
                ),
            )
        )
    items.append(
        ("title", "title.xhtml", _page("Title Page", "<h1>Title Page</h1><p>An Invented Novel</p>"))
    )
    items.append(
        (
            "copyright",
            "copyright.xhtml",
            _page("Copyright", "<h1>Copyright</h1><p>All rights reserved.</p>"),
        )
    )
    if contents:
        labels = [f"<p>Chapter {number}</p>" for number in range(1, chapters + 1)]
        half = max(1, len(labels) // 2)
        items.append(
            (
                "contents",
                "contents.xhtml",
                _page("Contents", "<h1>Contents</h1>" + "".join(labels[:half])),
            )
        )
        items.append(("contents2", "contents2.xhtml", _page("Contents", "".join(labels[half:]))))
    for number in range(1, chapters + 1):
        body = chapter_body(number)
        if not body_numerals:
            body = body.replace(f"<h2>{number}</h2>", f"<h2>Chapter {number}</h2>")
        items.append((f"ch{number}", f"ch{number}.xhtml", _page(f"Chapter {number}", body)))

    manifest = "".join(
        f'<item id="{item_id}" href="{href}" media-type="application/xhtml+xml"/>'
        for item_id, href, _ in items
    )
    if cover:
        manifest += '<item id="img" href="cover.png" media-type="image/png"/>'
    if outline:
        manifest += '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    spine = "".join(f'<itemref idref="{item_id}"/>' for item_id, _, _ in items)
    spine_attr = ' toc="ncx"' if outline else ""
    package = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
        'unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="id">novel-fixture</dc:identifier><dc:title>Novel Fixture</dc:title>'
        "<dc:language>en</dc:language></metadata>"
        f"<manifest>{manifest}</manifest><spine{spine_attr}>{spine}</spine></package>"
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
            'version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr("OEBPS/content.opf", package)
        if outline:
            points = "".join(
                f'<navPoint id="n{number}" playOrder="{number}"><navLabel><text>Chapter {number}'
                f'</text></navLabel><content src="ch{number}.xhtml"/></navPoint>'
                for number in range(1, chapters + 1)
            )
            archive.writestr(
                "OEBPS/toc.ncx",
                '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
                '<head><meta name="dtb:uid" content="novel-fixture"/></head>'
                "<docTitle><text>Novel Fixture</text></docTitle>"
                f"<navMap>{points}</navMap></ncx>",
            )
        for _item_id, href, xhtml in items:
            archive.writestr(f"OEBPS/{href}", xhtml)
        if cover:
            archive.writestr("OEBPS/cover.png", _cover_png())
    return path
