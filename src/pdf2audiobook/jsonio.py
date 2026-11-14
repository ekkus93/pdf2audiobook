"""Bounded, defensive JSON loading for untrusted local cache files."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _reject_constant(_value: str) -> None:
    raise ValueError("non-standard JSON constant")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _within_depth(payload: bytes, max_depth: int) -> bool:
    """Count JSON container nesting without decoding or recursing."""
    depth = 0
    in_string = False
    escaped = False
    for byte in payload:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):
            depth += 1
            if depth > max_depth:
                return False
        elif byte in (0x5D, 0x7D):
            # A closer before its opener is invalid JSON; json.loads rejects it.
            depth -= 1
    return depth == 0 and not in_string


def json_within_depth(value: Any, max_depth: int) -> bool:
    """Check already-decoded JSON containers iteratively, without recursion."""
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if not isinstance(item, (dict, list)):
            continue
        if depth >= max_depth:
            return False
        children = item.values() if isinstance(item, dict) else item
        pending.extend((child, depth + 1) for child in children)
    return True


class JSONTooLargeError(Exception):
    """A bounded read found more bytes than the caller allows."""


def _check_bounds(max_bytes: int, max_depth: int) -> None:
    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes < 1
        or isinstance(max_depth, bool)
        or not isinstance(max_depth, int)
        or max_depth < 0
    ):
        raise ValueError("JSON bounds must be non-negative integers")


def _read_at_most(path: Path, max_bytes: int) -> bytes | None:
    """Read up to ``max_bytes + 1`` bytes through one handle; unreadable is ``None``.

    The extra byte lets callers tell an over-limit file from one exactly at the
    limit using the bytes actually read, not a separate size check.
    """
    try:
        with path.open("rb") as stream:
            return stream.read(max_bytes + 1)
    except (OSError, ValueError, TypeError):
        return None


def _decode_bounded(payload: bytes, max_depth: int) -> Any | None:
    try:
        if not _within_depth(payload, max_depth):
            return None
        parsed = json.loads(
            payload,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
        return parsed if json_within_depth(parsed, max_depth) else None
    except (UnicodeError, ValueError, TypeError, RecursionError):
        return None


def load_bounded_json(path: Path, *, max_bytes: int, max_depth: int) -> Any | None:
    """Read and parse a bounded JSON cache entry; malformed files are cache misses.

    The limits are checked before decoding. File and decoding errors intentionally
    return ``None`` so cache callers can regenerate the artifact.
    """
    _check_bounds(max_bytes, max_depth)
    payload = _read_at_most(path, max_bytes)
    if payload is None or len(payload) > max_bytes:
        return None
    return _decode_bounded(payload, max_depth)


def load_size_checked_json(path: Path, *, max_bytes: int, max_depth: int) -> Any | None:
    """Like ``load_bounded_json``, but an over-limit file raises ``JSONTooLargeError``.

    The size decision comes from the bytes read through the same open handle, so a
    file that grows or is replaced after any earlier size check is still detected.
    Missing, unreadable, malformed and over-depth files return ``None``.
    """
    _check_bounds(max_bytes, max_depth)
    payload = _read_at_most(path, max_bytes)
    if payload is None:
        return None
    if len(payload) > max_bytes:
        raise JSONTooLargeError
    return _decode_bounded(payload, max_depth)
