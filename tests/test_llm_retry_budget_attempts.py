"""Each retry consumes its own persistent request budget reservation."""

import json

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
        max_context_tokens=4096,
    ) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / "cache",
            identity="local-model",
            ledger_path=ledger_path,
            max_requests=1,
            max_reported_tokens=100_000,
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


def test_unknown_attempt_is_charged_at_bound_and_retry_can_succeed(tmp_path):
    sent = []

    def respond(request):
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            return httpx.Response(500, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"headings":[]}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    ledger_path = tmp_path / "reports" / "llm_budget.sqlite3"
    with OpenAICompatibleProvider(
        provider="stub",
        model="local",
        base_url="http://127.0.0.1:11434/v1",
        allow_remote=False,
        transport=httpx.MockTransport(respond),
        max_retries=1,
        max_context_tokens=4096,
        max_output_tokens=100,
    ) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / "cache",
            identity="local",
            ledger_path=ledger_path,
            max_reported_tokens=1000,
        )
        assert worker.complete_json(instructions="task", document_text="source") == {"headings": []}
    rows = BookLLMBudgetLedger(ledger_path).rows()
    assert [row["status"] for row in rows] == ["unknown", "complete"]
    assert rows[0]["total_tokens"] is None
    assert BookLLMBudgetLedger(ledger_path).totals()["reported_tokens"] > 100


def test_rejected_max_tokens_is_zero_cost_and_fallback_stays_capped(tmp_path):
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "max_tokens" in payload:
            return httpx.Response(
                400, json={"error": {"message": "max_tokens unsupported", "param": "max_tokens"}}
            )
        assert "max_completion_tokens" in payload
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"headings":[]}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    ledger_path = tmp_path / "reports" / "llm_budget.sqlite3"
    with OpenAICompatibleProvider(
        provider="stub",
        model="local",
        base_url="http://127.0.0.1:11434/v1",
        allow_remote=False,
        transport=httpx.MockTransport(respond),
        max_context_tokens=4096,
        max_output_tokens=100,
    ) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / "cache",
            identity="local",
            ledger_path=ledger_path,
            max_reported_tokens=1000,
        )
        assert worker.complete_json(instructions="task", document_text="source") == {"headings": []}
    assert len(requests) == 2
    assert [row["status"] for row in BookLLMBudgetLedger(ledger_path).rows()] == [
        "rejected",
        "complete",
    ]


def test_json_mode_rejection_is_rejected_and_capability_persists_between_providers(tmp_path):
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        has_json_mode = "response_format" in payload
        requests.append(has_json_mode)
        if has_json_mode:
            return httpx.Response(
                400,
                json={
                    "error": {"message": "response_format unsupported", "param": "response_format"}
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"headings":[]}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    transport = httpx.MockTransport(respond)
    ledger_path = tmp_path / "reports" / "llm_budget.sqlite3"
    for request_number in range(3):
        with OpenAICompatibleProvider(
            provider="stub",
            model="local",
            base_url="http://127.0.0.1:11434/v1",
            allow_remote=False,
            transport=transport,
            max_context_tokens=4096,
        ) as provider:
            worker = CachedLLMProvider(
                provider,
                cache_dir=tmp_path / "cache",
                identity="stable-provider-model",
                ledger_path=ledger_path,
                max_reported_tokens=100_000,
            )
            assert worker.complete_json(
                instructions="task", document_text=f"source {request_number}"
            ) == {"headings": []}

    assert requests == [True, False, False, False]
    assert [row["status"] for row in BookLLMBudgetLedger(ledger_path).rows()] == [
        "rejected",
        "complete",
        "complete",
        "complete",
    ]


@pytest.mark.parametrize(
    ("status_code", "body", "expected_status"),
    [
        (400, {"error": "invalid request"}, "rejected"),
        (
            400,
            {
                "error": "reported failure",
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
            "complete",
        ),
        (408, {"error": "timeout"}, "unknown"),
    ],
)
def test_http_failure_settlement_uses_usage_when_reported(
    tmp_path, status_code, body, expected_status
):
    ledger_path = tmp_path / f"{status_code}-{expected_status}.sqlite3"
    with OpenAICompatibleProvider(
        provider="stub",
        model="local",
        base_url="http://127.0.0.1:11434/v1",
        allow_remote=False,
        transport=httpx.MockTransport(lambda _request: httpx.Response(status_code, json=body)),
        max_retries=0,
        max_context_tokens=4096,
        max_output_tokens=100,
    ) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / f"cache-{status_code}-{expected_status}",
            identity="local",
            ledger_path=ledger_path,
            max_reported_tokens=1000,
        )
        with pytest.raises(LLMError):
            worker.complete_json(instructions="task", document_text="source")
    row = BookLLMBudgetLedger(ledger_path).rows()[0]
    assert row["status"] == expected_status
    assert row["total_tokens"] == (6 if expected_status == "complete" else None)


def test_context_length_error_mentioning_max_tokens_does_not_remove_or_persist_cap(tmp_path):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Invalid request: input exceeds the model context length; max_tokens is too large",
                    "param": "max_tokens",
                }
            },
        )

    transport = httpx.MockTransport(respond)
    cache_dir = tmp_path / "cache"
    with OpenAICompatibleProvider(
        provider="stub",
        model="local",
        base_url="http://127.0.0.1:11434/v1",
        allow_remote=False,
        transport=transport,
        max_context_tokens=4096,
    ) as provider:
        worker = CachedLLMProvider(provider, cache_dir=cache_dir, identity="local-model")
        with pytest.raises(LLMError):
            worker.complete_json(instructions="task", document_text="book")
        assert provider._unsupported_parameters == set()

    assert len(requests) == 1
    assert requests[0]["max_tokens"] == 1024
    capability_files = list(cache_dir.rglob("*.json"))
    assert not any("provider-capabilities" in path.parts for path in capability_files)
