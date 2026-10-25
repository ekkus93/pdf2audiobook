"""Workspace failures use one stable, private CLI diagnostic."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app

COMMANDS = ("analyze", "convert", "convert-dry-run", "batch", "review", "pack-m4b")


def _source(path: Path) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 80), "Chapter One")
    page.insert_text((72, 120), "A sufficiently long first chapter for workspace testing.")
    page.insert_text((72, 180), "Chapter Two")
    page.insert_text((72, 220), "A sufficiently long second chapter for workspace testing.")
    document.save(path)
    document.close()


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_workspace_failure_has_one_fixed_private_diagnostic(
    command: str, json_output: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    blocked_output = tmp_path / "not-a-directory"
    blocked_output.write_text("private sentinel path", encoding="utf-8")
    source = tmp_path / "book.pdf"
    _source(source)
    mode = ["--json"] if json_output else []

    if command in {"analyze", "convert", "convert-dry-run"}:
        arguments = [command.removesuffix("-dry-run"), str(source), "--no-config", "--no-llm"]
        if command == "convert-dry-run":
            arguments.append("--dry-run")
        arguments.extend(["--output", str(blocked_output), *mode])
    elif command == "batch":
        books = tmp_path / "books"
        books.mkdir()
        _source(books / "book.pdf")
        arguments = [
            "batch",
            str(books),
            "--no-config",
            "--no-llm",
            "--output",
            str(blocked_output),
            *mode,
        ]
    elif command == "review":
        arguments = ["review", str(blocked_output / "manifest.json"), *mode]
    else:
        from pdf2audiobook import audio, pipeline, workspace

        class Selection:
            chapters: list[object] = []
            skipped: list[object] = []

        class Manifest:
            title = "Book"
            author = None
            chapters: list[object] = []

        monkeypatch.setattr(workspace, "read_manifest", lambda _path: Manifest())
        monkeypatch.setattr(pipeline, "prepare_chapter_selection", lambda *_a, **_k: Selection())

        def fail_m4b(*_args: object, **_kwargs: object) -> None:
            raise OSError(f"No such file or directory: {blocked_output / 'book.m4b'}")

        monkeypatch.setattr(audio, "encode_m4b", fail_m4b)
        manifest = tmp_path / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        arguments = [
            "pack-m4b",
            str(manifest),
            "--output",
            str(blocked_output / "book.m4b"),
            "--no-config",
            *mode,
        ]

    result = runner.invoke(app, arguments)

    assert result.exit_code == (7 if command == "batch" else 4)
    assert str(blocked_output) not in result.stderr
    assert "No such file" not in result.stderr
    assert "private sentinel" not in result.stderr
    if command == "batch":
        if json_output:
            batch_result = json.loads(result.stdout)
            assert batch_result["books"][0]["error_code"] == 4
        else:
            assert '"error_code": 4' in result.output
        return
    if json_output:
        diagnostic = json.loads(result.stderr)
        assert diagnostic["error"] == {
            "type": "WorkspaceError",
            "code": 4,
            "message": "Cannot create the output workspace",
        }
    else:
        assert result.stderr.startswith("Error: Cannot create the output workspace")
