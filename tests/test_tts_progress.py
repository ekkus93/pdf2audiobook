"""Atomic TTS chunk progress ledgers and interruption recovery."""
import json

import numpy as np
import pytest

from pdf2audiobook.audio import split_sentences, synthesize_chunks
from pdf2audiobook.workspace import digest_file

TEXT = ("Alpha " * 40).strip() + ". " + ("Bravo " * 40).strip() + "."


class Provider:
    sample_rate = 24000

    def __init__(self, fail_at=None):
        self.calls = 0
        self.fail_at = fail_at

    def generate(self, text, *, voice, speed):
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError("synthetic interruption")
        return np.full(2400, 0.02, dtype=np.float32)


def options(tmp_path):
    return {
        "model": "mini", "voice": "Jasper", "speed": 1.0,
        "pause_ms": 50, "cache": tmp_path / "wav",
        "progress_file": tmp_path / "progress" / "chapter.json",
    }


def read_progress(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_interrupted_ledger_persists_and_resume_verifies_cache(tmp_path):
    assert len(split_sentences(TEXT)) == 2
    opts = options(tmp_path)
    provider = Provider(fail_at=2)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        synthesize_chunks(TEXT, provider, **opts)
    saved = read_progress(opts["progress_file"])
    assert saved["schema_version"] == 1
    assert saved["total_chunks"] == 2
    assert saved["completed_chunks"] == 1
    assert saved["status"] == "failed"
    assert [item["status"] for item in saved["chunks"]] == ["completed", "failed"]
    assert TEXT not in opts["progress_file"].read_text(encoding="utf-8")

    restarted = Provider()
    synthesize_chunks(TEXT, restarted, **opts)
    assert restarted.calls == 1  # Validated first WAV was not re-synthesized.
    done = read_progress(opts["progress_file"])
    assert done["status"] == "completed"
    assert done["completed_chunks"] == 2
    assert all(item["status"] == "completed" for item in done["chunks"])
    for item in done["chunks"]:
        wav = opts["cache"] / (item["cache_key"] + ".wav")
        assert wav.stat().st_size == item["bytes"]
        assert digest_file(wav) == item["sha256"]
    assert not list(opts["progress_file"].parent.glob(".tmp-*"))


def test_corrupt_audio_regenerates_despite_completed_ledger(tmp_path):
    opts = options(tmp_path)
    first = Provider()
    synthesize_chunks(TEXT, first, **opts)
    assert first.calls == 2
    state = read_progress(opts["progress_file"])
    bad = opts["cache"] / (state["chunks"][0]["cache_key"] + ".wav")
    bad.write_bytes(b"corrupt")
    resumed = Provider()
    synthesize_chunks(TEXT, resumed, **opts)
    assert resumed.calls == 1
    refreshed = read_progress(opts["progress_file"])
    assert refreshed["status"] == "completed"
    assert digest_file(bad) == refreshed["chunks"][0]["sha256"]


def test_progress_fingerprint_invalidation_and_no_resume(tmp_path):
    opts = options(tmp_path)
    provider = Provider()
    synthesize_chunks(TEXT, provider, **opts)
    old_fingerprint = read_progress(opts["progress_file"])["fingerprint"]
    synthesize_chunks(TEXT, provider, **opts)
    assert provider.calls == 2
    synthesize_chunks(TEXT, provider, **dict(opts, voice="Different"))
    assert provider.calls == 4
    assert read_progress(opts["progress_file"])["fingerprint"] != old_fingerprint
    synthesize_chunks(TEXT, provider, **dict(opts, use_cache=False))
    assert provider.calls == 6
