"""Per-book LLM budget regression tests."""

import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm.budget import BookLLMBudgetLedger
from pdf2audiobook.llm.cache import CachedLLMProvider


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


def test_pending_budget_reservation_blocks_next_worker(tmp_path):
    ledger = BookLLMBudgetLedger(tmp_path / 'budget.sqlite3')
    ledger.reserve(
        request_hash='a', provider_hash='b',
        max_requests=None, max_tokens=100, max_usd=None,
    )
    with pytest.raises(LLMError, match='unresolved requests'):
        BookLLMBudgetLedger(tmp_path / 'budget.sqlite3').reserve(
            request_hash='c', provider_hash='b',
            max_requests=None, max_tokens=100, max_usd=None,
        )


class Metered:
    def __init__(self):
        self.calls = 0
        self.last_usage = {}
        self.total_usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}

    def complete_json(self, *, instructions, document_text):
        self.calls += 1
        self.last_usage = {'prompt_tokens': 40, 'completion_tokens': 10, 'total_tokens': 50}
        for key, value in self.last_usage.items():
            self.total_usage[key] += value
        return {'headings': []}


def test_metered_fixture(tmp_path):
    provider = Metered()
    worker = CachedLLMProvider(
        provider, cache_dir=tmp_path / 'cache',
        identity='model', ledger_path=tmp_path / 'budget.sqlite3',
    )
    assert worker.complete_json(instructions='task', document_text='A') == {'headings': []}
    assert BookLLMBudgetLedger(tmp_path / 'budget.sqlite3').totals()['reported_tokens'] == 50


def test_budget_guard_rejects_second_request(tmp_path):
    provider = Metered()
    budget = CachedLLMProvider(
        provider, cache_dir=tmp_path / 'cache',
        identity='model', ledger_path=tmp_path / 'budget.sqlite3',
        max_requests=1,
    )
    budget.complete_json(instructions='task', document_text='A')
    with pytest.raises(LLMError, match='request budget'):
        budget.complete_json(instructions='task', document_text='B')
    assert provider.calls == 1


def test_token_ceiling_records_response_that_crosses_limit(tmp_path):
    provider = Metered()
    budget = CachedLLMProvider(
        provider, cache_dir=tmp_path / 'cache',
        identity='model', ledger_path=tmp_path / 'budget.sqlite3',
        max_reported_tokens=75,
    )
    budget.complete_json(instructions='task', document_text='A')
    with pytest.raises(LLMError, match='token budget'):
        budget.complete_json(instructions='task', document_text='B')
    assert BookLLMBudgetLedger(tmp_path / 'budget.sqlite3').totals()['reported_tokens'] == 100


def test_cost_budget_uses_explicit_rates(tmp_path):
    provider = Metered()
    budget = CachedLLMProvider(
        provider, cache_dir=tmp_path / 'cache',
        identity='model', ledger_path=tmp_path / 'budget.sqlite3',
        max_estimated_cost_usd=0.00009,
        input_cost_usd_per_million_tokens=2,
        output_cost_usd_per_million_tokens=1,
    )
    assert budget.complete_json(instructions='task', document_text='A') == {'headings': []}
    with pytest.raises(LLMError, match='cost budget'):
        budget.complete_json(instructions='task', document_text='B')
    assert provider.calls == 1
    assert BookLLMBudgetLedger(
        tmp_path / 'budget.sqlite3'
    ).totals()['estimated_cost_usd'] == pytest.approx(0.00009)
