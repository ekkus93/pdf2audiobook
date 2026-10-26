"""Atomic TTS chunk progress ledgers and interruption recovery."""

import numpy as np
import pytest

from pdf2audiobook.audio import read_synthesis_progress, split_sentences, synthesize_chunks
from pdf2audiobook.errors import AudioError
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
        "model": "mini",
        "voice": "Jasper",
        "speed": 1.0,
        "pause_ms": 50,
        "cache": tmp_path / "wav",
        "progress_file": tmp_path / "progress" / "chapter.json",
        "max_retries": 0,
    }


def read_progress(path):
    return read_synthesis_progress(path)


def test_interrupted_ledger_persists_and_resume_verifies_cache(tmp_path):
    assert len(split_sentences(TEXT)) == 2
    opts = options(tmp_path)
    provider = Provider(fail_at=2)
    with pytest.raises(AudioError, match="TTS synthesis failed"):
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


def test_half_million_character_chapter_keeps_pause_count_with_linear_progress(tmp_path):
    import time

    class NoOpProvider:
        sample_rate = 24000
        max_chars_per_chunk = 1000

        def generate(self, _text, *, voice, speed):
            return np.zeros(1, dtype=np.float32)

    source = "word " * 100_000 + "\n\n# # #"
    assert len(source) >= 500_000
    progress_file = tmp_path / "progress" / "large.jsonl"
    started = time.monotonic()
    synthesize_chunks(
        source,
        NoOpProvider(),
        model="noop",
        voice="voice",
        speed=1,
        pause_ms=0,
        cache=tmp_path / "cache",
        use_cache=False,
        progress_file=progress_file,
    )
    elapsed = time.monotonic() - started

    progress = read_progress(progress_file)
    assert progress["pause_count"] == 1
    assert progress["completed_chunks"] == progress["total_chunks"]
    assert progress["status"] == "completed"
    assert elapsed < 15


def test_oversized_progress_record_warns_and_is_unavailable(tmp_path, caplog):
    from pdf2audiobook.audio import _MAX_PROGRESS_RECORD_BYTES

    path = tmp_path / "oversized.jsonl"
    path.write_bytes(b"x" * (_MAX_PROGRESS_RECORD_BYTES + 100) + b"\n")
    with caplog.at_level("WARNING", logger="pdf2audiobook"):
        assert read_progress(path) is None
    assert any(
        isinstance(record.msg, dict) and record.msg.get("event") == "progress_unavailable"
        for record in caplog.records
    )
