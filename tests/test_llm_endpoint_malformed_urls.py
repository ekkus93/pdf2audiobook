"""Invalid direct LLM endpoints fail with stable privacy-safe domain errors."""

import pytest

from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import validate_endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        None,
        "",
        "   ",
        "http://[invalid-ipv6",
        "http://[::1",
        "http://localhost:abc/v1",
        "http://127.0.0.1:-1/v1",
        "http://127.0.0.1:65536/v1",
        "http://localhost:0/v1",
        "https://example.org:65536/v1",
    ],
)
def test_malformed_endpoints_are_rejected_without_parser_exceptions(endpoint):
    with pytest.raises(LLMError, match="Invalid LLM endpoint URL or port") as raised:
        validate_endpoint(endpoint, allow_remote=True)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ or endpoint in (None, "", "   ", "http://localhost:0/v1")


@pytest.mark.parametrize(
    ("endpoint", "remote"),
    [
        ("http://localhost:11434/v1", False),
        ("http://127.0.0.1:11434/v1", False),
        ("http://[::1]:8080/v1", False),
        ("https://example.org:443/v1", True),
    ],
)
def test_valid_endpoint_ports_keep_existing_consent_rules(endpoint, remote):
    assert validate_endpoint(endpoint, allow_remote=remote) == endpoint


def test_remote_https_still_requires_explicit_consent():
    with pytest.raises(LLMError, match="allow-remote-content"):
        validate_endpoint("https://example.org:443/v1", allow_remote=False)
