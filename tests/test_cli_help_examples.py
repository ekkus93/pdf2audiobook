"""Every public CLI command includes a directly usable help example."""

import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app


@pytest.mark.parametrize(
    "arguments",
    [
        ["--help"],
        ["doctor", "--help"],
        ["inspect", "--help"],
        ["analyze", "--help"],
        ["convert", "--help"],
        ["batch", "--help"],
        ["pack-m4b", "--help"],
        ["review", "--help"],
        ["config", "show", "--help"],
        ["budget", "show", "--help"],
        ["budget", "resolve", "--help"],
    ],
)
def test_every_command_help_contains_an_example(arguments):
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 0
    assert "Example:" in result.output
