"""Privacy-safe structured logging contracts."""

import json
import logging

from pdf2audiobook.logging import EventFormatter, configure_logging, log_event


def test_allowlisted_fields_and_event():
    record = logging.LogRecord(
        "pdf2audiobook", logging.INFO, __file__, 1,
        {"event": "command_started", "fields": {
            "command": "analyze", "stage": "extract", "count": 3,
            "unrecognized_field": "not for output",
        }},
        (), None,
    )
    assert json.loads(EventFormatter().format(record)) == {
        "level": "info", "event": "command_started",
        "fields": {"command": "analyze", "stage": "extract", "count": 3},
    }


def test_unstructured_message_redacted():
    record = logging.LogRecord(
        "pdf2audiobook", logging.INFO, __file__, 1,
        "unstructured private content", (), None,
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
