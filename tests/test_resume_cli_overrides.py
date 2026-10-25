"""Resume flags override configured values on every analysis command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app


@pytest.mark.parametrize("command", ["analyze", "batch"])
@pytest.mark.parametrize(
    ("configured", "flag", "expected"), [(True, "--no-resume", False), (False, "--resume", True)]
)
def test_resume_flags_override_config(
    tmp_path: Path, monkeypatch, command, configured, flag, expected
):
    config = tmp_path / "settings.toml"
    config.write_text(f"[general]\nresume = {str(configured).lower()}\n")
    source = tmp_path / "books"
    source.mkdir()
    if command == "analyze":
        argument = tmp_path / "book.pdf"
        captured = {}

        def fake_analyze_book(pdf, settings):
            captured["resume"] = settings.general.resume
            return tmp_path / "manifest.json"

        monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", fake_analyze_book)
        args = ["analyze", str(argument), "--config", str(config), flag]
    else:
        (source / "book.pdf").write_bytes(b"pdf")
        monkeypatch.setattr("pdf2audiobook.audio.read_cover_image", lambda *_: None)
        captured = {}

        def fake_convert_book(pdf, settings):
            captured["resume"] = settings.general.resume
            return []

        monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", fake_convert_book)
        args = ["batch", str(source), "--config", str(config), flag]

    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert captured["resume"] is expected
