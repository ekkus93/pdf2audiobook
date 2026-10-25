"""Filesystem failures on a user-selected output path never disclose that path."""

import json

import pymupdf
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app


@pytest.mark.parametrize("json_output", [False, True])
def test_analyze_output_path_failure_is_content_free(tmp_path, json_output):
    source = tmp_path / "PRIVATE_BOOK_STEM.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((60, 70), "Chapter 1")
    page.insert_text((60, 100), "Synthetic passage for a private path test.")
    document.save(source)
    document.close()

    output_file = tmp_path / "PRIVATE_OUTPUT_PATH"
    output_file.write_text("not a directory")
    output_dir = output_file / "subdirectory"
    args = [
        "analyze",
        str(source),
        "--no-config",
        "--no-llm",
        "--output",
        str(output_dir),
    ]
    if json_output:
        args.append("--json")
    result = CliRunner().invoke(app, args)

    assert result.exit_code == 4
    for private in ("PRIVATE_BOOK_STEM", "PRIVATE_OUTPUT_PATH", "NotADirectoryError", "errno"):
        assert private not in result.stderr
    if json_output:
        diagnostic = json.loads(result.stderr.splitlines()[-1])
        assert diagnostic["error"]["type"] == "ExtractionError"
        assert diagnostic["error"]["message"] == "Could not create or update the output workspace"
