"""Remote consent: a visible, content-free warning precedes the first book-text upload."""

import json

import httpx
import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider

BOOK_TEXT = "PRIVATE_CHAPTER_SENTENCE about the hero"


def _ok(_request):
    return httpx.Response(200, json={"choices": [{"message": {"content": '{"headings":[]}'}}]})


def test_warning_is_printed_once_before_the_first_remote_upload(capsys):
    seen_warning_before_upload = []

    def handler(request):
        # The warning must already be visible when the request carries text.
        assert BOOK_TEXT in json.loads(request.content)["messages"][1]["content"]
        seen_warning_before_upload.append(
            "uploading PDF-derived book text" in capsys.readouterr().err
        )
        return _ok(request)

    with OpenAICompatibleProvider(
        provider="openai",
        base_url="https://api.example.invalid/v1",
        model="remote-model",
        allow_remote=True,
        transport=httpx.MockTransport(handler),
    ) as provider:
        provider.complete_json(instructions="Classify", document_text=BOOK_TEXT)
        provider.complete_json(instructions="Classify", document_text=BOOK_TEXT)
    assert seen_warning_before_upload == [True, False]
    assert BOOK_TEXT not in capsys.readouterr().err


def test_image_and_whole_book_text_get_separate_scoped_warnings(capsys):
    warnings_before_upload = []
    image = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + b"\x00\x00\x00\x01" * 2
        + b"\x08\x06\x00\x00\x00"
    )

    def handler(_request):
        warnings_before_upload.append(capsys.readouterr().err)
        return _ok(_request)

    with OpenAICompatibleProvider(
        provider="remote-test",
        base_url="https://api.example.invalid/v1",
        model="scope-model",
        allow_remote=True,
        transport=httpx.MockTransport(handler),
    ) as provider:
        provider.complete_json_with_image(
            instructions="Inspect image", document_text="page scope", image_data=image
        )
        provider.complete_json_with_image(
            instructions="Inspect image", document_text="page scope", image_data=image
        )
        provider.complete_json(instructions="Analyze", document_text=BOOK_TEXT)
        provider.complete_json(instructions="Analyze", document_text=BOOK_TEXT)

    assert len(warnings_before_upload) == 4
    image_warning, repeated_image, text_warning, repeated_text = warnings_before_upload
    assert "page image" in image_warning
    assert "up to 12 rendered PDF page images" in image_warning
    assert '"remote-test"' in image_warning and '"scope-model"' in image_warning
    assert repeated_image == ""
    assert "whole book in bounded analysis windows" in text_warning
    assert '"remote-test"' in text_warning and '"scope-model"' in text_warning
    assert BOOK_TEXT not in image_warning + text_warning
    assert repeated_text == ""


def test_loopback_providers_upload_without_a_remote_warning(capsys):
    with OpenAICompatibleProvider(
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model="local",
        allow_remote=False,
        transport=httpx.MockTransport(_ok),
    ) as provider:
        provider.complete_json(instructions="Classify", document_text=BOOK_TEXT)
    assert "uploading PDF-derived book text" not in capsys.readouterr().err


def test_remote_endpoint_without_consent_never_sends(capsys):
    def handler(_request):
        raise AssertionError("no request may be sent without consent")

    with pytest.raises(LLMError, match="allow-remote-content"):
        OpenAICompatibleProvider(
            provider="openai",
            base_url="https://api.example.invalid/v1",
            model="remote-model",
            allow_remote=False,
            transport=httpx.MockTransport(handler),
        )
    assert "uploading" not in capsys.readouterr().err
