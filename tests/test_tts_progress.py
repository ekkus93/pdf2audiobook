"""Atomic TTS chunk progress ledgers and interruption recovery."""

import io
import json

import numpy as np
import pytest

from pdf2audiobook.audio import progress as progress_module
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


# --- Progress reader rejections (test coverage spec T4) ------------------------


_HEADER = {
    "event": "header",
    "schema_version": 1,
    "fingerprint": "f",
    "total_chunks": 1,
    "pause_count": 0,
    "completed_chunks": 0,
    "status": "in_progress",
}
_CHUNK = {
    "event": "chunk",
    "chunk": {"number": 1, "status": "pending"},
    "mapping": {"number": 1, "source_start": 0, "source_end": 5},
}
_UPDATE = {"event": "chunk_update", "number": 1, "status": "completed", "completed_chunks": 1}
_STATUS = {"event": "status", "status": "completed"}


def _lines(*records):
    return b"".join(
        record if isinstance(record, bytes) else json.dumps(record).encode() + b"\n"
        for record in records
    )


def _unavailable_warnings(caplog):
    return [
        record
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("event") == "progress_unavailable"
    ]


def test_valid_progress_records_are_reconstructed(tmp_path, caplog):
    """Control case for the rejection table below."""
    path = tmp_path / "progress.jsonl"
    path.write_bytes(_lines(_HEADER, _CHUNK, {**_UPDATE, "sha256": "a" * 64, "bytes": 3}, _STATUS))

    with caplog.at_level("WARNING", logger="pdf2audiobook"):
        progress = read_synthesis_progress(path)

    assert progress["status"] == "completed"
    assert progress["completed_chunks"] == 1
    assert progress["chunks"] == [
        {"number": 1, "status": "completed", "sha256": "a" * 64, "bytes": 3}
    ]
    assert _unavailable_warnings(caplog) == []


_REJECTED = {
    "no-trailing-newline": _lines(_HEADER)[:-1],
    "record-too-long": _lines(_HEADER) + b"x" * (16 * 1024 + 10) + b"\n",
    "non-object-record": _lines(_HEADER, [1, 2]),
    "over-depth-record": _lines(
        _HEADER, {"event": "mapping", "mapping": json.loads('{"a":' * 9 + "1" + "}" * 9)}
    ),
    "duplicate-header": _lines(_HEADER, _HEADER),
    "chunk-not-an-object": _lines(_HEADER, {**_CHUNK, "chunk": [1]}),
    "chunk-without-mapping": _lines(_HEADER, {**_CHUNK, "mapping": None}),
    # dict() would accept key-value pairs; only the type check refuses them.
    "chunk-mapping-as-pairs": _lines(_HEADER, {**_CHUNK, "mapping": [["number", 1]]}),
    "chunk-number-not-an-integer": _lines(_HEADER, {**_CHUNK, "chunk": {"number": "1"}}),
    "duplicate-chunk-number": _lines(_HEADER, _CHUNK, _CHUNK),
    "mapping-not-an-object": _lines(_HEADER, {"event": "mapping", "mapping": "pause"}),
    "update-for-unknown-chunk": _lines(_HEADER, {**_UPDATE, "number": 2}),
    "update-number-not-an-integer": _lines(_HEADER, _CHUNK, {**_UPDATE, "number": "1"}),
    "invalid-update-status": _lines(_HEADER, _CHUNK, {**_UPDATE, "status": "done"}),
    "completed-count-before-header": _lines(_CHUNK, _UPDATE, _HEADER),
    "status-before-header": _lines(_STATUS, _HEADER),
    "invalid-status": _lines(_HEADER, {**_STATUS, "status": "paused"}),
    "unknown-event": _lines(_HEADER, {"event": "rewind"}),
    "malformed-json": _lines(_HEADER, b"{not json\n"),
    "invalid-utf8": _lines(_HEADER, b'{"event": "\xff"}\n'),
    "no-header": _lines(_CHUNK),
    "empty-file": b"",
}


@pytest.mark.parametrize("payload", list(_REJECTED.values()), ids=list(_REJECTED))
def test_malformed_progress_is_unavailable_with_one_warning(tmp_path, caplog, payload):
    """T4.a: every rejection returns None and logs progress_unavailable once."""
    path = tmp_path / "progress.jsonl"
    path.write_bytes(payload)

    with caplog.at_level("WARNING", logger="pdf2audiobook"):
        assert read_synthesis_progress(path) is None

    assert len(_unavailable_warnings(caplog)) == 1


@pytest.mark.parametrize(
    ("limit", "value"),
    [("_MAX_PROGRESS_RECORDS", 2), ("_MAX_PROGRESS_FILE_BYTES", 200)],
    ids=["too-many-records", "file-too-large"],
)
def test_progress_beyond_its_bounds_is_unavailable(tmp_path, caplog, monkeypatch, limit, value):
    """T4.a: the record-count and file-size bounds also reject the file."""
    monkeypatch.setattr(progress_module, limit, value)
    path = tmp_path / "progress.jsonl"
    path.write_bytes(_lines(_HEADER, _CHUNK, _UPDATE, _STATUS))

    with caplog.at_level("WARNING", logger="pdf2audiobook"):
        assert read_synthesis_progress(path) is None

    assert len(_unavailable_warnings(caplog)) == 1


def test_unreadable_progress_is_unavailable(tmp_path, caplog):
    """T4.a: a path that can't be read as a file is unavailable, not an error."""
    with caplog.at_level("WARNING", logger="pdf2audiobook"):
        assert read_synthesis_progress(tmp_path) is None

    assert len(_unavailable_warnings(caplog)) == 1


def test_oversized_progress_record_is_never_written():
    """T4.b: the writer refuses a record over the size limit and writes nothing."""
    stream = io.BytesIO()

    with pytest.raises(AudioError, match="^TTS progress record exceeds safe size limit$"):
        progress_module._write_progress_record(stream, {"event": "x" * (16 * 1024)})

    assert stream.getvalue() == b""


def test_progress_that_cannot_be_created_fails_with_a_fixed_message(tmp_path):
    """T4.b: a progress path under a regular file can't be opened; no path leaks."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_bytes(b"")
    target = blocker / "progress.jsonl"

    with pytest.raises(AudioError, match="^Could not write TTS progress$") as error:
        progress_module._start_progress_stream(
            target,
            {
                "schema_version": 1,
                "fingerprint": "f",
                "total_chunks": 0,
                "pause_count": 0,
                "completed_chunks": 0,
                "status": "in_progress",
                "chunks": [],
                "mapping": [],
            },
        )

    assert str(tmp_path) not in str(error.value)
