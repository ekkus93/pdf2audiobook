"""Commands preserve deliberate non-zero Click/Typer exit signals."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

from pdf2audiobook.cli import app


class _FakeLedger:
    def __init__(self, _path: Path) -> None:
        pass

    def rows(self, *, readonly: bool) -> list[dict[str, object]]:
        assert readonly
        return []

    def totals(self, *, readonly: bool) -> dict[str, object]:
        assert readonly
        return {}

    def resolve_unknown(self, *_args: object, **_kwargs: object) -> str:
        return "unbilled"


@pytest.mark.parametrize(
    "command",
    [
        "config-show",
        "budget-show",
        "budget-resolve",
        "doctor",
        "inspect",
        "analyze",
        "convert",
        "batch",
        "pack-m4b",
        "review",
    ],
)
def test_commands_reraise_nonzero_typer_exit(monkeypatch, tmp_path, command):
    exit_code = 37

    def raise_exit(*_args: object, **_kwargs: object) -> None:
        raise typer.Exit(exit_code)

    output = tmp_path / "book-output"
    reports = output / "reports"
    reports.mkdir(parents=True)
    (reports / "llm_budget.sqlite3").touch()
    source = tmp_path / "book.pdf"
    source.write_bytes(b"synthetic input")

    monkeypatch.setattr("pdf2audiobook.llm.budget.BookLLMBudgetLedger", _FakeLedger)
    if command == "inspect":
        monkeypatch.setattr("pdf2audiobook.pdf.inspect_pdf", lambda *_a, **_k: {})
    elif command == "analyze":
        monkeypatch.setattr("pdf2audiobook.pipeline.analyze_book", lambda *_a, **_k: source)
    elif command == "convert":
        monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", lambda *_a, **_k: [])
    elif command == "batch":
        books = tmp_path / "books"
        books.mkdir()
        (books / "book.pdf").write_bytes(b"synthetic input")
        monkeypatch.setattr(
            "pdf2audiobook.pipeline.settings_for_book_tts",
            lambda settings, *_a, **_k: settings,
        )
        monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", lambda *_a, **_k: [])
    elif command == "pack-m4b":
        monkeypatch.setattr(
            "pdf2audiobook.workspace.read_manifest",
            lambda *_a, **_k: SimpleNamespace(title="Book", author=None, chapters=[]),
        )
        monkeypatch.setattr(
            "pdf2audiobook.pipeline.prepare_chapter_selection",
            lambda *_a, **_k: SimpleNamespace(chapters=[], skipped=[]),
        )
        monkeypatch.setattr(
            "pdf2audiobook.audio.encode_m4b", lambda *_a, **_k: tmp_path / "book.m4b"
        )
    elif command == "review":

        class _ReviewServer:
            server_address = ("127.0.0.1", 12345)

            def serve_forever(self) -> None:
                raise typer.Exit(exit_code)

            def server_close(self) -> None:
                pass

        monkeypatch.setattr(
            "pdf2audiobook.review_ui.create_review_server", lambda *_a, **_k: _ReviewServer()
        )
        (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    if command != "review":
        monkeypatch.setattr("pdf2audiobook.cli.emit", raise_exit)

    arguments = {
        "config-show": ["config", "show", "--no-config"],
        "budget-show": ["budget", "show", "--output", str(output)],
        "budget-resolve": [
            "budget",
            "resolve",
            "--output",
            str(output),
            "1",
            "--unbilled",
            "--confirm",
            "--no-config",
        ],
        "doctor": ["doctor", "--no-config"],
        "inspect": ["inspect", str(source)],
        "analyze": ["analyze", str(source), "--no-config"],
        "convert": ["convert", str(source), "--no-config"],
        "batch": ["batch", str(tmp_path / "books"), "--no-config"],
        "pack-m4b": [
            "pack-m4b",
            str(tmp_path / "manifest.json"),
            "--output",
            str(tmp_path / "book.m4b"),
            "--no-config",
        ],
        "review": ["review", str(tmp_path / "manifest.json")],
    }[command]
    result = CliRunner().invoke(app, arguments)

    assert result.exit_code == exit_code


def test_batch_failure_exits_7_with_one_json_stderr_value(tmp_path):
    books = tmp_path / "books"
    books.mkdir()
    (books / "invalid.pdf").write_bytes(b"not a PDF")

    result = CliRunner().invoke(app, ["batch", str(books), "--no-config", "--no-llm", "--json"])

    assert result.exit_code == 7
    assert json.loads(result.stdout)["failed"] == 1
    assert json.loads(result.stderr) == {
        "ok": False,
        "error": {
            "type": "PartialConversionError",
            "code": 7,
            "message": "One or more books failed",
        },
        "warnings": [],
    }


def test_batch_reraises_exit_from_book_converter(monkeypatch, tmp_path):
    books = tmp_path / "books"
    books.mkdir()
    (books / "book.pdf").write_bytes(b"synthetic input")

    def stop_book(*_args: object, **_kwargs: object) -> list[Path]:
        raise typer.Exit(37)

    monkeypatch.setattr(
        "pdf2audiobook.pipeline.settings_for_book_tts",
        lambda settings, *_a, **_k: settings,
    )
    monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", stop_book)

    result = CliRunner().invoke(app, ["batch", str(books), "--no-config", "--json"])

    assert result.exit_code == 37
