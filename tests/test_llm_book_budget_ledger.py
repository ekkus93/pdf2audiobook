"""Per-book LLM budget regression tests."""

from pdf2audiobook.llm.budget import BookLLMBudgetLedger


def test_new_book_ledger_has_no_requests(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / 'budget.sqlite3')
    assert ledger.totals()['requests_started'] == 0


def test_reservation_increases_per_book_request_count(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / 'budget.sqlite3')
    call_id = ledger.reserve(
        request_hash='a', provider_hash='b',
        max_requests=1, max_tokens=None, max_usd=None,
    )
    assert call_id == 1
    assert ledger.totals()['requests_started'] == 1
