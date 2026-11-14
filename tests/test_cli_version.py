"""`--version` works on its own and still works before a command (Tauri spec D2.f)."""

from __future__ import annotations

from typer.testing import CliRunner

from pdf2audiobook import __version__
from pdf2audiobook.cli import app

runner = CliRunner()


def test_version_alone_prints_the_version_and_exits_zero() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == f"{__version__}\n"


def test_version_before_a_command_still_prints_only_the_version() -> None:
    result = runner.invoke(app, ["--version", "doctor", "--json"])

    assert result.exit_code == 0
    assert result.stdout == f"{__version__}\n"


def test_no_arguments_still_shows_help() -> None:
    result = runner.invoke(app, [])

    assert "Usage" in result.output
    assert __version__ not in result.stdout.split()
