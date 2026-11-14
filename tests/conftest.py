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


@pytest.fixture(autouse=True)
def _default_event_policy():
    """Start every test from the CLI's default logging policy, as a fresh process would."""
    from pdf2audiobook.logging import configure_logging, use_default_event_policy

    configure_logging()
    use_default_event_policy()


@pytest.fixture
def closing(request):
    """Return a function that registers an object's ``close`` for test teardown.

    Use it around a constructor that owns a resource, for example
    ``worker = closing(CachedLLMProvider(...))``, so the resource is released
    when the test ends instead of being left to the garbage collector.
    """

    def register(resource):
        request.addfinalizer(resource.close)
        return resource

    return register
