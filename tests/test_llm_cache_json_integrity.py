"""Untrusted LLM cache entries must not bypass bounded, finite JSON parsing."""

import io
import json
from pathlib import Path

import pytest

from pdf2audiobook.errors import LLMError
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

def test_deeply_nested_cached_response_is_treated_as_a_miss(tmp_path):
    provider = _Provider()
    worker = CachedLLMProvider(provider, cache_dir=tmp_path, identity="local")
    key = fingerprint("llm-json-cache-v1", "local", "schema", "synthetic source")
    path = tmp_path / f"{key}.json"
    nested = "[" * 1600 + "0" + "]" * 1600
    path.write_text(
        '{"schema_version":1,"fingerprint":"' + key
        + '","response":{"nested":' + nested + "}}",
        encoding="utf-8",
    )

    result = worker.complete_json(instructions="schema", document_text="synthetic source")
    assert result == {"headings": [], "recovered": True}
    assert provider.calls == 1
    assert worker.hits == 0
    assert worker.misses == 1
    assert json.loads(path.read_text(encoding="utf-8"))["response"] == result


def test_nesting_limit_checks_object_containers_as_well_as_arrays(tmp_path):
    provider = _Provider()
    worker = CachedLLMProvider(provider, cache_dir=tmp_path, identity="local")
    key = fingerprint("llm-json-cache-v1", "local", "schema", "synthetic source")
    nested = '{"next":' * 80 + "null" + "}" * 80
    (tmp_path / f"{key}.json").write_text(
        '{"schema_version":1,"fingerprint":"' + key
        + '","response":{"nested":' + nested + "}}",
        encoding="utf-8",
    )

    assert worker.complete_json(instructions="schema", document_text="synthetic source") == {
        "headings": [], "recovered": True,
    }
    assert provider.calls == 1
    assert worker.hits == 0


def test_moderately_nested_cached_response_is_reused(tmp_path):
    provider = _Provider()
    worker = CachedLLMProvider(provider, cache_dir=tmp_path, identity="local")
    key = fingerprint("llm-json-cache-v1", "local", "schema", "synthetic source")
    response = {"nested": [{"text": "literal braces { } and [ ]"}]}
    (tmp_path / f"{key}.json").write_text(
        json.dumps({"schema_version": 1, "fingerprint": key, "response": response}),
        encoding="utf-8",
    )

    assert worker.complete_json(instructions="schema", document_text="synthetic source") == response
    assert worker.hits == 1
    assert worker.misses == 0
    assert provider.calls == 0


def test_oversized_live_provider_structure_is_not_cached(tmp_path):
    class _NestedProvider(_Provider):
        def complete_json(self, *, instructions, document_text):
            self.calls += 1
            root = {}
            cursor = root
            for _ in range(80):
                child = {}
                cursor["nested"] = child
                cursor = child
            return root

    provider = _NestedProvider()
    worker = CachedLLMProvider(provider, cache_dir=tmp_path, identity="local")
    with pytest.raises(LLMError, match="supported JSON nesting depth"):
        worker.complete_json(instructions="schema", document_text="synthetic source")
    assert provider.calls == 1
    assert worker.hits == 0
    assert worker.misses == 1
    assert not list(tmp_path.glob("*.json"))


def test_cache_path_probe_error_falls_back_without_disclosing_path(tmp_path, monkeypatch):
    provider = _Provider()
    worker = CachedLLMProvider(provider, cache_dir=tmp_path, identity="local")
    key = fingerprint("llm-json-cache-v1", "local", "schema", "synthetic source")
    path = tmp_path / f"{key}.json"
    original_is_file = Path.is_file

    def failing_is_file(self):
        if self == path:
            raise OSError("PRIVATE_WORKSPACE_PATH")
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", failing_is_file)
    result = worker.complete_json(instructions="schema", document_text="synthetic source")
    assert result == {"headings": [], "recovered": True}
    assert provider.calls == 1
    assert worker.hits == 0
    assert worker.misses == 1

