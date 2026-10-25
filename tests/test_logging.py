"""Privacy-safe structured logging contracts."""

import json
import logging

from pdf2audiobook.logging import (
    EventFormatter,
    configure_from_settings,
    configure_logging,
    log_event,
)


def test_allowlisted_fields_and_event():
    record = logging.LogRecord(
        "pdf2audiobook",
        logging.INFO,
        __file__,
        1,
        {
            "event": "command_started",
            "fields": {
                "command": "analyze",
                "stage": "extract",
                "count": 3,
                "unrecognized_field": "not for output",
            },
        },
        (),
        None,
    )
    assert json.loads(EventFormatter().format(record)) == {
        "level": "info",
        "event": "command_started",
        "fields": {"command": "analyze", "stage": "extract", "count": 3},
    }


def test_unstructured_message_redacted():
    record = logging.LogRecord(
        "pdf2audiobook",
        logging.INFO,
        __file__,
        1,
        "unstructured private content",
        (),
        None,
    )
    assert "private content" not in EventFormatter().format(record)


def test_debug_events_and_quiet_mode(capsys):
    configure_logging(verbose=True)
    log_event("command_started", command="analyze")
    assert json.loads(capsys.readouterr().err)["event"] == "command_started"
    configure_logging(quiet=True)
    log_event("command_started", command="analyze")
    assert capsys.readouterr().err == ""
    configure_logging()


def test_settings_log_level_controls_event_visibility(capsys):
    configure_logging()
    configure_from_settings("WARNING", cache_directory_configured=False)
    log_event("progress", level=logging.INFO, stage="analysis")
    log_event("degraded", level=logging.WARNING, status="fallback")
    log_event("command_failed", level=logging.ERROR, error_code=5)
    lines = capsys.readouterr().err.splitlines()
    assert [json.loads(line)["level"] for line in lines] == ["warning", "error"]


def test_quiet_level_keeps_errors_and_suppresses_warnings(capsys):
    configure_logging(quiet=True)
    log_event("degraded", level=logging.WARNING, status="fallback")
    log_event("command_failed", level=logging.ERROR, error_code=5)
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["level"] == "error"
