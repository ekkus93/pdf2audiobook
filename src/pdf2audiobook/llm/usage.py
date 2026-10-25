"""Shared validation for provider-reported token usage."""

from __future__ import annotations

from typing import Literal, TypeAlias, TypeGuard

MAX_SIGNED_TOKEN_COUNT = (1 << 63) - 1
AttemptOutcome: TypeAlias = Literal["unbilled", "rejected", "settled"]


def valid_usage_count(value: object) -> TypeGuard[int]:
    """Return whether one token count fits the ledger's signed integer format."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_SIGNED_TOKEN_COUNT
    )


def verified_usage(usage: object) -> dict[str, int] | None:
    """Return complete, internally consistent provider usage, or no verified record."""
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    if not all(valid_usage_count(value) for value in (prompt, completion, total)):
        return None
    assert isinstance(prompt, int) and isinstance(completion, int) and isinstance(total, int)
    if total < prompt + completion:
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }
