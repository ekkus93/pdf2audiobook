"""Machine-readable CLI error contract and stable domain exit codes."""

import json

import pytest
import typer
from typer.testing import CliRunner

from pdf2audiobook.cli import app, fail
from pdf2audiobook.errors import (
    AudioError,
    ConfigError,
    ExtractionError,
    InputError,
    LLMError,
    PartialConversionError,
)


@pytest.mark.parametrize(
    ("exception", "exit_code"),
    [
        (ConfigError("bad setting"), 2),
        (InputError("missing PDF"), 3),
        (ExtractionError("unreadable page"), 4),
        (LLMError("provider unavailable"), 5),
        (AudioError("invalid audio"), 6),
        (PartialConversionError("incomplete conversion"), 7),
        (OSError("filesystem unavailable"), 1),
    ],
)
def test_json_error_contract(exception, exit_code, capsys):
    with pytest.raises(typer.Exit) as raised:
        fail(exception, json_output=True)
    captured = capsys.readouterr()
    assert raised.value.exit_code == exit_code
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "ok": False,
        "error": {
            "type": type(exception).__name__,
            "code": exit_code,
            "message": str(exception),
        },
    }


def test_config_show_json_error_is_only_on_stderr(tmp_path):
    missing = tmp_path / "missing.toml"
    result = CliRunner().invoke(app, ["config", "show", "--json", "--config", str(missing)])
    assert result.exit_code == 2
    assert result.stdout == ""
    diagnostic = json.loads(result.stderr)
    assert diagnostic["ok"] is False
    assert diagnostic["error"]["type"] == "ConfigError"
    assert diagnostic["error"]["code"] == 2
    assert "not found" in diagnostic["error"]["message"]


def test_human_error_output_remains_human_readable(tmp_path):
    missing = tmp_path / "missing.toml"
    result = CliRunner().invoke(app, ["config", "show", "--config", str(missing)])
    assert result.exit_code == 2
    assert "Error:" in result.stderr
    assert not result.stderr.lstrip().startswith("{")
