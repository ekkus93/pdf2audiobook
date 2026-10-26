"""CLI structured event logging must not corrupt JSON output or expose secrets."""

import json

import pymupdf
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


def test_default_stderr_of_a_failed_command_is_only_the_error(tmp_path):
    missing = tmp_path / "missing.pdf"
    human = runner.invoke(app, ["analyze", str(missing), "--no-config"])
    assert human.exit_code != 0
    assert human.stderr.lstrip().startswith("Error:")
    machine = runner.invoke(app, ["analyze", str(missing), "--no-config", "--json"])
    assert machine.exit_code != 0
    assert json.loads(machine.stderr)["ok"] is False


def test_verbose_failed_analyze_emits_stage_and_failure_events(tmp_path):
    result = runner.invoke(
        app, ["--verbose", "analyze", str(tmp_path / "missing.pdf"), "--no-config", "--json"]
    )
    assert result.exit_code != 0
    lines = [line for line in result.stderr.splitlines() if line.startswith("{")]
    events = [json.loads(line) for line in lines if '"event"' in line]
    names = [event["event"] for event in events]
    assert "command_failed" in names
    assert any(event.get("level") == "error" for event in events)


def test_verbose_analyze_emits_stage_started_event(tmp_path):
    source = tmp_path / "book.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 80), "Chapter One")
    page.insert_text((72, 130), "Enough ordinary readable prose for this chapter.")
    page.insert_text((72, 180), "Chapter Two")
    page.insert_text((72, 230), "Enough ordinary readable prose for the next chapter.")
    document.save(source)
    document.close()

    result = runner.invoke(
        app,
        [
            "--verbose",
            "analyze",
            str(source),
            "--no-config",
            "--no-llm",
            "--output",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0, result.stderr
    events = [
        json.loads(line)
        for line in result.stderr.splitlines()
        if line.startswith("{") and '"event"' in line
    ]
    assert any(
        event["event"] == "stage_started" and event["fields"].get("stage") == "analysis"
        for event in events
    )


def test_explicit_log_level_enables_progress_and_failure_events(tmp_path):
    config = tmp_path / "settings.toml"
    config.write_text('[general]\nlog_level = "INFO"\n')
    result = runner.invoke(
        app, ["analyze", str(tmp_path / "missing.pdf"), "--config", str(config), "--json"]
    )
    assert result.exit_code != 0
    events = [json.loads(line) for line in result.stderr.splitlines() if '"event"' in line]
    assert "command_failed" in [event["event"] for event in events]


def test_quiet_json_failure_writes_one_error_object(tmp_path):
    result = runner.invoke(
        app,
        ["--quiet", "analyze", str(tmp_path / "missing.pdf"), "--no-config", "--json"],
    )

    assert result.exit_code != 0
    assert len(result.stderr.splitlines()) == 1
    assert json.loads(result.stderr)["ok"] is False


def test_quiet_human_failure_starts_with_error(tmp_path):
    result = runner.invoke(
        app, ["--quiet", "analyze", str(tmp_path / "missing.pdf"), "--no-config"]
    )

    assert result.exit_code != 0
    assert result.stderr.lstrip().startswith("Error:")
    assert '"event"' not in result.stderr


def test_json_failure_embeds_configuration_warning_code(tmp_path, monkeypatch):
    import pdf2audiobook.logging as app_logging

    monkeypatch.setattr(app_logging, "_CACHE_DIRECTORY_WARNING_EMITTED", False)
    config = tmp_path / "settings.toml"
    config.write_text('[cache]\nenabled = false\ndirectory = "custom-cache"\n')
    result = runner.invoke(
        app,
        ["analyze", str(tmp_path / "missing.pdf"), "--config", str(config), "--json"],
    )

    assert result.exit_code != 0
    assert len(result.stderr.splitlines()) == 1
    diagnostic = json.loads(result.stderr)
    assert diagnostic["warnings"] == ["cache_directory_ignored"]


def test_human_failure_renders_warning_and_error_without_json(tmp_path, monkeypatch):
    import pdf2audiobook.logging as app_logging

    monkeypatch.setattr(app_logging, "_CACHE_DIRECTORY_WARNING_EMITTED", False)
    config = tmp_path / "settings.toml"
    config.write_text('[cache]\nenabled = false\ndirectory = "custom-cache"\n')
    result = runner.invoke(app, ["analyze", str(tmp_path / "missing.pdf"), "--config", str(config)])

    assert result.exit_code != 0
    lines = result.stderr.splitlines()
    assert lines[0].startswith("Warning:")
    assert lines[-1].startswith("Error:")
    assert "{" not in result.stderr
