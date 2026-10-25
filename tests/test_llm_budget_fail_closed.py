"""Budget accounting fails closed: bounds are charged, never assumed free (R70)."""

import json
import sqlite3
import struct
import zlib

import httpx
import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider
from pdf2audiobook.llm.budget import BookLLMBudgetLedger
from pdf2audiobook.llm.cache import CachedLLMProvider

_USAGES = [
    None,
    {},
    {"prompt_tokens": 10, "completion_tokens": 3},
    {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 11},
    {"prompt_tokens": 1 << 70, "completion_tokens": 1, "total_tokens": 1 << 71},
]


@pytest.mark.parametrize("usage", _USAGES)
def test_unknown_attempt_with_recorded_bound_is_charged_at_that_bound(tmp_path, usage):
    ledger = BookLLMBudgetLedger(tmp_path / "budget.sqlite3")
    call_id = ledger.reserve(
        request_hash="one",
        provider_hash="provider",
        max_requests=None,
        max_tokens=100,
        max_usd=None,
        upper_bound_tokens=40,
    )
    ledger.settle(call_id, usage=usage, input_rate=2.0, output_rate=1.0)
    stats = ledger.totals()
    assert stats["unresolved_requests"] == 1
    assert stats["reported_tokens"] == 40
    ledger.reserve(
        request_hash="two",
        provider_hash="provider",
        max_requests=None,
        max_tokens=100,
        max_usd=None,
        upper_bound_tokens=40,
    )
    with pytest.raises(LLMError, match="token budget"):
        ledger.reserve(
            request_hash="three",
            provider_hash="provider",
            max_requests=None,
            max_tokens=100,
            max_usd=None,
            upper_bound_tokens=40,
        )


def test_legacy_open_row_without_a_bound_blocks_a_token_budget(tmp_path):
    path = tmp_path / "budget.sqlite3"
    ledger = BookLLMBudgetLedger(path)
    ledger.totals()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO calls (request_hash, provider_hash, status) VALUES ('old','p','unknown')"
        )
    with pytest.raises(LLMError, match="without a recorded bound.*budget resolve"):
        ledger.reserve(
            request_hash="new",
            provider_hash="p",
            max_requests=None,
            max_tokens=1000,
            max_usd=None,
            upper_bound_tokens=1,
        )
    # Without a token or USD budget the same row does not block.
    ledger.reserve(
        request_hash="new",
        provider_hash="p",
        max_requests=None,
        max_tokens=None,
        max_usd=None,
        upper_bound_tokens=1,
    )


def _provider(respond, **kwargs):
    return OpenAICompatibleProvider(
        provider="stub",
        model="local",
        base_url="http://127.0.0.1:11434/v1",
        allow_remote=False,
        transport=httpx.MockTransport(respond),
        max_context_tokens=4096,
        max_output_tokens=100,
        **kwargs,
    )


def _reject_every_cap(sent):
    def respond(request):
        payload = json.loads(request.content)
        sent.append(payload)
        for parameter in ("max_tokens", "max_completion_tokens"):
            if parameter in payload:
                return httpx.Response(
                    400, json={"error": {"message": f"{parameter} unsupported", "param": parameter}}
                )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    return respond


def test_both_cap_parameters_rejected_is_refused_under_a_budget(tmp_path):
    sent: list[dict] = []
    ledger_path = tmp_path / "reports" / "llm_budget.sqlite3"
    with _provider(_reject_every_cap(sent)) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / "cache",
            identity="local",
            ledger_path=ledger_path,
            max_reported_tokens=100_000,
        )
        with pytest.raises(LLMError, match="output token cap"):
            worker.complete_json(instructions="task", document_text="source")
    assert len(sent) == 2
    assert all("max_tokens" in item or "max_completion_tokens" in item for item in sent)
    assert [row["status"] for row in BookLLMBudgetLedger(ledger_path).rows()] == [
        "rejected",
        "rejected",
    ]


def test_remembered_cap_rejections_never_send_an_uncapped_budgeted_request(tmp_path):
    sent: list[dict] = []
    for _ in range(2):
        with _provider(_reject_every_cap(sent)) as provider:
            worker = CachedLLMProvider(
                provider,
                cache_dir=tmp_path / "cache",
                identity="local",
                ledger_path=tmp_path / "reports" / "llm_budget.sqlite3",
                max_reported_tokens=100_000,
            )
            with pytest.raises(LLMError, match="output token cap"):
                worker.complete_json(instructions="task", document_text="source")
    assert len(sent) == 2
    assert all("max_tokens" in item or "max_completion_tokens" in item for item in sent)


def test_without_a_budget_the_cap_may_be_dropped_as_before(tmp_path):
    sent: list[dict] = []
    with _provider(_reject_every_cap(sent)) as provider:
        assert provider.complete_json(instructions="task", document_text="source") == {"ok": True}
    assert "max_tokens" not in sent[-1] and "max_completion_tokens" not in sent[-1]


def test_429_after_the_last_retry_stays_unknown(tmp_path):
    ledger_path = tmp_path / "reports" / "llm_budget.sqlite3"
    with _provider(
        lambda _request: httpx.Response(429, json={"error": "slow down"}), max_retries=1
    ) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / "cache",
            identity="local",
            ledger_path=ledger_path,
            max_reported_tokens=100_000,
        )
        with pytest.raises(LLMError):
            worker.complete_json(instructions="task", document_text="source")
    rows = BookLLMBudgetLedger(ledger_path).rows()
    assert [row["status"] for row in rows] == ["unknown", "unknown"]
    assert BookLLMBudgetLedger(ledger_path).totals()["reported_tokens"] > 0


def test_provider_usage_above_the_reserved_bound_still_fails_closed(tmp_path):
    class Overreporting:
        max_context_tokens = 4096
        max_output_tokens = 1

        def __init__(self):
            self.calls = 0
            self.last_usage = {}
            self.total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        def complete_json(self, *, instructions, document_text):
            self.calls += 1
            self.last_usage = {"prompt_tokens": 400, "completion_tokens": 100, "total_tokens": 500}
            for key, value in self.last_usage.items():
                self.total_usage[key] += value
            return {"ok": True}

    for persistent in (False, True):
        provider = Overreporting()
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / f"cache-{persistent}",
            identity="synthetic",
            ledger_path=tmp_path / "ledger.sqlite" if persistent else None,
            max_reported_tokens=300,
        )
        with pytest.raises(LLMError, match="token budget"):
            worker.complete_json(instructions="x", document_text="first")
        assert provider.calls == 1
        with pytest.raises(LLMError, match="token budget"):
            worker.complete_json(instructions="x", document_text="second")
        assert provider.calls == 1


def _png(width, height):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = zlib.compress(bytes((width + 1) * height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def test_image_bound_comes_from_pixels_not_compressed_bytes(tmp_path):
    image = _png(2000, 2000)
    assert len(image) < 20_000
    ledger_path = tmp_path / "reports" / "llm_budget.sqlite3"

    def respond(request):
        raise httpx.ReadTimeout("slow", request=request)

    with OpenAICompatibleProvider(
        provider="stub",
        model="local",
        base_url="http://127.0.0.1:11434/v1",
        allow_remote=False,
        transport=httpx.MockTransport(respond),
        max_retries=0,
        max_context_tokens=100_000,
        max_output_tokens=100,
    ) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / "cache",
            identity="local",
            ledger_path=ledger_path,
            max_reported_tokens=1_000_000,
        )
        with pytest.raises(LLMError):
            worker.complete_json_with_image(
                instructions="task", document_text="source", image_data=image
            )
    with sqlite3.connect(ledger_path) as connection:
        (bound,) = connection.execute("SELECT upper_bound_tokens FROM calls").fetchone()
    assert bound >= ((2000 * 2000 + 1023) // 1024) * 4 + 256
