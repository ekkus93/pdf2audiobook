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
_CLI_ACTIVE = False
_OUTPUT_MODE: str | None = None
_VERBOSE = False
_QUIET = False
_EXPLICIT_LOG_LEVEL = False
_PENDING_EVENTS: list[tuple[str, int, dict[str, object]]] = []
_WARNING_CODES: list[str] = []
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
    global _OVERRIDE_LEVEL, _DEFAULT_POLICY, _VERBOSE, _QUIET, _EXPLICIT_LOG_LEVEL
    global _CLI_ACTIVE, _OUTPUT_MODE, _PENDING_EVENTS, _WARNING_CODES
    _DEFAULT_POLICY = False
    _CLI_ACTIVE = False
    _OUTPUT_MODE = None
    _PENDING_EVENTS = []
    _WARNING_CODES = []
    configured = getattr(logging, log_level.upper(), logging.INFO)
    _OVERRIDE_LEVEL = logging.DEBUG if verbose else logging.ERROR if quiet else None
    _VERBOSE = verbose
    _QUIET = quiet
    _EXPLICIT_LOG_LEVEL = False
    LOGGER.setLevel(_OVERRIDE_LEVEL if _OVERRIDE_LEVEL is not None else configured)
    LOGGER.propagate = False


def use_default_event_policy() -> None:
    """Show warnings only, and leave failure reporting to the command itself."""
    global _DEFAULT_POLICY
    _DEFAULT_POLICY = True
    if LOGGER.handlers and _OVERRIDE_LEVEL is None:
        LOGGER.setLevel(logging.WARNING)


def begin_cli_command() -> None:
    """Buffer early events until the command's output mode is known."""
    global _CLI_ACTIVE, _OUTPUT_MODE, _PENDING_EVENTS, _WARNING_CODES
    _CLI_ACTIVE = True
    _OUTPUT_MODE = None
    _PENDING_EVENTS = []
    _WARNING_CODES = []


def _remember_warning(event: str) -> None:
    if event not in _WARNING_CODES:
        _WARNING_CODES.append(event)


def _dispatch(event: str, level: int, fields: dict[str, object]) -> None:
    if not _CLI_ACTIVE or _OUTPUT_MODE is None:
        LOGGER.log(level, {"event": event, "fields": fields})
        return
    structured = _VERBOSE or _EXPLICIT_LOG_LEVEL
    if level == logging.WARNING and not structured:
        if _QUIET:
            return
        _remember_warning(event)
        if _OUTPUT_MODE == "human":
            description = {
                "cache_directory_ignored": "cache.directory is ignored unless explicitly configured",
                "review_warning": "Book review is required before conversion",
                "analysis_preserved": "Approved analysis was kept because its inputs are unchanged",
                "audio_cleanup_candidate_skipped": (
                    "An audio cleanup candidate could not be inspected and was left untouched"
                ),
                "degraded_output": "Some chapters produced degraded output",
            }.get(event, event.replace("_", " "))
            sys.stderr.write(f"Warning: {description}.\n")
        return
    if event == "command_failed" and not structured:
        return
    LOGGER.log(level, {"event": event, "fields": fields})


def set_output_mode(json_output: bool) -> None:
    """Choose human or JSON event rendering and flush buffered records."""
    global _OUTPUT_MODE, _PENDING_EVENTS
    _OUTPUT_MODE = "json" if json_output else "human"
    pending, _PENDING_EVENTS = _PENDING_EVENTS, []
    for event, level, fields in pending:
        _dispatch(event, level, fields)


def take_warning_codes() -> list[str]:
    warnings = list(_WARNING_CODES)
    _WARNING_CODES.clear()
    return warnings


def configure_from_settings(
    log_level: str, *, cache_directory_configured: bool, explicit: bool = True
) -> None:
    """Apply file/environment logging policy after settings are loaded.

    ``explicit`` is false when ``general.log_level`` is only the built-in
    default, which keeps the CLI's default policy.
    """
    global _CACHE_DIRECTORY_WARNING_EMITTED, _DEFAULT_POLICY, _EXPLICIT_LOG_LEVEL
    _EXPLICIT_LOG_LEVEL = explicit
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
    if _CLI_ACTIVE and _OUTPUT_MODE is None:
        _PENDING_EVENTS.append((event, level, dict(fields)))
        return
    _dispatch(event, level, dict(fields))
