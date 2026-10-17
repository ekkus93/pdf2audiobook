"""Per-book LLM budget regression tests."""

from pdf2audiobook.llm.budget import BookLLMBudgetLedger


def test_new_book_ledger_has_no_requests(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / 'budget.sqlite3')
    assert ledger.totals()['requests_started'] == 0
