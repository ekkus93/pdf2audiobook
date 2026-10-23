"""Untrusted provider usage must not overflow signed accounting counters."""

import httpx

from pdf2audiobook.config import Settings
from pdf2audiobook.llm import create_provider


def response(usage):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"ok":true}'}}],
            "usage": usage,
        },
    )


def test_oversized_usage_does_not_poison_valid_fields_or_followup():
    responses = iter(
        [
            response(
                {
                    "prompt_tokens": 10**400,
                    "completion_tokens": 3,
                    "total_tokens": 10**400,
                }
            ),
            response(
                {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "total_tokens": 7,
                }
            ),
        ]
    )

    def handler(request):
        return next(responses)

    with create_provider(Settings(), transport=httpx.MockTransport(handler)) as provider:
        assert provider.complete_json(instructions="test", document_text="synthetic") == {
            "ok": True
        }
        assert provider.last_usage == {"completion_tokens": 3}
        assert provider.total_usage == {
            "prompt_tokens": 0,
            "completion_tokens": 3,
            "total_tokens": 0,
        }
        assert provider.complete_json(instructions="test", document_text="synthetic") == {
            "ok": True
        }
        assert provider.last_usage == {
            "prompt_tokens": 5,
            "completion_tokens": 2,
            "total_tokens": 7,
        }
        assert provider.total_usage == {
            "prompt_tokens": 5,
            "completion_tokens": 5,
            "total_tokens": 7,
        }


def test_aggregate_usage_overflow_does_not_wrap_or_overwrite():
    max_signed = 2**63 - 1
    responses = iter(
        [
            response({"prompt_tokens": max_signed, "completion_tokens": 0, "total_tokens": 0}),
            response({"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 2}),
        ]
    )

    with create_provider(
        Settings(), transport=httpx.MockTransport(lambda request: next(responses))
    ) as provider:
        provider.complete_json(instructions="test", document_text="synthetic")
        assert provider.total_usage["prompt_tokens"] == max_signed
        provider.complete_json(instructions="test", document_text="synthetic")
        assert "prompt_tokens" not in provider.last_usage
        assert provider.last_usage["completion_tokens"] == 2
        assert provider.total_usage["prompt_tokens"] == max_signed


def test_boolean_negative_and_noninteger_usage_stays_unknown():
    usage = {
        "prompt_tokens": True,
        "completion_tokens": -3,
        "total_tokens": "12",
    }
    with create_provider(
        Settings(), transport=httpx.MockTransport(lambda request: response(usage))
    ) as provider:
        provider.complete_json(instructions="test", document_text="synthetic")
        assert provider.last_usage == {}
        assert provider.total_usage == {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
