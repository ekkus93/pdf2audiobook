"""Kitten 2 receives the configured temperature; Kitten 0.8 never does (spec K2)."""

import json
import os
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.tts import catalog, clone_provider
from pdf2audiobook.tts.clone_provider import WorkerClient


def test_the_worker_passes_the_temperature_for_built_in_and_cloned_voices(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    fake = tmp_path / "fake_sdk"
    fake.mkdir()
    calls = tmp_path / "calls.jsonl"
    (fake / "huggingface_hub.py").write_text("hf_hub_download = None\n")
    (fake / "kittenml.py").write_text(f"""
import json
import numpy as np
class KittenTTS2:
    def __init__(self, *a, **kw): pass
    def _speaker(self, voice, reference, transcript): pass
    def generate(self, text, **kw):
        with open({str(calls)!r}, "a") as stream:
            stream.write(json.dumps({{k: v for k, v in kw.items() if k != "reference"}}) + "\\n")
        return np.ones(2400, dtype=np.float32) * 0.1
""")
    folder = catalog.model_directory() / "model"
    folder.mkdir(parents=True)
    (folder / "config.json").write_text("{}")
    monkeypatch.setenv(
        "PYTHONPATH", str(fake) + os.pathsep + str(Path(__file__).resolve().parents[1] / "src")
    )
    client = WorkerClient()
    try:
        builtin = {"command": "generate_builtin", "voice": "Bruno", "temperature": 0.2}
        cloned = {
            "command": "generate",
            "reference": "/private/ref.wav",
            "transcript": "Spoken words.",
            "temperature": 0.45,
        }
        for n, request in enumerate((builtin, cloned)):
            output = tmp_path / f"chunk-{n}.npy"
            response = client.request({**request, "text": "Book narration.", "output": str(output)})
            assert response == {"ok": True}
    finally:
        client.close()
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    assert [call["temperature"] for call in recorded] == [0.2, 0.45]
    for call in recorded:
        assert call["preset"] == "stable" and call["normalize"] is False
        assert call["advanced"] == {"seed": 0, "use_emotion": False}


class _Client:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def request(self, payload, **_kwargs):
        self.requests.append(payload)
        if "output" in payload:
            np.save(payload["output"], np.full(2400, 0.1, dtype=np.float32), allow_pickle=False)
        return {"ok": True}

    def close(self) -> None:
        pass


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Client:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    worker = _Client()
    monkeypatch.setattr(clone_provider, "WorkerClient", lambda: worker)
    monkeypatch.setattr(clone_provider, "require_model", lambda: None)
    return worker


def test_the_built_in_kitten_2_provider_sends_its_temperature(client: _Client) -> None:
    provider = clone_provider.Kitten2BuiltinProvider(temperature=0.2)
    provider.generate("Book narration.", voice="Bruno", speed=1)
    generated = [r for r in client.requests if r["command"] == "generate_builtin"]
    assert [r["temperature"] for r in generated] == [0.2]


def test_the_clone_provider_sends_its_temperature(client: _Client) -> None:
    reference = types.SimpleNamespace(key="ref", wav=Path("/private/ref.wav"), transcript="Words.")
    provider = clone_provider.KittenCloneProvider(reference, temperature=0.45)  # type: ignore[arg-type]
    provider.generate("Book narration.", voice="ref", speed=1)
    generated = [r for r in client.requests if r["command"] == "generate"]
    assert [r["temperature"] for r in generated] == [0.45]


def test_the_pipeline_gives_kitten_2_the_configured_temperature(monkeypatch) -> None:
    from pdf2audiobook import pipeline

    seen: list[float] = []

    class Builtin:
        def __init__(self, *, temperature: float) -> None:
            seen.append(temperature)

    monkeypatch.setattr(clone_provider, "Kitten2BuiltinProvider", Builtin)
    settings = Settings.model_validate(
        {"tts": {"kitten": {"model": "kitten2", "temperature": 0.2}}}
    )
    pipeline.create_tts_provider(settings)
    assert seen == [0.2]


def test_kitten_0_8_never_receives_a_temperature(monkeypatch) -> None:
    calls: list[dict] = []

    class KittenTTS:
        def __init__(self, model: str) -> None:
            pass

        def generate(self, text: str, **kwargs):
            calls.append(kwargs)
            return np.ones(2400, dtype=np.float32)

    monkeypatch.setitem(sys.modules, "kittenml", types.SimpleNamespace(KittenTTS=KittenTTS))
    from pdf2audiobook.tts import KittenProvider

    KittenProvider("mini").generate("Book narration.", voice="Jasper", speed=1.0)
    assert calls == [{"voice": "Jasper", "speed": 1.0}]
