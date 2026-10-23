"""Incomplete provider usage must never qualify cost-budget accounting."""

import httpx
import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import create_provider
from pdf2audiobook.llm.cache import CachedLLMProvider


@pytest.mark.parametrize(
    "usage",
    [
        {"total_tokens": 7},
        {"completion_tokens": 2, "total_tokens": 7},
        {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 6},
        {"prompt_tokens": True, "completion_tokens": 2, "total_tokens": 7},
        {"prompt_tokens": 10**400, "completion_tokens": 2, "total_tokens": 7},
    ],
)
def test_incomplete_usage_cannot_authorize_cost_budget(tmp_path, usage):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": usage,
            },
        )

    with create_provider(Settings(), transport=httpx.MockTransport(handler)) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / "cache",
            identity="incomplete-usage-v1",
            enabled=False,
            max_estimated_cost_usd=1.0,
            input_cost_usd_per_million_tokens=1.0,
            output_cost_usd_per_million_tokens=1.0,
        )
        with pytest.raises(LLMError, match="verified usage"):
            worker.complete_json(instructions="test", document_text="synthetic")
        assert worker.usage_verified is False
        assert worker._reported_cost_usd() is None


def test_complete_consistent_usage_can_qualify_cost_budget(tmp_path):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            },
        )

    with create_provider(Settings(), transport=httpx.MockTransport(handler)) as provider:
        worker = CachedLLMProvider(
            provider,
            cache_dir=tmp_path / "cache",
            identity="complete-usage-v1",
            enabled=False,
            max_estimated_cost_usd=1.0,
            input_cost_usd_per_million_tokens=1.0,
            output_cost_usd_per_million_tokens=1.0,
        )
        assert worker.complete_json(instructions="test", document_text="synthetic") == {"ok": True}
        assert worker.usage_verified is True
        assert worker._reported_cost_usd() == pytest.approx(0.000007)
