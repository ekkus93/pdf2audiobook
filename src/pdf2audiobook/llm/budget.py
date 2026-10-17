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
        row = connection.execute(
            "SELECT COUNT(*), "
            "COALESCE(SUM(CASE WHEN status != 'complete' THEN 1 ELSE 0 END), 0), "
            "COALESCE(SUM(total_tokens), 0), "
            "COALESCE(SUM(prompt_tokens), 0), "
            "COALESCE(SUM(completion_tokens), 0) FROM calls"
        ).fetchone()
        costs = connection.execute(
            "SELECT estimated_usd FROM calls WHERE estimated_usd IS NOT NULL"
        ).fetchall()
        total_cost = sum((Decimal(item[0]) for item in costs), Decimal(0))
        return {
            "requests_started": row[0],
            "unresolved_requests": row[1],
            "reported_tokens": row[2],
            "prompt_tokens": row[3],
            "completion_tokens": row[4],
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
                return int(cursor.lastrowid)
        except (sqlite3.Error, InvalidOperation) as exc:
            raise LLMError("Cannot reserve per-book LLM budget") from exc

    def settle(
        self, call_id: int, *, usage: dict | None,
        input_rate: float | None, output_rate: float | None,
    ) -> None:
        known = (
            isinstance(usage, dict)
            and all(
                isinstance(usage.get(key), int)
                and not isinstance(usage[key], bool)
                and usage[key] >= 0
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            )
        )
        price = None
        if known and input_rate is not None and output_rate is not None:
            price = str((
                Decimal(usage["prompt_tokens"]) * Decimal(str(input_rate))
                + Decimal(usage["completion_tokens"]) * Decimal(str(output_rate))
            ) / Decimal(1_000_000))
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                result = connection.execute(
                    "UPDATE calls SET status=?, prompt_tokens=?, completion_tokens=?, "
                    "total_tokens=?, estimated_usd=? WHERE id=? AND status='pending'",
                    (
                        "complete" if known else "unknown",
                        usage["prompt_tokens"] if known else None,
                        usage["completion_tokens"] if known else None,
                        usage["total_tokens"] if known else None,
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
