"""Offline acceptance coverage added by the voice-cloning review."""

import json
from pathlib import Path

import numpy as np
import pytest
from test_voice_cloning import settings_for_reference

from pdf2audiobook.audio import read_synthesis_progress, synthesize_chunks
from pdf2audiobook.config import load_settings
from pdf2audiobook.errors import AudioError
from pdf2audiobook.tts import clone_provider
from pdf2audiobook.tts.cloning import snapshot_reference
from pdf2audiobook.tts.selection import settings_for_book_tts


@pytest.fixture(autouse=True)
def isolated_clone_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


@pytest.mark.parametrize(
    ("global_value", "env_value", "profile_value", "cli_value", "expected"),
    [
        (False, None, None, None, False),
        (True, None, None, None, True),
        (False, True, None, None, True),
        (True, False, None, None, False),
        (False, True, False, None, False),
        (True, False, True, None, True),
        (False, False, False, True, True),
        (True, True, True, False, False),
        (False, None, True, False, False),
        (True, None, False, True, True),
    ],
)
def test_clone_enable_precedence_matrix(
    tmp_path, global_value, env_value, profile_value, cli_value, expected
):
    config = tmp_path / "config.toml"
    text = "[tts.voice_clone]\nenabled=" + str(global_value).lower() + "\n"
    if profile_value is not None:
        text += "[tts.profiles.Book]\nclone_voice=" + str(profile_value).lower() + "\n"
    config.write_text(text)
    env = {} if env_value is None else {"PDF2AUDIOBOOK_CLONE_VOICE": str(env_value).lower()}
    overrides = {} if cli_value is None else {"tts": {"voice_clone": {"enabled": cli_value}}}
    settings, _ = load_settings(config, environ=env, overrides=overrides)
    assert settings_for_book_tts(settings, "Book").tts.voice_clone.enabled is expected


@pytest.mark.parametrize("data", [b"", b"RIFFmalformed PRIVATE_AUDIO"])
def test_empty_and_malformed_reference_media_fail_privately(tmp_path, data):
    settings = settings_for_reference(tmp_path)
    Path(settings.tts.voice_clone.reference_audio).write_bytes(data)
    with pytest.raises(AudioError) as error:
        snapshot_reference(settings)
    assert error.value.error_reason == "voice_reference_invalid"
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("kind", ["nan", "stereo", "empty", "float64", "oversized", "missing"])
def test_clone_worker_audio_contract_rejects_invalid_output(tmp_path, kind):
    path = tmp_path / "PRIVATE_AUDIO.npy"
    if kind == "oversized":
        with path.open("wb") as stream:
            stream.truncate(24000 * 120 * 4 + 1025)
    elif kind != "missing":
        audio = {
            "nan": np.array([np.nan], dtype=np.float32),
            "stereo": np.ones((2, 8), dtype=np.float32),
            "empty": np.array([], dtype=np.float32),
            "float64": np.ones(8, dtype=np.float64),
        }[kind]
        np.save(path, audio, allow_pickle=False)
    with pytest.raises(AudioError) as error:
        clone_provider._read_worker_audio(path)
    assert "PRIVATE" not in str(error.value)


@pytest.fixture
def reference_provider(tmp_path, monkeypatch):
    settings = settings_for_reference(tmp_path)
    reference = snapshot_reference(settings)
    requests = []

    class Client:
        def request(self, payload, **kwargs):
            requests.append(payload)
            if "output" in payload:
                np.save(payload["output"], np.full(2400, 0.1, dtype=np.float32), allow_pickle=False)
            return {"ok": True}

        def close(self):
            pass

    monkeypatch.setattr(clone_provider, "WorkerClient", Client)
    monkeypatch.setattr(clone_provider, "require_model", lambda: None)
    provider = clone_provider.KittenCloneProvider(reference, temperature=0.3)
    try:
        yield settings, reference, provider, requests
    finally:
        provider.close()
        reference.close()


def test_clone_uses_narration_transforms_pauses_and_source_progress(tmp_path, reference_provider):
    settings, reference, provider, requests = reference_provider
    text = "Hermione arrived [13].\n\nThe keeper returned."
    progress = tmp_path / "progress.json"
    result = synthesize_chunks(
        text,
        provider,
        model="kitten2",
        voice=reference.key,
        speed=1,
        pause_ms=50,
        cache=tmp_path / "chunks",
        progress_file=progress,
        pronunciations={"hermione": "Her-my-oh-nee"},
        skip_citations=True,
    )
    spoken = [r["text"] for r in requests if r["command"] == "generate"]
    assert spoken == ["Her-my-oh-nee arrived.", "The keeper returned."]
    assert all(r.get("transcript") == reference.transcript for r in requests)
    assert not any(reference.transcript in value for value in spoken)
    assert sum(r["command"] == "prepare" for r in requests) == 1
    assert result.ndim == 1 and np.isfinite(result).all()
    assert np.count_nonzero(result == 0) >= 2400  # Existing paragraph pause at 24 kHz.
    saved = read_synthesis_progress(progress)
    assert saved["status"] == "completed" and saved["completed_chunks"] == 2
    assert all(
        0 <= item["source_start"] <= item["source_end"] <= len(text) for item in saved["mapping"]
    )
    assert saved["mapping"][0]["source_start"] == 0
    assert saved["mapping"][-1]["source_end"] == len(text)
    assert reference.transcript not in progress.read_text()
    assert str(reference.wav) not in progress.read_text()


@pytest.mark.parametrize(
    "change",
    [
        {"reference_audio_sha256": "0" * 64},
        {"reference_text_sha256": "1" * 64},
        {"transcription": {"model": "local", "package": "test"}},
        {"backend_versions": {"torch": "9.9"}},
        {"manifest_sha256": "2" * 64},
        {"seed": 1},
        {"speed_processing": "test-v2"},
    ],
)
def test_clone_identity_changes_reach_chunk_cache_and_progress(
    tmp_path, reference_provider, change
):
    settings, reference, provider, requests = reference_provider
    import test_citation_identity as legacy

    from pdf2audiobook.conversion import _rendering_inputs
    from pdf2audiobook.pipeline import chapter_audio_fingerprint

    manifest = legacy._manifest()
    settings._clone_reference = reference
    before_chapter = chapter_audio_fingerprint(
        "The keeper returned.", settings, manifest, manifest.chapters[0]
    )
    opts = {
        "model": "kitten2",
        "speed": 1,
        "pause_ms": 0,
        "cache": tmp_path / "chunks",
        "progress_file": tmp_path / "progress.json",
    }
    synthesize_chunks("The keeper returned.", provider, voice=reference.key, **opts)
    before = read_synthesis_progress(opts["progress_file"])
    calls = len(requests)
    synthesize_chunks("The keeper returned.", provider, voice=reference.key, **opts)
    assert len(requests) == calls
    reference.identity = {**reference.identity, **change}
    synthesize_chunks("The keeper returned.", provider, voice=reference.key, **opts)
    after = read_synthesis_progress(opts["progress_file"])
    assert len(requests) > calls
    assert before["fingerprint"] != after["fingerprint"]
    assert (
        chapter_audio_fingerprint("The keeper returned.", settings, manifest, manifest.chapters[0])
        != before_chapter
    )
    assert _rendering_inputs(settings)["voice_clone"] == reference.identity
    assert before["chunks"][0]["cache_key"] != after["chunks"][0]["cache_key"]
    public = json.dumps(after)
    assert reference.transcript not in public and str(reference.wav) not in public


def test_inactive_reference_options_preserve_legacy_chapter_and_rendering_identity(monkeypatch):
    import test_citation_identity as legacy

    from pdf2audiobook import pipeline
    from pdf2audiobook.config import Settings
    from pdf2audiobook.conversion import _rendering_inputs

    monkeypatch.setattr(pipeline, "_tts_model_identity", lambda settings: "pinned-model-identity")
    baseline = Settings()
    inactive = Settings()
    baseline.reading.process_citations = False
    inactive.reading.process_citations = False
    inactive.tts.voice_clone.reference_audio = "/PRIVATE/missing.wav"
    inactive.tts.voice_clone.reference_text_file = "/PRIVATE/missing.txt"
    assert legacy._fingerprint(inactive) == legacy.GOLDEN_OFF
    assert _rendering_inputs(inactive) == _rendering_inputs(baseline)
    assert "voice_clone" not in _rendering_inputs(inactive)
