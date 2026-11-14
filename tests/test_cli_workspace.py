"""`pdf2audiobook workspace` reports where analysis keeps a book (Tauri spec D2.a)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from pdf2audiobook.cli import app

FIXTURE = Path(__file__).parent / "fixtures" / "outlined_text.pdf"
runner = CliRunner()


def _tree(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def _book(tmp_path: Path) -> Path:
    book = tmp_path / "My Book.pdf"
    shutil.copyfile(FIXTURE, book)
    return book


def test_workspace_matches_the_folder_analyze_creates(tmp_path: Path) -> None:
    book = _book(tmp_path)
    output = tmp_path / "out"
    before = _tree(tmp_path)

    first = runner.invoke(
        app, ["workspace", str(book), "--output", str(output), "--no-config", "--json"]
    )

    assert first.exit_code == 0, first.output
    payload = json.loads(first.stdout)
    digest = hashlib.sha256(book.read_bytes()).hexdigest()
    expected = output / f"My Book-{digest[:10]}"
    assert payload == {"workspace": str(expected), "exists": False, "warnings": []}
    assert _tree(tmp_path) == before

    analyzed = runner.invoke(
        app,
        [
            "analyze",
            str(book),
            "--output",
            str(output),
            "--no-config",
            "--no-llm",
            "--allow-single-chapter",
            "--json",
        ],
    )
    assert analyzed.exit_code == 0, analyzed.output
    assert Path(json.loads(analyzed.stdout)["manifest"]).parent == expected

    second = runner.invoke(
        app, ["workspace", str(book), "--output", str(output), "--no-config", "--json"]
    )

    assert second.exit_code == 0, second.output
    assert json.loads(second.stdout) == {
        "workspace": str(expected),
        "exists": True,
        "warnings": [],
    }


def test_workspace_uses_the_configured_output_folder(tmp_path: Path, monkeypatch) -> None:
    book = _book(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PDF2AUDIOBOOK_OUTPUT_DIR", str(tmp_path / "configured"))

    result = runner.invoke(app, ["workspace", str(book), "--no-config", "--json"])

    assert result.exit_code == 0, result.output
    workspace = Path(json.loads(result.stdout)["workspace"])
    assert workspace.parent == tmp_path / "configured"


def test_missing_book_gives_exit_3_and_the_existing_message(tmp_path: Path) -> None:
    missing = tmp_path / "secret-title.pdf"

    result = runner.invoke(app, ["workspace", str(missing), "--no-config", "--json"])

    assert result.exit_code == 3
    error = json.loads(result.stderr)
    assert error["ok"] is False
    assert error["error"] == {
        "type": "InputError",
        "code": 3,
        "message": "PDF not found; check the input path and permissions",
    }
    assert "secret-title" not in result.stderr
    assert str(tmp_path) not in result.stderr
    assert list(tmp_path.iterdir()) == []
