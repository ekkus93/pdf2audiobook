"""Offline model-list, health and token-usage provider contracts."""

import json

import httpx

from pdf2audiobook.llm import OpenAICompatibleProvider


def make_provider(handler, model="auto"):
    return OpenAICompatibleProvider(
        provider="ollama", model=model,
        base_url="http://127.0.0.1:11434/v1", allow_remote=False,
        transport=httpx.MockTransport(handler),
    )


def test_model_discovery_health_and_token_telemetry_without_document_leak():
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [
                {"id": "small-model"}, {"id": "larger-model"}, {"id": "small-model"},
            ]})
        payload = json.loads(request.content)
        assert payload["model"] == "small-model"
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][1]["content"] == "Safe fixture"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"headings":[]}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16},
        })

    with make_provider(respond) as provider:
        assert provider.health()
        assert provider.list_models() == ["small-model", "larger-model"]
        assert provider.complete_json(
            instructions="structure task", document_text="Safe fixture"
        ) == {"headings": []}
        assert provider.request_count == 1
        assert provider.last_usage == {"prompt_tokens": 10, "completion_tokens": 6,
                                       "total_tokens": 16}
        assert provider.total_usage["total_tokens"] == 16
        provider.complete_json(instructions="structure", document_text="Safe fixture")
        assert provider.total_usage["total_tokens"] == 32
    assert all("Safe fixture" not in str(request.url) for request in requests)
    assert all("Safe fixture" not in str(request.headers) for request in requests)


def test_unavailable_discovery_reports_unhealthy_and_explicit_model_remains_usable():
    def respond(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(404, text="server echoes private payload")
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"edits":[]}'}}],
        })

    with make_provider(respond, model="fixed-model") as provider:
        assert provider.health() is False
        assert provider.complete_json(instructions="task", document_text="book") == {
            "edits": []
        }
        assert provider.request_count == 1
        assert provider.last_usage == {}


def test_malformed_usage_does_not_poison_totals():
    def respond(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"headings":[]}'}}],
            "usage": {"total_tokens": -5, "prompt_tokens": True, "completion_tokens": "5"},
        })

    with make_provider(respond, model="fixed-model") as provider:
        provider.complete_json(instructions="task", document_text="fixture")
        assert provider.total_usage["total_tokens"] == 0
        assert provider.last_usage == {}
