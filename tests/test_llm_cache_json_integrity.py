"""Untrusted LLM cache entries must not bypass bounded, finite JSON parsing."""

import io
import json
from pathlib import Path

import pytest

from pdf2audiobook.llm.cache import CachedLLMProvider
from pdf2audiobook.workspace import fingerprint


class _Provider:
    def __init__(self):
        self.calls = 0

    def complete_json(self, *, instructions, document_text):
        self.calls += 1
        return {"headings": [], "recovered": True}


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_cached_provider_values_are_regenerated(tmp_path, number):
    provider = _Provider()
    worker = CachedLLMProvider(provider, cache_dir=tmp_path, identity="local")
    key = fingerprint("llm-json-cache-v1", "local", "schema", "synthetic source")
    path = tmp_path / f"{key}.json"
    path.write_text(
        '{"schema_version":1,"fingerprint":"' + key
        + '","response":{"confidence":' + number + '}}',
        encoding="utf-8",
    )

    result = worker.complete_json(instructions="schema", document_text="synthetic source")
    assert result == {"headings": [], "recovered": True}
    assert worker.hits == 0
    assert worker.misses == 1
    assert provider.calls == 1
    assert json.loads(path.read_text(encoding="utf-8"))["response"] == result


def test_cached_json_read_is_bounded_even_if_file_grows_after_stat(tmp_path, monkeypatch):
    provider = _Provider()
    worker = CachedLLMProvider(provider, cache_dir=tmp_path, identity="local")
    key = fingerprint("llm-json-cache-v1", "local", "schema", "synthetic source")
    path = tmp_path / f"{key}.json"
    path.write_text("{}", encoding="utf-8")

    real_open = Path.open
    observed_reads = []

    class _GrowingStream(io.BytesIO):
        def read(self, size=-1):
            observed_reads.append(size)
            return super().read(size)

    def growing_open(self, mode="r", *args, **kwargs):
        if self == path and mode == "rb":
            return _GrowingStream(b"x" * (2 * 1024 * 1024 + 8))
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", growing_open)
    result = worker.complete_json(instructions="schema", document_text="synthetic source")
    assert result == {"headings": [], "recovered": True}
    assert provider.calls == 1
    assert worker.hits == 0
    assert observed_reads == [2 * 1024 * 1024 + 1]
