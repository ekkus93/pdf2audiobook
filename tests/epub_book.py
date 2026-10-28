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


def chapter_body(number: int, paragraphs: int | None = None) -> str:
    """Chapter text that never repeats the words 'Chapter' or the chapter number.

    Lengths vary from a fraction of a page to several pages, like a real novel, so the
    numerals do not advance exactly one per page.
    """
    if paragraphs is None:
        paragraphs = 3 + (number * 5) % 7 * 2
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
            "narrative prose that is long enough to read as ordinary running text, and then "
            "carries on for a few more clauses so that several paragraphs fill a page.</p>"
        )
    return "".join(lines)


def write_novel_epub(
    path: Path,
    *,
    chapters: int = 6,
    outline: bool | str | None = True,
    cover: bool = True,
    contents: bool = True,
    body_numerals: bool = True,
    art_page: bool = False,
) -> Path:
    """Write the fixture; returns ``path``.

    ``outline`` is ``"ncx"`` (EPUB 2, also ``True``), ``"nav"`` (an EPUB 3 navigation
    document) or ``None`` (also ``False``). ``body_numerals=False`` makes each chapter
    open with a heading that repeats the outline title, as many ordinary EPUBs do.
    """
    outline_kind = {True: "ncx", False: None}.get(outline, outline)  # type: ignore[call-overload]
    if outline_kind not in {"ncx", "nav", None}:
        raise ValueError("outline must be 'ncx', 'nav', True, False or None")
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
    if art_page:
        # A page with a drawn frame and no text: real vector art, not a page background.
        items.append(
            (
                "art",
                "art.xhtml",
                _page(
                    "Art",
                    '<div style="width:200px;height:200px;border:3px solid #000000;'
                    'background-color:#cc0000"></div>',
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
    if outline_kind == "ncx":
        manifest += '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    if outline_kind == "nav":
        manifest += (
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )
    spine = "".join(f'<itemref idref="{item_id}"/>' for item_id, _, _ in items)
    spine_attr = ' toc="ncx"' if outline_kind == "ncx" else ""
    version = "3.0" if outline_kind == "nav" else "2.0"
    package = (
        f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="{version}" '
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
        if outline_kind == "nav":
            entries = "".join(
                f'<li><a href="ch{number}.xhtml">Chapter {number}</a></li>'
                for number in range(1, chapters + 1)
            )
            archive.writestr(
                "OEBPS/nav.xhtml",
                f'{XHTML[:-1]} xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Nav</title>'
                f'</head><body><nav epub:type="toc"><ol>{entries}</ol></nav></body></html>',
            )
        if outline_kind == "ncx":
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
