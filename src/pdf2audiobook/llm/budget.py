"""Crash-conservative, transactional per-book LLM request and usage ledger.

SQLite's BEGIN IMMEDIATE serializes reservations across concurrent processes.
Pending/unknown requests are deliberately never presumed free after a crash.
No document text, prompt, response, credentials or raw model IDs are stored.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pdf2audiobook.errors import LLMError


class BookLLMBudgetLedger:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=15)
            connection.execute("PRAGMA busy_timeout=15000")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise LLMError("Unsupported LLM budget ledger schema version")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS calls ("
                "id INTEGER PRIMARY KEY, request_hash TEXT NOT NULL, "
                "provider_hash TEXT NOT NULL, status TEXT NOT NULL, "
                "prompt_tokens INTEGER, completion_tokens INTEGER, "
                "total_tokens INTEGER, estimated_usd TEXT)"
            )
            if version == 0:
                connection.execute("PRAGMA user_version=1")
            connection.commit()
            return connection
        except sqlite3.Error as exc:
            raise LLMError("Cannot access per-book LLM budget ledger") from exc

    @staticmethod
    def _stats(connection: sqlite3.Connection) -> dict:
        # Fail closed on malformed/corrupted ledgers rather than undercounting.
        invalid = connection.execute(
            "SELECT COUNT(*) FROM calls WHERE status NOT IN ('pending','complete','unknown') "
            "OR (status='complete' AND (prompt_tokens IS NULL OR "
            "completion_tokens IS NULL OR total_tokens IS NULL)) "
            "OR prompt_tokens < 0 OR completion_tokens < 0 OR total_tokens < 0 "
            "OR (status='complete' AND total_tokens < prompt_tokens + completion_tokens)"
        ).fetchone()[0]
        if invalid:
            raise LLMError("Invalid per-book LLM budget ledger entries")
        row = connection.execute(
            "SELECT COUNT(*), "
            "COALESCE(SUM(CASE WHEN status != 'complete' THEN 1 ELSE 0 END), 0), "
            "COALESCE(SUM(total_tokens), 0), "
            "COALESCE(SUM(prompt_tokens), 0), "
            "COALESCE(SUM(completion_tokens), 0), "
            "COALESCE(SUM(CASE WHEN status='complete' AND estimated_usd IS NULL "
            "THEN 1 ELSE 0 END), 0) FROM calls"
        ).fetchone()
        costs = connection.execute(
            "SELECT estimated_usd FROM calls WHERE estimated_usd IS NOT NULL"
        ).fetchall()
        values = [Decimal(item[0]) for item in costs]
        if any(not amount.is_finite() or amount < 0 for amount in values):
            raise LLMError("Invalid per-book LLM cost entries")
        total_cost = sum(values, Decimal(0))
        return {
            "requests_started": row[0],
            "unresolved_requests": row[1],
            "reported_tokens": row[2],
            "prompt_tokens": row[3],
            "completion_tokens": row[4],
            "unpriced_requests": row[5],
            "estimated_cost_usd": float(total_cost),
            "scope": "persistent_book_workspace",
        }

    @staticmethod
    def _check(
        stats: dict, *, max_requests: int | None,
        max_tokens: int | None, max_usd: float | None,
    ) -> None:
        if max_requests is not None and stats["requests_started"] >= max_requests:
            raise LLMError("Per-book LLM request budget exhausted")
        if (max_tokens is not None or max_usd is not None) and stats[
            "unresolved_requests"
        ]:
            raise LLMError(
                "Per-book LLM budget has unresolved requests; inspect ledger before retrying"
            )
        if max_tokens is not None and stats["reported_tokens"] >= max_tokens:
            raise LLMError("Per-book LLM reported token budget reached or exceeded")
        if max_usd is not None and stats["unpriced_requests"]:
            raise LLMError(
                "Per-book cost budget has unpriced earlier requests; inspect ledger"
            )
        if max_usd is not None and Decimal(
            str(stats["estimated_cost_usd"])
        ) >= Decimal(str(max_usd)):
            raise LLMError("Per-book LLM estimated cost budget reached or exceeded")

    def totals(self) -> dict:
        try:
            with self._connect() as connection:
                return self._stats(connection)
        except (sqlite3.Error, InvalidOperation) as exc:
            raise LLMError("Invalid per-book LLM budget ledger") from exc

    def reserve(
        self, *, request_hash: str, provider_hash: str,
        max_requests: int | None, max_tokens: int | None, max_usd: float | None,
    ) -> int:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._check(
                    self._stats(connection), max_requests=max_requests,
                    max_tokens=max_tokens, max_usd=max_usd,
                )
                cursor = connection.execute(
                    "INSERT INTO calls (request_hash, provider_hash, status) "
                    "VALUES (?, ?, 'pending')",
                    (request_hash, provider_hash),
                )
                reservation_id = cursor.lastrowid
                if reservation_id is None:
                    raise LLMError("LLM budget reservation did not return a row ID")
                return reservation_id
        except (sqlite3.Error, InvalidOperation) as exc:
            raise LLMError("Cannot reserve per-book LLM budget") from exc

    def settle(
        self, call_id: int, *, usage: dict | None,
        input_rate: float | None, output_rate: float | None,
    ) -> None:
        # Validate each provider counter independently before using any of
        # them for persistent accounting. A failed or malformed response is
        # deliberately settled as unknown rather than undercounted.
        verified: dict[str, int] | None = None
        if isinstance(usage, dict):
            prompt = usage.get("prompt_tokens")
            completion = usage.get("completion_tokens")
            total = usage.get("total_tokens")
            if (
                isinstance(prompt, int) and not isinstance(prompt, bool)
                and isinstance(completion, int) and not isinstance(completion, bool)
                and isinstance(total, int) and not isinstance(total, bool)
                and prompt >= 0 and completion >= 0
                and total >= prompt + completion
            ):
                verified = {
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": total,
                }
        price = None
        if verified is not None and input_rate is not None and output_rate is not None:
            price = str((
                Decimal(verified["prompt_tokens"]) * Decimal(str(input_rate))
                + Decimal(verified["completion_tokens"]) * Decimal(str(output_rate))
            ) / Decimal(1_000_000))
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                result = connection.execute(
                    "UPDATE calls SET status=?, prompt_tokens=?, completion_tokens=?, "
                    "total_tokens=?, estimated_usd=? WHERE id=? AND status='pending'",
                    (
                        "complete" if verified is not None else "unknown",
                        verified["prompt_tokens"] if verified is not None else None,
                        verified["completion_tokens"] if verified is not None else None,
                        verified["total_tokens"] if verified is not None else None,
                        price, call_id,
                    ),
                )
                if result.rowcount != 1:
                    raise LLMError("LLM ledger request was already settled or missing")
        except sqlite3.Error as exc:
            raise LLMError("Cannot settle per-book LLM budget") from exc

    def check_spend(self, *, max_tokens: int | None, max_usd: float | None) -> None:
        try:
            with self._connect() as connection:
                self._check(
                    self._stats(connection), max_requests=None,
                    max_tokens=max_tokens, max_usd=max_usd,
                )
        except (sqlite3.Error, InvalidOperation) as exc:
            raise LLMError("Cannot inspect per-book LLM budget") from exc
