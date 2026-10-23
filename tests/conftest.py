"""Shared test configuration."""

import pytest

from pdf2audiobook.llm import OpenAICompatibleProvider


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "ollama_context: exercise real Ollama served-context discovery"
    )


@pytest.fixture(autouse=True)
def _served_ollama_context(request, monkeypatch):
    """Mock transports emulate only /v1; stub Ollama's /api context lookup."""
    if request.node.get_closest_marker("ollama_context") is None:
        monkeypatch.setattr(
            OpenAICompatibleProvider, "_ollama_served_context", lambda self, model: 1 << 20
        )
