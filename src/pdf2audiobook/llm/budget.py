"""Crash-conservative, transactional per-book LLM request and usage ledger.

SQLite's BEGIN IMMEDIATE serializes reservations across concurrent processes.
Pending/unknown requests are deliberately never presumed free after a crash.
No document text, prompt, response, credentials or raw model IDs are stored.
"""

from __future__ import annotations

import math
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.usage import (
    MAX_SIGNED_TOKEN_COUNT,
    valid_usage_count,
    verified_usage,
)


def read_ledger_schema_version(path: Path) -> int:
    """Read ledger metadata through SQLite's read-only URI without migration."""
    try:
        with sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True) as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])
    except (sqlite3.Error, TypeError, ValueError):
        raise LLMError("Cannot access per-book LLM budget ledger") from None


class BookLLMBudgetLedger:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        try:
            if readonly:
                connection = sqlite3.connect(
                    f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True, timeout=15
                )
            else:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(self.path, timeout=15)
            connection.execute("PRAGMA busy_timeout=15000")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise LLMError("Unsupported LLM budget ledger schema version")
            if readonly:
                if version not in (0, 1, 2, 3):
                    raise LLMError("Unsupported LLM budget ledger schema version")
                return connection
            connection.execute(
                "CREATE TABLE IF NOT EXISTS calls ("
                "id INTEGER PRIMARY KEY, request_hash TEXT NOT NULL, "
                "provider_hash TEXT NOT NULL, status TEXT NOT NULL, "
                "prompt_tokens INTEGER, completion_tokens INTEGER, "
                "total_tokens INTEGER, estimated_usd TEXT, "
                "upper_bound_tokens INTEGER, upper_bound_usd TEXT)"
            )
            if version < 3:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(calls)")}
                if "upper_bound_tokens" not in columns:
                    connection.execute("ALTER TABLE calls ADD COLUMN upper_bound_tokens INTEGER")
                if "upper_bound_usd" not in columns:
                    connection.execute("ALTER TABLE calls ADD COLUMN upper_bound_usd TEXT")
                connection.execute("PRAGMA user_version=3")
            connection.commit()
            return connection
        except sqlite3.Error:
            # SQLite diagnostics may contain private workspace paths.
            raise LLMError("Cannot access per-book LLM budget ledger") from None

    @staticmethod
    def _stats(connection: sqlite3.Connection) -> dict:
        # Fail closed on malformed/corrupted ledgers rather than undercounting.
        columns = {row[1] for row in connection.execute("PRAGMA table_info(calls)")}
        token_bound_expr = "upper_bound_tokens" if "upper_bound_tokens" in columns else "NULL"
        cost_bound_expr = "upper_bound_usd" if "upper_bound_usd" in columns else "NULL"
        bound_validation = ""
        if "upper_bound_tokens" in columns:
            bound_validation += (
                " OR (upper_bound_tokens IS NOT NULL AND (typeof(upper_bound_tokens) != 'integer' "
                "OR upper_bound_tokens < 0 OR status NOT IN ('pending','unknown')))"
            )
        if "upper_bound_usd" in columns:
            bound_validation += (
                " OR (upper_bound_usd IS NOT NULL AND (typeof(upper_bound_usd) != 'text' "
                "OR status NOT IN ('pending','unknown')))"
            )
        invalid = connection.execute(
            "SELECT COUNT(*) FROM calls WHERE status NOT IN ('pending','complete','unknown','unbilled','rejected') "
            "OR (status='complete' AND (prompt_tokens IS NULL OR "
            "completion_tokens IS NULL OR total_tokens IS NULL)) "
            "OR (status!='complete' AND (prompt_tokens IS NOT NULL OR "
            "completion_tokens IS NOT NULL OR total_tokens IS NOT NULL "
            "OR estimated_usd IS NOT NULL)) "
            "OR (status='complete' AND (typeof(prompt_tokens) != 'integer' "
            "OR typeof(completion_tokens) != 'integer' "
            "OR typeof(total_tokens) != 'integer')) "
            "OR (estimated_usd IS NOT NULL AND typeof(estimated_usd) != 'text') "
            "OR prompt_tokens < 0 OR completion_tokens < 0 OR total_tokens < 0 "
            "OR (status='complete' AND total_tokens < prompt_tokens + completion_tokens)"
            + bound_validation
        ).fetchone()[0]
        if invalid:
            raise LLMError("Invalid per-book LLM budget ledger entries")
        token_limit = (1 << 63) - 1
        counts = {
            "requests_started": 0,
            "unresolved_requests": 0,
            "reported_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "unpriced_requests": 0,
        }
        # Open attempts with no recorded upper bound (legacy rows, direct
        # reservations) cannot be charged conservatively, so they block.
        unbounded_open = 0
        for (
            status,
            prompt,
            completion,
            total,
            estimated,
            upper_tokens,
            upper_usd,
        ) in connection.execute(
            "SELECT status,prompt_tokens,completion_tokens,total_tokens,estimated_usd,"
            f"{token_bound_expr},{cost_bound_expr} FROM calls"
        ):
            if status != "unbilled":
                counts["requests_started"] += 1
            if status in {"pending", "unknown"}:
                counts["unresolved_requests"] += 1
                if upper_tokens is None:
                    unbounded_open += 1
                else:
                    counts["reported_tokens"] += upper_tokens
                if upper_usd is None:
                    counts["unpriced_requests"] += 1
            elif status == "complete":
                counts["reported_tokens"] += total
                counts["prompt_tokens"] += prompt
                counts["completion_tokens"] += completion
                if estimated is None:
                    counts["unpriced_requests"] += 1
            if any(
                counts[key] > token_limit
                for key in ("reported_tokens", "prompt_tokens", "completion_tokens")
            ):
                raise LLMError("Cumulative token totals exceed supported range")
        if "upper_bound_usd" in columns:
            costs = connection.execute(
                "SELECT CASE WHEN status='complete' THEN estimated_usd "
                "WHEN status IN ('pending','unknown') THEN upper_bound_usd ELSE NULL END "
                "FROM calls WHERE (status='complete' AND estimated_usd IS NOT NULL) "
                "OR (status IN ('pending','unknown') AND upper_bound_usd IS NOT NULL)"
            ).fetchall()
        else:
            costs = connection.execute(
                "SELECT estimated_usd FROM calls WHERE status='complete' AND estimated_usd IS NOT NULL"
            ).fetchall()
        values = [Decimal(item[0]) for item in costs]
        if any(not amount.is_finite() or amount < 0 for amount in values):
            raise LLMError("Invalid per-book LLM cost entries")
        total_cost = sum(values, Decimal(0))
        # Decimal values may be finite yet overflow binary64 to Infinity.
        # Never serialize nonfinite cost estimates or weaken budget checks.
        estimated_cost = float(total_cost)
        if not math.isfinite(estimated_cost):
            raise LLMError("Invalid per-book LLM cost entries")
        return {
            **counts,
            "_unbounded_open": unbounded_open,
            "estimated_cost_usd": estimated_cost,
            # Keep precise decimal accounting for budget authorization, but
            # do not expose internal arithmetic state in the public report.
            "_exact_cost_usd": str(total_cost),
            "scope": "persistent_book_workspace",
        }

    @staticmethod
    def _check(
        stats: dict,
        *,
        max_requests: int | None,
        max_tokens: int | None,
        max_usd: float | None,
        postflight: bool = False,
    ) -> None:
        # An exactly exhausted limit may return its already-paid response.
        # A subsequent reservation still rejects equality before the next call.
        if max_requests is not None and stats["requests_started"] >= max_requests:
            raise LLMError("Per-book LLM request budget exhausted")
        if (max_tokens is not None or max_usd is not None) and stats["_unbounded_open"]:
            raise LLMError(
                "Per-book LLM budget has unresolved requests without a recorded bound; "
                "run 'pdf2audiobook budget resolve' before retrying"
            )
        if max_tokens is not None and (
            stats["reported_tokens"] > max_tokens
            if postflight
            else stats["reported_tokens"] >= max_tokens
        ):
            raise LLMError("Per-book LLM reported token budget reached or exceeded")
        if max_usd is not None and stats["unpriced_requests"]:
            raise LLMError("Per-book cost budget has unpriced earlier requests; inspect ledger")
        if max_usd is not None:
            cost = Decimal(str(stats.get("_exact_cost_usd", stats["estimated_cost_usd"])))
            limit = Decimal(str(max_usd))
            if cost > limit if postflight else cost >= limit:
                raise LLMError("Per-book LLM estimated cost budget reached or exceeded")

    def totals(self, *, readonly: bool = False) -> dict:
        try:
            with self._connect(readonly=readonly) as connection:
                stats = self._stats(connection)
                stats.pop("_exact_cost_usd", None)
                stats.pop("_unbounded_open", None)
                return stats
        except (sqlite3.Error, InvalidOperation):
            raise LLMError("Invalid per-book LLM budget ledger") from None

    def schema_version(self) -> int:
        """Read the schema version without opening a migration-capable connection."""
        return read_ledger_schema_version(self.path)

    def rows(self, *, readonly: bool = False) -> list[dict]:
        """Return the content-free accounting fields shown by the budget CLI."""
        try:
            with self._connect(readonly=readonly) as connection:
                self._stats(connection)
                result = connection.execute(
                    "SELECT id,status,prompt_tokens,completion_tokens,total_tokens,estimated_usd "
                    "FROM calls ORDER BY id"
                )
                return [
                    {
                        "id": row[0],
                        "status": row[1],
                        "prompt_tokens": row[2],
                        "completion_tokens": row[3],
                        "total_tokens": row[4],
                        "estimated_cost_usd": float(Decimal(row[5]))
                        if row[5] is not None
                        else None,
                    }
                    for row in result
                ]
        except (sqlite3.Error, InvalidOperation, ValueError, OverflowError):
            raise LLMError("Invalid per-book LLM budget ledger") from None

    def reserve(
        self,
        *,
        request_hash: str,
        provider_hash: str,
        max_requests: int | None,
        max_tokens: int | None,
        max_usd: float | None,
        upper_bound_tokens: int | None = None,
        upper_bound_usd: str | None = None,
    ) -> int:
        """Reserve one attempt. A missing bound is stored as unbounded and blocks later budgeted
        requests until the row is resolved."""
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                stats = self._stats(connection)
                self._check(
                    stats,
                    max_requests=max_requests,
                    max_tokens=max_tokens,
                    max_usd=max_usd,
                )
                if (
                    max_tokens is not None
                    and upper_bound_tokens is not None
                    and stats["reported_tokens"] + upper_bound_tokens > max_tokens
                ):
                    raise LLMError("Per-book LLM token budget cannot cover the next request")
                if max_usd is not None:
                    if upper_bound_usd is None:
                        raise LLMError("Per-book cost budget requires a bounded request cost")
                    if Decimal(stats["_exact_cost_usd"]) + Decimal(upper_bound_usd) > Decimal(
                        str(max_usd)
                    ):
                        raise LLMError("Per-book LLM cost budget cannot cover the next request")
                cursor = connection.execute(
                    "INSERT INTO calls (request_hash, provider_hash, status, upper_bound_tokens, upper_bound_usd) "
                    "VALUES (?, ?, 'pending', ?, ?)",
                    (request_hash, provider_hash, upper_bound_tokens, upper_bound_usd),
                )
                reservation_id = cursor.lastrowid
                if reservation_id is None:
                    raise LLMError("LLM budget reservation did not return a row ID")
                return reservation_id
        except (sqlite3.Error, InvalidOperation):
            raise LLMError("Cannot reserve per-book LLM budget") from None

    def settle(
        self,
        call_id: int,
        *,
        usage: dict | None,
        input_rate: float | None,
        output_rate: float | None,
        rejected: bool = False,
    ) -> None:
        if rejected:
            try:
                with self._connect() as connection:
                    result = connection.execute(
                        "UPDATE calls SET status='rejected', upper_bound_tokens=NULL, "
                        "upper_bound_usd=NULL WHERE id=? AND status='pending'",
                        (call_id,),
                    )
                    if result.rowcount != 1:
                        raise LLMError("LLM ledger request was already settled or missing")
                return
            except sqlite3.Error:
                raise LLMError("Cannot settle per-book LLM budget") from None
        # Validate each provider counter independently before using any of
        # them for persistent accounting. A failed or malformed response is
        # deliberately settled as unknown rather than undercounted.
        verified = verified_usage(usage)
        price = None
        if verified is not None and input_rate is not None and output_rate is not None:
            # Bad price configuration must never create negative/NaN charges or
            # be treated as a correctly priced successful provider request.
            try:
                input_price = Decimal(str(input_rate))
                output_price = Decimal(str(output_rate))
                if (
                    input_price.is_finite()
                    and input_price >= 0
                    and output_price.is_finite()
                    and output_price >= 0
                ):
                    price = str(
                        (
                            Decimal(verified["prompt_tokens"]) * input_price
                            + Decimal(verified["completion_tokens"]) * output_price
                        )
                        / Decimal(1_000_000)
                    )
            except (InvalidOperation, ValueError, TypeError):
                pass  # Preserve token counts; mark this request unpriced.
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                result = connection.execute(
                    "UPDATE calls SET status=?, prompt_tokens=?, completion_tokens=?, "
                    "total_tokens=?, estimated_usd=?, "
                    "upper_bound_tokens=CASE WHEN ?='complete' THEN NULL ELSE upper_bound_tokens END, "
                    "upper_bound_usd=CASE WHEN ?='complete' THEN NULL ELSE upper_bound_usd END "
                    "WHERE id=? AND status='pending'",
                    (
                        "complete" if verified is not None else "unknown",
                        verified["prompt_tokens"] if verified is not None else None,
                        verified["completion_tokens"] if verified is not None else None,
                        verified["total_tokens"] if verified is not None else None,
                        price,
                        "complete" if verified is not None else "unknown",
                        "complete" if verified is not None else "unknown",
                        call_id,
                    ),
                )
                if result.rowcount != 1:
                    raise LLMError("LLM ledger request was already settled or missing")
        except sqlite3.Error:
            raise LLMError("Cannot settle per-book LLM budget") from None

    def settle_unbilled(self, call_id: int) -> None:
        """Mark a request unsent only when transport evidence proves it."""
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                result = connection.execute(
                    "UPDATE calls SET status='unbilled', upper_bound_tokens=NULL, "
                    "upper_bound_usd=NULL WHERE id=? AND status='pending'",
                    (call_id,),
                )
                if result.rowcount != 1:
                    raise LLMError("LLM ledger request was already settled or missing")
        except sqlite3.Error:
            raise LLMError("Cannot settle per-book LLM budget") from None

    def resolve_unknown(
        self,
        call_id: int,
        *,
        usage: dict | None,
        input_rate: float | None,
        output_rate: float | None,
        unbilled: bool = False,
    ) -> str:
        """Resolve one pending/unknown request with validated accounting in one transaction."""
        if read_ledger_schema_version(self.path) < 3:
            raise LLMError("Legacy budget ledger cannot be resolved; re-create the ledger")
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT status FROM calls WHERE id=?", (call_id,)
                ).fetchone()
                if row is None:
                    raise LLMError("Budget request ID does not exist")
                if row[0] not in {"pending", "unknown"}:
                    raise LLMError("Budget request is already settled")
                if unbilled:
                    connection.execute(
                        "UPDATE calls SET status='unbilled', upper_bound_tokens=NULL, "
                        "upper_bound_usd=NULL WHERE id=?",
                        (call_id,),
                    )
                    return "unbilled"
                prompt = usage.get("prompt_tokens") if isinstance(usage, dict) else None
                completion = usage.get("completion_tokens") if isinstance(usage, dict) else None
                total = usage.get("total_tokens") if isinstance(usage, dict) else None
                if not all(valid_usage_count(value) for value in (prompt, completion, total)):
                    raise LLMError("Verified token counts are invalid")
                prompt = cast(int, prompt)
                completion = cast(int, completion)
                total = cast(int, total)
                if total < prompt + completion:
                    raise LLMError("Verified token counts exceed supported totals")
                limit = MAX_SIGNED_TOKEN_COUNT
                prior = connection.execute(
                    "SELECT prompt_tokens, completion_tokens, total_tokens, estimated_usd "
                    "FROM calls WHERE id != ? AND status='complete'",
                    (call_id,),
                ).fetchall()
                for column in range(3):
                    if (
                        sum(int(item[column]) for item in prior)
                        + (prompt, completion, total)[column]
                        > limit
                    ):
                        raise LLMError("Cumulative token totals exceed supported range")
                price = None
                if input_rate is not None and output_rate is not None:
                    input_price = Decimal(str(input_rate))
                    output_price = Decimal(str(output_rate))
                    if (
                        not input_price.is_finite()
                        or input_price < 0
                        or not output_price.is_finite()
                        or output_price < 0
                    ):
                        raise LLMError("Configured token prices are invalid")
                    price = str(
                        (Decimal(prompt) * input_price + Decimal(completion) * output_price)
                        / Decimal(1_000_000)
                    )
                connection.execute(
                    "UPDATE calls SET status='complete', prompt_tokens=?, completion_tokens=?, "
                    "total_tokens=?, estimated_usd=?, upper_bound_tokens=NULL, upper_bound_usd=NULL "
                    "WHERE id=?",
                    (prompt, completion, total, price, call_id),
                )
                # Everything `budget show` and later reservations sum, including
                # the upper bounds of other open rows, must still be representable.
                # A failure here rolls the whole transaction back.
                self._stats(connection)
                return "complete"
        except (sqlite3.Error, InvalidOperation, ValueError, TypeError, OverflowError):
            raise LLMError("Cannot resolve per-book LLM budget") from None

    def check_spend(self, *, max_tokens: int | None, max_usd: float | None) -> None:
        try:
            with self._connect() as connection:
                self._check(
                    self._stats(connection),
                    max_requests=None,
                    max_tokens=max_tokens,
                    max_usd=max_usd,
                    postflight=True,
                )
        except (sqlite3.Error, InvalidOperation):
            raise LLMError("Cannot inspect per-book LLM budget") from None
