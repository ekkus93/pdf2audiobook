"""CLI structured event logging must not corrupt JSON output or expose secrets."""

import json

from typer.testing import CliRunner

from pdf2audiobook.cli import app

runner = CliRunner()


def test_verbose_events_are_json_on_stderr_only():
    result = runner.invoke(app, ["--verbose", "config", "show", "--no-config", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert events == [
        {
            "event": "command_started",
            "fields": {"command": "config"},
            "level": "debug",
        }
    ]


def test_quiet_does_not_pollute_json_stdout():
    result = runner.invoke(app, ["--quiet", "config", "show", "--no-config", "--json"])
    assert result.exit_code == 0, result.output
    assert isinstance(json.loads(result.stdout), dict)
    assert result.stderr == ""


def test_mutually_exclusive_log_flags_are_rejected():
    result = runner.invoke(app, ["--verbose", "--quiet", "config", "show"])
    assert result.exit_code != 0
    assert "cannot be combined" in result.output


def test_verbose_error_events_never_include_invalid_config_path(tmp_path):
    secret = "confidential-book-title"
    result = runner.invoke(
        app,
        [
            "--verbose",
            "config",
            "show",
            "--config",
            str(tmp_path / f"{secret}.toml"),
            "--json",
        ],
    )
    assert result.exit_code != 0
    events = [
        json.loads(line)
        for line in result.stderr.splitlines()
        if line.startswith("{") and "command_" in line
    ]
    assert [event["event"] for event in events] == ["command_started", "command_failed"]
    assert all(secret not in json.dumps(event) for event in events)
