"""Structured, privacy-preserving CLI event logging."""

from __future__ import annotations

import json
import logging
import re
import sys

LOGGER = logging.getLogger("pdf2audiobook")
ALLOWED = frozenset({"command", "stage", "status", "provider", "error_code", "count"})
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")


def _safe(value: object) -> str:
    if isinstance(value, str) and IDENTIFIER.fullmatch(value):
        return value
    return "[redacted]"


class EventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, object] = {"level": record.levelname.lower(), "event": "unstructured_message_redacted"}
        if isinstance(record.msg, dict):
            data["event"] = _safe(record.msg.get("event"))
            fields = record.msg.get("fields")
            if isinstance(fields, dict):
                data["fields"] = {
                    key: value if isinstance(value, (int, bool)) else _safe(value)
                    for key, value in fields.items()
                    if key in ALLOWED
                }
        return json.dumps(data, sort_keys=True)


def configure_logging(*, verbose: bool = False, quiet: bool = False) -> None:
    if verbose and quiet:
        raise ValueError("--verbose and --quiet cannot be combined")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(EventFormatter())
    for old in LOGGER.handlers[:]:
        LOGGER.removeHandler(old)
        old.close()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.DEBUG if verbose else logging.ERROR if quiet else logging.INFO)
    LOGGER.propagate = False


def log_event(event: str, **fields: object) -> None:
    LOGGER.debug({"event": event, "fields": fields})
