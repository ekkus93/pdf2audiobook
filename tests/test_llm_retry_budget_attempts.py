"""Each retry consumes its own persistent request budget reservation."""

import httpx
import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider
from pdf2audiobook.llm.budget import BookLLMBudgetLedger
from pdf2audiobook.llm.cache import CachedLLMProvider


def test_request_budget_stops_retry_after_first_sent_timeout(tmp_path):
    sent = []

    def respond(request):
        sent.append(request)
        raise httpx.ReadTimeout("PRIVATE READ FAILURE", request=request)

    ledger_path = tmp_path / "reports" / "llm_budget.sqlite3"
    with OpenAICompatibleProvider(
        provider="stub",
        model="local",
        base_url="http://127.0.0.1:11434/v1",
        allow_remote=False,
        transport=httpx.MockTransport(respond),
        max_retries=4,
    ) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / "cache",
            identity="local-model",
            ledger_path=ledger_path,
            max_requests=1,
            max_reported_tokens=100,
        )
        with pytest.raises(LLMError, match="request budget") as error:
            worker.complete_json(instructions="private prompt", document_text="private book")

    rows = BookLLMBudgetLedger(ledger_path).rows()
    assert len(sent) == 1
    assert len(rows) == 1
    assert rows[0]["status"] == "unknown"
    assert BookLLMBudgetLedger(ledger_path).totals()["requests_started"] == 1
    assert "PRIVATE READ FAILURE" not in str(error.value)
    assert "private book" not in str(error.value)
