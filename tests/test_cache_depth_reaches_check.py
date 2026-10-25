"""Depth tests use otherwise-valid payloads, so only the depth check can reject them (R63)."""

import json

import numpy as np

from pdf2audiobook.audio import synthesize_chunks
from pdf2audiobook.pipeline import valid_mp3_sidecar
from pdf2audiobook.workspace import digest_bytes


class Voice:
    sample_rate = 24000

    def __init__(self):
        self.calls = 0

    def generate(self, text, *, voice, speed):
        self.calls += 1
        return np.full(100, 0.125, dtype=np.float32)


def _synthesize(tmp_path, provider):
    return synthesize_chunks(
        "A short, synthetic spoken sentence.",
        provider,
        model="synthetic",
        voice="Test",
        speed=1.0,
        pause_ms=0,
        cache=tmp_path,
    )


def _disable_depth_checks(monkeypatch):
    monkeypatch.setattr("pdf2audiobook.jsonio._within_depth", lambda *_a, **_k: True)
    monkeypatch.setattr("pdf2audiobook.jsonio.json_within_depth", lambda *_a, **_k: True)


def test_wav_metadata_nesting_is_the_only_reason_the_entry_is_a_miss(tmp_path, monkeypatch):
    voice = Voice()
    _synthesize(tmp_path, voice)
    path = next(tmp_path.glob("*.meta.json"))
    metadata = json.loads(path.read_text())
    metadata["extra"] = [[[[[0]]]]]
    path.write_text(json.dumps(metadata))
    assert path.stat().st_size < 1024

    with monkeypatch.context() as unchecked:
        _disable_depth_checks(unchecked)
        _synthesize(tmp_path, voice)
    assert voice.calls == 1, "without the depth check this payload is a valid cache hit"

    _synthesize(tmp_path, voice)
    assert voice.calls == 2


def _owned_audio(tmp_path, **extra):
    audio = tmp_path / "001 - One.mp3"
    audio.write_bytes(b"synthetic mp3 bytes")
    sidecar = {
        "chapter_id": "c1",
        "sidecar_version": 2,
        "text_sha256": "0" * 64,
        "fingerprint": "f",
        "bytes": audio.stat().st_size,
        "sha256": digest_bytes(audio.read_bytes()),
        **extra,
    }
    audio.with_suffix(".cache.json").write_text(json.dumps(sidecar))
    assert audio.with_suffix(".cache.json").stat().st_size < 4096
    return audio


def test_mp3_sidecar_without_nesting_is_accepted(tmp_path):
    assert valid_mp3_sidecar(_owned_audio(tmp_path)) is not None


def test_mp3_sidecar_nesting_is_the_only_reason_it_is_rejected(tmp_path, monkeypatch):
    audio = _owned_audio(tmp_path, extra=[[[[[[[[[0]]]]]]]]])
    with monkeypatch.context() as unchecked:
        _disable_depth_checks(unchecked)
        assert valid_mp3_sidecar(audio) is not None
    assert valid_mp3_sidecar(audio) is None
