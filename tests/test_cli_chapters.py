"""CLI chapter selection, dry-run and speech-setting override acceptance."""

from __future__ import annotations

import json

import fitz
from typer.testing import CliRunner

from pdf2audiobook.cli import app, parse_chapter_range
from pdf2audiobook.errors import ConfigError


def test_parse_range():
    assert parse_chapter_range("2:5") == (2, 5)
    for invalid in ("0:2", "2:1", "1-3", "1:0", "-1:2", "1:2:3"):
        try:
            parse_chapter_range(invalid)
            assert False, f"accepted {invalid}"
        except ConfigError:
            pass


def test_dry_run_plans_selected_chapters_without_tts(tmp_path):
    source = tmp_path / "example.pdf"
    document = fitz.open()
    for n in (1, 2, 3):
        page = document.new_page()
        page.insert_text((80, 80), f"Chapter {n}")
        page.insert_text((80, 130), f"This is chapter {n} text.")
    document.save(source)
    document.close()
    runner = CliRunner()
    args = [
        "convert",
        str(source),
        "--no-llm",
        "--ocr",
        "never",
        "--output",
        str(tmp_path / "out"),
        "--chapter-range",
        "2:3",
        "--speed",
        "1.25",
        "--sample-rate",
        "22050",
        "--dry-run",
        "--json",
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["dry_run"] is True
    assert report["chapters"] == 2
    assert "002" in report["mp3_files"][0]
    assert "003" in report["mp3_files"][1]
    assert not list((tmp_path / "out").rglob("*.mp3"))
    conflict = runner.invoke(app, args + ["--chapter", "1"])
    assert conflict.exit_code == 2


def test_out_of_bounds_range_is_error(tmp_path):
    source = tmp_path / "example.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((80, 80), "Chapter 1")
    page.insert_text((80, 140), "A first chapter.")
    document.save(source)
    document.close()
    result = CliRunner().invoke(
        app,
        [
            "convert",
            str(source),
            "--no-llm",
            "--ocr",
            "never",
            "--output",
            str(tmp_path / "out"),
            "--chapter-range",
            "1:2",
            "--dry-run",
        ],
    )
    assert result.exit_code == 6
