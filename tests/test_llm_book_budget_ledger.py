"""Per-book LLM budget regression tests."""

import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.budget import BookLLMBudgetLedger
from pdf2audiobook.llm.cache import CachedLLMProvider


def test_new_book_ledger_has_no_requests(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    assert ledger.totals()["requests_started"] == 0


def test_reservation_increases_per_book_request_count(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    call_id = ledger.reserve(
        request_hash="a",
        provider_hash="b",
        max_requests=1,
        max_tokens=None,
        max_usd=None,
    )
    assert call_id == 1
    assert ledger.totals()["requests_started"] == 1


def test_pending_worst_case_reservation_allows_safe_retry_only(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    call_id = ledger.reserve(
        request_hash="a",
        provider_hash="b",
        max_requests=None,
        max_tokens=100,
        max_usd=None,
        upper_bound_tokens=40,
    )
    ledger.settle(call_id, usage=None, input_rate=None, output_rate=None)
    other = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    other.reserve(
        request_hash="c",
        provider_hash="b",
        max_requests=None,
        max_tokens=100,
        max_usd=None,
        upper_bound_tokens=40,
    )
    with pytest.raises(LLMError, match="token budget"):
        other.reserve(
            request_hash="d",
            provider_hash="b",
            max_requests=None,
            max_tokens=100,
            max_usd=None,
            upper_bound_tokens=30,
        )


def test_budget_resolve_accepts_pending_crash_rows_atomically(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    request_id = ledger.reserve(
        request_hash="a",
        provider_hash="b",
        max_requests=None,
        max_tokens=None,
        max_usd=None,
    )
    status = ledger.resolve_unknown(
        request_id,
        usage={"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        input_rate=1,
        output_rate=2,
    )
    assert status == "complete"
    assert ledger.rows()[0]["status"] == "complete"


class Metered:
    max_output_tokens = 32
    max_context_tokens = 4096

    def __init__(self):
        self.calls = 0
        self.last_usage = {}
        self.total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def complete_json(self, *, instructions, document_text):
        self.calls += 1
        self.last_usage = {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50}
        for key, value in self.last_usage.items():
            self.total_usage[key] += value
        return {"headings": []}


def test_metered_fixture(tmp_path):
    provider = Metered()
    worker = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="model",
        ledger_path=tmp_path / "budget.sqlite3",
    )
    assert worker.complete_json(instructions="task", document_text="A") == {"headings": []}
    assert BookLLMBudgetLedger(tmp_path / "budget.sqlite3").totals()["reported_tokens"] == 50


def test_budget_guard_rejects_second_request(tmp_path):
    provider = Metered()
    budget = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="model",
        ledger_path=tmp_path / "budget.sqlite3",
        max_requests=1,
    )
    budget.complete_json(instructions="task", document_text="A")
    with pytest.raises(LLMError, match="request budget"):
        budget.complete_json(instructions="task", document_text="B")
    assert provider.calls == 1


def test_token_ceiling_refuses_retry_when_worst_case_exceeds_limit(tmp_path):
    provider = Metered()
    budget = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="model",
        ledger_path=tmp_path / "budget.sqlite3",
        max_reported_tokens=200,
    )
    budget.complete_json(instructions="task", document_text="A")
    with pytest.raises(LLMError, match="token budget"):
        budget.complete_json(instructions="task", document_text="B")
    assert BookLLMBudgetLedger(tmp_path / "budget.sqlite3").totals()["reported_tokens"] == 50


def test_cost_budget_uses_explicit_rates(tmp_path):
    provider = Metered()
    budget = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="model",
        ledger_path=tmp_path / "budget.sqlite3",
        max_estimated_cost_usd=0.0003,
        input_cost_usd_per_million_tokens=2,
        output_cost_usd_per_million_tokens=1,
    )
    assert budget.complete_json(instructions="task", document_text="A") == {"headings": []}
    with pytest.raises(LLMError, match="cost budget"):
        budget.complete_json(instructions="task", document_text="B")
    assert provider.calls == 1
    assert BookLLMBudgetLedger(tmp_path / "budget.sqlite3").totals()[
        "estimated_cost_usd"
    ] == pytest.approx(0.00009)


def test_uncapped_provider_request_is_refused_under_token_budget(tmp_path):
    class Uncapped(Metered):
        max_context_tokens = None

    provider = Uncapped()
    budget = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="model",
        ledger_path=tmp_path / "budget.sqlite3",
        max_reported_tokens=1000,
    )
    with pytest.raises(LLMError, match="bounded output token cap"):
        budget.complete_json(instructions="task", document_text="A")
    assert provider.calls == 0


# --- Fail-closed paths (test coverage spec T1) ---------------------------------

_HUGE = (1 << 62) + 7  # two of these overflow the signed 64-bit token range


def _reserve(ledger, name="r"):
    return ledger.reserve(
        request_hash=name, provider_hash="p", max_requests=None, max_tokens=None, max_usd=None
    )


def _usage(total, prompt=0, completion=0):
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def _assert_content_free(message, tmp_path):
    assert str(tmp_path) not in message
    assert "sqlite" not in message.lower()


def test_settlement_that_would_overflow_the_ledger_is_recorded_as_unknown(tmp_path):
    """T1.a: the candidate complete row is rolled back to unknown with null counts."""
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    first, second = _reserve(ledger, "a"), _reserve(ledger, "b")
    ledger.settle(first, usage=_usage(_HUGE), input_rate=None, output_rate=None)

    ledger.settle(second, usage=_usage(_HUGE), input_rate=None, output_rate=None)

    rows = {row["id"]: row for row in ledger.rows()}
    assert rows[first]["status"] == "complete"
    assert rows[first]["total_tokens"] == _HUGE
    assert rows[second] == {
        "id": second,
        "status": "unknown",
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "estimated_cost_usd": None,
    }


@pytest.mark.parametrize(
    ("usage", "rates", "message"),
    [
        (_usage(-1), (None, None), "Verified token counts are invalid"),
        ({"prompt_tokens": 1}, (None, None), "Verified token counts are invalid"),
        (_usage(5, prompt=4, completion=4), (None, None), "Verified token counts exceed"),
        (_usage(10, prompt=5, completion=5), (-1.0, 1.0), "Configured token prices are invalid"),
        (
            _usage(10, prompt=5, completion=5),
            (1.0, float("inf")),
            "Configured token prices are invalid",
        ),
    ],
    ids=["negative", "incomplete", "total-below-parts", "negative-price", "infinite-price"],
)
def test_resolve_unknown_rejects_invalid_accounting_and_keeps_the_row(
    tmp_path, usage, rates, message
):
    """T1.b: each validation error leaves the open row exactly as it was."""
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    call_id = _reserve(ledger)
    before = ledger.rows()

    with pytest.raises(LLMError, match=message) as error:
        ledger.resolve_unknown(call_id, usage=usage, input_rate=rates[0], output_rate=rates[1])

    assert ledger.rows() == before
    _assert_content_free(str(error.value), tmp_path)


def test_resolve_unknown_refuses_a_cumulative_total_beyond_the_supported_range(tmp_path):
    """T1.b: resolving a row cannot push the completed totals past 2**63 - 1."""
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    done, open_row = _reserve(ledger, "a"), _reserve(ledger, "b")
    ledger.settle(done, usage=_usage(_HUGE), input_rate=None, output_rate=None)
    before = ledger.rows()

    with pytest.raises(LLMError, match="Cumulative token totals exceed supported range"):
        ledger.resolve_unknown(open_row, usage=_usage(_HUGE), input_rate=None, output_rate=None)

    assert ledger.rows() == before


@pytest.mark.parametrize(
    "settle",
    [
        lambda ledger, call_id: ledger.settle(
            call_id, usage=_usage(3, 1, 2), input_rate=None, output_rate=None
        ),
        lambda ledger, call_id: ledger.settle(
            call_id, usage=None, input_rate=None, output_rate=None, rejected=True
        ),
        lambda ledger, call_id: ledger.settle_unbilled(call_id),
    ],
    ids=["settle", "reject", "unbilled"],
)
@pytest.mark.parametrize("target", ["settled", "missing"])
def test_settling_a_settled_or_missing_call_changes_nothing(tmp_path, settle, target):
    """T1.c: a second settlement, of any kind, is refused."""
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    call_id = _reserve(ledger)
    ledger.settle(call_id, usage=_usage(3, 1, 2), input_rate=None, output_rate=None)
    before = ledger.rows()

    with pytest.raises(LLMError, match="LLM ledger request was already settled or missing"):
        settle(ledger, call_id if target == "settled" else call_id + 99)

    assert ledger.rows() == before


def _legacy_ledger(path, version, columns):
    import sqlite3

    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE calls (id INTEGER PRIMARY KEY, request_hash TEXT NOT NULL, "
            "provider_hash TEXT NOT NULL, status TEXT NOT NULL, prompt_tokens INTEGER, "
            "completion_tokens INTEGER, total_tokens INTEGER, estimated_usd TEXT"
            + "".join(f", {column}" for column in columns)
            + ")"
        )
        connection.execute(
            "INSERT INTO calls (request_hash, provider_hash, status, prompt_tokens, "
            "completion_tokens, total_tokens, estimated_usd) "
            "VALUES ('a', 'p', 'complete', 1, 2, 3, '0.5')"
        )
        connection.execute(f"PRAGMA user_version={version}")


@pytest.mark.parametrize(
    ("version", "columns"),
    [(1, []), (2, ["upper_bound_tokens INTEGER"])],
    ids=["v1-no-bound-columns", "v2-token-bound-only"],
)
def test_older_ledger_is_migrated_to_version_three_with_its_rows(tmp_path, version, columns):
    """T1.d: missing upper-bound columns are added and the version becomes 3."""
    path = tmp_path / "budget.sqlite3"
    _legacy_ledger(path, version, columns)
    ledger = BookLLMBudgetLedger(path)

    rows = ledger.rows()

    assert ledger.schema_version() == 3
    import sqlite3

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(calls)")}
    assert {"upper_bound_tokens", "upper_bound_usd"} <= columns
    bounded = ledger.reserve(
        request_hash="b",
        provider_hash="p",
        max_requests=None,
        max_tokens=100,
        max_usd=1.0,
        upper_bound_tokens=10,
        upper_bound_usd="0.01",
    )
    assert bounded == 2
    assert rows == [
        {
            "id": 1,
            "status": "complete",
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
            "estimated_cost_usd": 0.5,
        }
    ]


@pytest.mark.parametrize("readonly", [False, True])
def test_unsupported_ledger_schema_version_is_refused(tmp_path, readonly):
    """T1.d: a future schema version is never read or migrated."""
    import sqlite3

    path = tmp_path / "budget.sqlite3"
    BookLLMBudgetLedger(path).totals()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=4")

    with pytest.raises(LLMError, match="Unsupported LLM budget ledger schema version"):
        BookLLMBudgetLedger(path).totals(readonly=readonly)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4


def test_unreadable_ledger_fails_with_a_fixed_message(tmp_path):
    """T1.d: a file that is not a database can't be inspected or listed."""
    path = tmp_path / "budget.sqlite3"
    path.write_bytes(b"not a database, " * 64)
    ledger = BookLLMBudgetLedger(path)

    with pytest.raises(LLMError, match="^Cannot access per-book LLM budget ledger$") as access:
        ledger.schema_version()
    with pytest.raises(LLMError) as listing:
        ledger.rows()

    for error in (access, listing):
        _assert_content_free(str(error.value), tmp_path)


def test_ledger_with_an_unparseable_cost_is_refused_when_listed(tmp_path):
    """T1.d: a cost entry that isn't a number makes the listing fail closed."""
    import sqlite3

    path = tmp_path / "budget.sqlite3"
    ledger = BookLLMBudgetLedger(path)
    call_id = _reserve(ledger)
    ledger.settle(call_id, usage=_usage(3, 1, 2), input_rate=1.0, output_rate=1.0)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE calls SET estimated_usd='not-a-number'")

    with pytest.raises(LLMError, match="^Invalid per-book LLM budget ledger$"):
        ledger.rows()
