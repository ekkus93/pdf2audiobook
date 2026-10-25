"""Structured, privacy-preserving CLI event logging."""

from __future__ import annotations

import json
import logging
import re
import sys

LOGGER = logging.getLogger("pdf2audiobook")
_OVERRIDE_LEVEL: int | None = None
_CACHE_DIRECTORY_WARNING_EMITTED = False
# The CLI default: warnings are shown, stage progress is not, and a failed
# command is reported by its own "Error:" line or JSON diagnostic alone.
_DEFAULT_POLICY = False
ALLOWED = frozenset({"command", "stage", "status", "provider", "error_code", "count"})
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")


def _safe(value: object) -> str:
    if isinstance(value, str) and IDENTIFIER.fullmatch(value):
        return value
    return "[redacted]"


class EventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, object] = {
            "level": record.levelname.lower(),
            "event": "unstructured_message_redacted",
        }
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


class _DefaultPolicyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not (
            _DEFAULT_POLICY
            and isinstance(record.msg, dict)
            and record.msg.get("event") == "command_failed"
        )


class CurrentStderrHandler(logging.StreamHandler):
    """Write to the active stderr stream, including when CLI tests swap it."""

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


def configure_logging(
    *, verbose: bool = False, quiet: bool = False, log_level: str = "INFO"
) -> None:
    if verbose and quiet:
        raise ValueError("--verbose and --quiet cannot be combined")
    handler = CurrentStderrHandler()
    handler.setFormatter(EventFormatter())
    handler.addFilter(_DefaultPolicyFilter())
    for old in LOGGER.handlers[:]:
        LOGGER.removeHandler(old)
        old.close()
    LOGGER.addHandler(handler)
    global _OVERRIDE_LEVEL, _DEFAULT_POLICY
    _DEFAULT_POLICY = False
    configured = getattr(logging, log_level.upper(), logging.INFO)
    _OVERRIDE_LEVEL = logging.DEBUG if verbose else logging.ERROR if quiet else None
    LOGGER.setLevel(_OVERRIDE_LEVEL if _OVERRIDE_LEVEL is not None else configured)
    LOGGER.propagate = False


def use_default_event_policy() -> None:
    """Show warnings only, and leave failure reporting to the command itself."""
    global _DEFAULT_POLICY
    _DEFAULT_POLICY = True
    if LOGGER.handlers and _OVERRIDE_LEVEL is None:
        LOGGER.setLevel(logging.WARNING)


def configure_from_settings(
    log_level: str, *, cache_directory_configured: bool, explicit: bool = True
) -> None:
    """Apply file/environment logging policy after settings are loaded.

    ``explicit`` is false when ``general.log_level`` is only the built-in
    default, which keeps the CLI's default policy.
    """
    global _CACHE_DIRECTORY_WARNING_EMITTED, _DEFAULT_POLICY
    if explicit and _OVERRIDE_LEVEL is None:
        _DEFAULT_POLICY = False
    if LOGGER.handlers:
        configured = getattr(logging, log_level.upper(), logging.INFO)
        if _OVERRIDE_LEVEL is not None:
            LOGGER.setLevel(_OVERRIDE_LEVEL)
        elif _DEFAULT_POLICY and not explicit:
            LOGGER.setLevel(logging.WARNING)
        else:
            LOGGER.setLevel(configured)
    if cache_directory_configured and not _CACHE_DIRECTORY_WARNING_EMITTED:
        _CACHE_DIRECTORY_WARNING_EMITTED = True
        log_event("cache_directory_ignored", level=logging.WARNING)


def log_event(event: str, *, level: int = logging.INFO, **fields: object) -> None:
    LOGGER.log(level, {"event": event, "fields": fields})
