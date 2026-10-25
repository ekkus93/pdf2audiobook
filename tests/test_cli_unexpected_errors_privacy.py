"""Unexpected CLI exceptions never disclose their raw text."""

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("command", ["analyze", "convert", "config show"])
def test_runtime_error_is_content_free_for_all_commands(monkeypatch, tmp_path, command, json_mode):
    secret = "SECRET BOOK SENTENCE /private/book.pdf"
    if command == "config show":
        monkeypatch.setattr(
            "pdf2audiobook.cli.load_settings",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError(secret)),
        )
        args = ["config", "show"]
    elif command == "analyze":
        monkeypatch.setattr(
            "pdf2audiobook.pipeline.analyze_book",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError(secret)),
        )
        source = tmp_path / "input.pdf"
        source.write_bytes(b"pdf")
        args = ["analyze", str(source), "--no-config"]
    else:
        monkeypatch.setattr(
            "pdf2audiobook.pipeline.convert_book",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError(secret)),
        )
        source = tmp_path / "input.pdf"
        source.write_bytes(b"pdf")
        args = ["convert", str(source), "--no-config"]
    if json_mode:
        args.append("--json")
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 1
    assert "Unexpected internal error" in result.stderr
    assert secret not in result.output


def test_keyboard_interrupt_uses_fixed_message_and_exit_130(monkeypatch, tmp_path):
    source = tmp_path / "input.pdf"
    source.write_bytes(b"pdf")
    monkeypatch.setattr(
        "pdf2audiobook.pipeline.analyze_book",
        lambda *_a, **_k: (_ for _ in ()).throw(KeyboardInterrupt("PRIVATE DETAIL")),
    )
    result = CliRunner().invoke(app, ["analyze", str(source), "--no-config"])
    assert result.exit_code == 130
    assert "Interrupted" in result.stderr
    assert "PRIVATE DETAIL" not in result.output
