"""Offline regression tests for budget accounting on failed model responses."""

import httpx
import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider
from pdf2audiobook.llm.budget import BookLLMBudgetLedger
from pdf2audiobook.llm.cache import CachedLLMProvider


def test_invalid_json_response_still_charges_book_token_ledger(tmp_path):
    def respond(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "invalid-json"}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    with OpenAICompatibleProvider(
        provider="ollama",
        model="local",
        base_url="http://127.0.0.1:11434/v1",
        allow_remote=False,
        transport=httpx.MockTransport(respond),
        max_retries=0,
        max_context_tokens=4096,
    ) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / "cache",
            identity="model",
            ledger_path=tmp_path / "ledger.sqlite3",
            max_reported_tokens=2000,
        )
        with pytest.raises(LLMError):
            worker.complete_json(instructions="task", document_text="fixture")
    totals = BookLLMBudgetLedger(tmp_path / "ledger.sqlite3").totals()
    assert totals["reported_tokens"] == 30
    assert totals["unresolved_requests"] == 0
