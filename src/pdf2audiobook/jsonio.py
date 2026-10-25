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
            depth -= 1
            if depth < 0:
                return False
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


def load_bounded_json(path: Path, *, max_bytes: int, max_depth: int) -> Any | None:
    """Read and parse a bounded JSON cache entry; malformed files are cache misses.

    The limits are checked before decoding. File and decoding errors intentionally
    return ``None`` so cache callers can regenerate the artifact.
    """
    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes < 1
        or isinstance(max_depth, bool)
        or not isinstance(max_depth, int)
        or max_depth < 0
    ):
        raise ValueError("JSON bounds must be non-negative integers")
    try:
        with path.open("rb") as stream:
            payload = stream.read(max_bytes + 1)
        if len(payload) > max_bytes or not _within_depth(payload, max_depth):
            return None
        parsed = json.loads(
            payload,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
        return parsed if json_within_depth(parsed, max_depth) else None
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        return None
