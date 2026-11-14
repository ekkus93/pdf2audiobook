"""`pdf2audiobook thumbnail` renders a book's first page or cover (Tauri spec D2.g)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pymupdf
from epub_book import write_novel_epub
from typer.testing import CliRunner

from pdf2audiobook.cli import app

FIXTURE = Path(__file__).parent / "fixtures" / "outlined_text.pdf"
runner = CliRunner()


def _thumbnail(*args: str) -> Any:
    return runner.invoke(app, ["thumbnail", *args, "--json"])


def _names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


def test_pdf_first_page_is_rendered_at_the_requested_width(tmp_path: Path) -> None:
    book = tmp_path / "book.pdf"
    shutil.copyfile(FIXTURE, book)
    out = tmp_path / "thumb.png"

    result = _thumbnail(str(book), "--output", str(out), "--width", "200")

    assert result.exit_code == 0, result.output
    page = pymupdf.open(book)[0].rect
    pixmap = pymupdf.Pixmap(str(out))
    assert (pixmap.width, pixmap.height) == (200, round(200 * page.height / page.width))
    assert json.loads(result.stdout) == {
        "thumbnail": str(out),
        "width": pixmap.width,
        "height": pixmap.height,
        "warnings": [],
    }
    assert _names(tmp_path) == ["book.pdf", "thumb.png"]


def test_default_width_is_320(tmp_path: Path) -> None:
    out = tmp_path / "thumb.png"

    result = _thumbnail(str(FIXTURE), "--output", str(out))

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["width"] == 320
    assert pymupdf.Pixmap(str(out)).width == 320


def test_epub_cover_is_rendered(tmp_path: Path) -> None:
    book = write_novel_epub(tmp_path / "novel.epub", cover=True)
    out = tmp_path / "cover.png"

    result = _thumbnail(str(book), "--output", str(out), "--width", "240")

    assert result.exit_code == 0, result.output
    pixmap = pymupdf.Pixmap(str(out))
    assert pixmap.width == 240
    red, green, blue = pixmap.pixel(pixmap.width // 5, pixmap.height // 5)[:3]
    # The fixture's first page holds its solid (40, 90, 160) cover image at its natural
    # size in the top-left corner; this point lies inside it.
    assert abs(red - 40) < 12 and abs(green - 90) < 12 and abs(blue - 160) < 12
    assert _names(tmp_path) == ["cover.png", "novel.epub"]


def test_unreadable_book_gives_exit_3_and_writes_nothing(tmp_path: Path) -> None:
    book = tmp_path / "secret-title.pdf"
    book.write_bytes(b"not a pdf at all")
    out = tmp_path / "thumb.png"

    result = _thumbnail(str(book), "--output", str(out))

    assert result.exit_code == 3
    assert json.loads(result.stderr)["error"] == {
        "type": "InputError",
        "code": 3,
        "message": "cannot open PDF; verify file integrity and permissions",
    }
    assert "secret-title" not in result.stderr and str(tmp_path) not in result.stderr
    assert _names(tmp_path) == ["secret-title.pdf"]


def test_missing_book_gives_exit_3(tmp_path: Path) -> None:
    result = _thumbnail(str(tmp_path / "gone.pdf"), "--output", str(tmp_path / "t.png"))

    assert result.exit_code == 3
    message = json.loads(result.stderr)["error"]["message"]
    assert message == "not a readable PDF or EPUB book; verify input path and permissions"
    assert list(tmp_path.iterdir()) == []


def test_output_in_a_missing_folder_is_refused_without_creating_it(tmp_path: Path) -> None:
    out = tmp_path / "missing" / "thumb.png"

    result = _thumbnail(str(FIXTURE), "--output", str(out))

    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["message"] == (
        "Thumbnail output must be a .png file in an existing folder"
    )
    assert list(tmp_path.iterdir()) == []


def test_output_that_is_not_png_is_refused(tmp_path: Path) -> None:
    result = _thumbnail(str(FIXTURE), "--output", str(tmp_path / "thumb.jpg"))

    assert result.exit_code == 2
    assert list(tmp_path.iterdir()) == []
