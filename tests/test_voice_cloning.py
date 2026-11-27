"""Offline voice selection, immutable references, artifact setup and worker safety."""

import hashlib
import io
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from pdf2audiobook.config import Settings, load_settings, settings_public
from pdf2audiobook.errors import AudioError, ConfigError
from pdf2audiobook.tts import catalog
from pdf2audiobook.tts.clone_provider import change_speed
from pdf2audiobook.tts.cloning import (
    _snapshot_bytes,
    snapshot_reference,
    validate_clone_selection,
)
from pdf2audiobook.tts.private import PrivateDirectory, cleanup_private_jobs, private_root
from pdf2audiobook.tts.selection import settings_for_book_tts
from pdf2audiobook.tts.worker_client import WorkerClient


@pytest.fixture(autouse=True)
def private_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def recording(
    path: Path, *, seconds: float = 6, frequency: float = 440, silent: bool = False
) -> Path:
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    samples = np.sin(np.arange(int(24000 * seconds)) * 2 * np.pi * frequency / 24000)
    samples = np.zeros_like(samples) if silent else samples * 0.2
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24000)
        stream.writeframes((samples * 32767).astype("<i2").tobytes())
    return path


def settings_for_reference(tmp_path: Path) -> Settings:
    audio = recording(tmp_path / "PRIVATE_VOICE.wav")
    text = tmp_path / "PRIVATE_TRANSCRIPT.txt"
    text.write_text("A synthetic reference, not book text.\r\n", encoding="utf-8")
    return Settings.model_validate(
        {
            "tts": {
                "kitten": {"model": "kitten2"},
                "voice_clone": {
                    "enabled": True,
                    "reference_audio": str(audio),
                    "reference_text_file": str(text),
                },
            }
        }
    )


def test_defaults_are_disabled_and_references_are_redacted() -> None:
    settings = Settings()
    assert not settings.tts.voice_clone.enabled
    settings.tts.voice_clone.reference_audio = "PRIVATE_VOICE"
    settings.tts.voice_clone.reference_text_file = "PRIVATE_TEXT"
    settings.tts.profiles["Book"] = __import__(
        "pdf2audiobook.config", fromlist=["TTSProfile"]
    ).TTSProfile(reference_audio="PRIVATE_PROFILE")
    public = str(settings_public(settings))
    assert "PRIVATE" not in public
    assert "***" in public


def test_environment_and_cli_replace_paired_reference_inputs(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[tts.voice_clone]\nreference_audio="old.wav"\nreference_text_file="old.txt"\n'
    )
    settings, sources = load_settings(config, environ={"PDF2AUDIOBOOK_REFERENCE_AUDIO": "new.wav"})
    assert settings.tts.voice_clone.reference_audio == "new.wav"
    assert settings.tts.voice_clone.reference_text_file is None
    assert sources["tts.voice_clone.reference_text_file"] == "env:PDF2AUDIOBOOK_REFERENCE_AUDIO"
    settings, _ = load_settings(
        config, environ={}, overrides={"tts": {"voice_clone": {"reference_audio": "cli.wav"}}}
    )
    assert settings.tts.voice_clone.reference_text_file is None
    assert "reference_audio" in settings._clone_explicit


def test_profiles_follow_existing_precedence_and_explicit_disable(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {
            "tts": {
                "voice_clone": {
                    "enabled": True,
                    "reference_audio": "global.wav",
                    "reference_text_file": "global.txt",
                },
                "profiles": {"Book": {"clone_voice": True, "reference_audio": "profile.wav"}},
            }
        }
    )
    selected = settings_for_book_tts(settings, "Book")
    assert selected.tts.voice_clone.reference_audio == "profile.wav"
    assert selected.tts.voice_clone.reference_text_file is None
    assert settings.tts.voice_clone.reference_text_file == "global.txt"
    settings._clone_explicit = frozenset({"enabled", "reference_audio", "reference_text_file"})
    settings.tts.voice_clone.enabled = False
    selected = settings_for_book_tts(settings, "Book")
    assert not selected.tts.voice_clone.enabled
    assert selected.tts.voice_clone.reference_audio == "global.wav"


def test_reference_selection_rejects_unsupported_or_conflicting_choices(tmp_path: Path) -> None:
    settings = settings_for_reference(tmp_path)
    validate_clone_selection(settings)
    settings._clone_explicit = frozenset({"voice"})
    with pytest.raises(ConfigError) as error:
        validate_clone_selection(settings)
    assert error.value.error_reason == "voice_selection_conflict"
    settings._clone_explicit = frozenset()
    settings.tts.kitten.model = "mini"
    with pytest.raises(ConfigError) as error:
        validate_clone_selection(settings)
    assert error.value.error_reason == "voice_clone_unsupported"


@pytest.mark.parametrize("value", ["https://example.com/voice.wav", "bad\0name", "missing.wav"])
def test_reference_unsafe_or_missing_paths_are_private(value: str) -> None:
    with pytest.raises(ConfigError) as error:
        _snapshot_bytes(value, 1024)
    assert value not in str(error.value)


def test_reference_accepts_an_explicit_regular_file_target_but_not_fifo_or_broken_link(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"abc")
    link = tmp_path / "link"
    link.symlink_to(source)
    assert _snapshot_bytes(str(link), 10) == b"abc"
    source.unlink()
    with pytest.raises(ConfigError):
        _snapshot_bytes(str(link), 10)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(ConfigError):
        _snapshot_bytes(str(fifo), 10)


def test_legacy_model_identity_stays_identical_for_the_same_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pdf2audiobook.tts import selection

    monkeypatch.setattr(selection, "package_version", lambda _: "0.9.6")
    assert (
        selection._tts_model_identity(Settings())
        == "1f3c2200e71ea50ebed4f2cde48c21ec55f3509b8c126f1dd1ccdbe295ba66b8"
    )


def test_reference_snapshot_is_content_addressed_private_and_immutable(tmp_path: Path) -> None:
    settings = settings_for_reference(tmp_path)
    first = snapshot_reference(settings)
    try:
        assert first.transcript == "A synthetic reference, not book text."
        assert "PRIVATE" not in str(first.identity)
        assert "synthetic reference" not in repr(first)
        assert first.wav is not None
        original = first.wav.read_bytes()
        source = Path(settings.tts.voice_clone.reference_audio or "")
        before = source.stat()
        recording(source, frequency=660)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        second = snapshot_reference(settings)
        try:
            assert second.key != first.key
            assert first.wav.read_bytes() == original
            assert source.stat().st_size == before.st_size
        finally:
            second.close()
        directory = first.wav.parent
    finally:
        first.close()
    assert not directory.exists()
    assert source.exists()


def test_identical_reference_moved_to_another_path_reuses_identity(tmp_path: Path) -> None:
    settings = settings_for_reference(tmp_path)
    first = snapshot_reference(settings)
    try:
        moved = tmp_path / "moved.wav"
        moved.write_bytes(Path(settings.tts.voice_clone.reference_audio or "").read_bytes())
        settings.tts.voice_clone.reference_audio = str(moved)
        second = snapshot_reference(settings)
        try:
            assert first.identity == second.identity
            assert first.key == second.key
        finally:
            second.close()
    finally:
        first.close()


@pytest.mark.parametrize("seconds,silent", [(4, False), (31, False), (6, True)])
def test_reference_bounds_and_silence_fail_before_model_loading(
    tmp_path: Path, seconds: int, silent: bool
) -> None:
    settings = settings_for_reference(tmp_path)
    recording(Path(settings.tts.voice_clone.reference_audio or ""), seconds=seconds, silent=silent)
    with pytest.raises(ConfigError):
        snapshot_reference(settings)
    assert not list(private_root().glob("job-*")) if private_root().exists() else True


@pytest.mark.parametrize("suffix", ["flac", "mp3"])
def test_supported_compressed_reference_formats(tmp_path: Path, suffix: str) -> None:
    settings = settings_for_reference(tmp_path)
    converted = tmp_path / f"reference.{suffix}"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            settings.tts.voice_clone.reference_audio or "",
            str(converted),
        ],
        check=True,
    )
    settings.tts.voice_clone.reference_audio = str(converted)
    reference = snapshot_reference(settings)
    reference.close()


def test_transcript_is_optional_for_dry_run_and_no_asr_is_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for_reference(tmp_path)
    settings.tts.voice_clone.reference_text_file = None
    monkeypatch.setattr(
        "pdf2audiobook.tts.worker_client.transcribe_reference", lambda _: pytest.fail("ASR loaded")
    )
    reference = snapshot_reference(settings, transcribe=False)
    assert reference.transcript is None
    reference.close()


def test_changed_source_capture_is_detected_without_exposing_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "PRIVATE_NAME"
    path.write_bytes(b"abc")
    original = os.fstat
    calls = 0

    def changed(fd: int):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_bytes(b"def")
        return original(fd)

    monkeypatch.setattr(os, "fstat", changed)
    with pytest.raises(AudioError) as error:
        _snapshot_bytes(str(path), 10)
    assert error.value.error_reason == "voice_reference_changed"
    assert "PRIVATE_NAME" not in str(error.value)


def test_worker_failure_and_timeout_are_private_and_reaped() -> None:
    code = "import sys,time;sys.stdin.readline();sys.stderr.write('PRIVATE_TEXT');sys.stderr.flush();time.sleep(99)"
    worker = WorkerClient([sys.executable, "-c", code])
    started = time.monotonic()
    with pytest.raises(AudioError) as error:
        worker.request({"command": "test", "text": "PRIVATE_NARRATION"}, timeout=0.1)
    assert "PRIVATE" not in str(error.value)
    assert worker.process.poll() is not None
    assert time.monotonic() - started < 8


def test_private_cleanup_preserves_active_and_unowned_directories(tmp_path: Path) -> None:
    active = PrivateDirectory()
    foreign = private_root() / "job-foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("not our data")
    cleanup_private_jobs()
    assert Path(active.name).is_dir()
    assert foreign.is_dir()
    active.cleanup()


def test_private_cleanup_removes_crashed_owned_jobs() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from pdf2audiobook.tts.private import PrivateDirectory;import os;p=PrivateDirectory();open(p.name+'/reference','w').write('PRIVATE');os._exit(0)",
        ],
        check=True,
    )
    assert list(private_root().glob("job-*"))
    cleanup_private_jobs()
    assert not list(private_root().glob("job-*"))


def test_model_fetch_is_verified_atomic_and_cancel_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = {
        "repo": catalog.MODEL_ID,
        "revision": "a" * 40,
        "name": "weights.bin",
        "size": 3,
        "sha256": hashlib.sha256(b"abc").hexdigest(),
    }
    monkeypatch.setitem(catalog.MANIFEST, "files", [artifact])
    root = tmp_path / "models"
    assert catalog.fetch_model(root, opener=lambda *a, **kw: io.BytesIO(b"abc")) == ["weights.bin"]
    assert catalog.verified(artifact, root)
    assert catalog.fetch_model(root, opener=lambda *a, **kw: pytest.fail("downloaded twice")) == []
    target = catalog.artifact_path(artifact, root)
    before = target.stat()
    target.write_bytes(b"def")
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert not catalog.verified(artifact, root)
    with pytest.raises(AudioError):
        catalog.fetch_model(root, opener=lambda *a, **kw: io.BytesIO(b"BAD"))
    assert target.read_bytes() == b"def"
    assert not list(root.rglob(".part-*"))


def test_speed_transform_preserves_finite_mono_audio() -> None:
    samples = np.sin(np.arange(24000, dtype=np.float32) * 0.1) * 0.2
    faster = change_speed(samples, 2)
    assert 9000 < len(faster) < 14000
    assert faster.ndim == 1 and np.isfinite(faster).all()


def test_download_interruption_removes_unpublished_files(tmp_path, monkeypatch):
    artifact = {
        "repo": catalog.MODEL_ID,
        "revision": catalog.MODEL_REVISION,
        "name": "weights",
        "size": 4,
        "sha256": hashlib.sha256(b"data").hexdigest(),
    }
    monkeypatch.setitem(catalog.MANIFEST, "files", [artifact])

    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        catalog.fetch_model(tmp_path, opener=lambda *a, **kw: Interrupted(b"data"))
    assert not list(tmp_path.rglob(".part-*"))
    assert not catalog.artifact_path(artifact, tmp_path).exists()


def test_private_worker_protocol_omits_voice_and_reuses_conditioning(tmp_path, monkeypatch):
    fake = tmp_path / "fake_sdk"
    fake.mkdir()
    (fake / "huggingface_hub.py").write_text("hf_hub_download = None\n")
    (fake / "kittenml.py").write_text("""
import numpy as np
class KittenTTS2:
    def __init__(self, *a, **kw): self.prepared = False
    def _speaker(self, voice, reference, transcript):
        assert voice is None and reference and transcript == "PRIVATE WORDS"
        self.prepared = True
    def generate(self, text, **kw):
        assert self.prepared and "voice" not in kw
        assert kw["reference_text"] == "PRIVATE WORDS"
        assert "PRIVATE" not in text
        print("PRIVATE noisy backend output")
        import os
        os.write(1, b"PRIVATE native output\\n")
        os.write(2, b"PRIVATE native error\\n")
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
        assert client.request(
            {"command": "prepare", "reference": "/private/ref.wav", "transcript": "PRIVATE WORDS"}
        ) == {"ok": True}
        for n in range(2):
            output = tmp_path / f"chunk-{n}.npy"
            response = client.request(
                {
                    "command": "generate",
                    "text": "Book narration.",
                    "reference": "/private/ref.wav",
                    "transcript": "PRIVATE WORDS",
                    "temperature": 0.2,
                    "output": str(output),
                }
            )
            assert response == {"ok": True}
            assert np.load(output, allow_pickle=False).size == 2400
        assert "PRIVATE" not in str(client.process.args)
        with pytest.raises(AudioError) as error:
            client.request(
                {
                    "command": "prepare",
                    "reference": "/private/ref.wav",
                    "transcript": "PRIVATE_WRONG_WORDS",
                }
            )
        assert "PRIVATE" not in str(error.value)
        assert error.value.error_reason == "voice_reference_invalid"
        assert client.process.poll() is not None
    finally:
        client.close()


@pytest.mark.parametrize(
    ("cli_audio", "cli_text", "expected_audio", "expected_text"),
    [
        (None, None, "profile.wav", "profile.txt"),
        ("cli.wav", None, "cli.wav", None),
        ("cli.wav", "cli.txt", "cli.wav", "cli.txt"),
        (None, "cli.txt", "profile.wav", "cli.txt"),
    ],
)
def test_cli_reference_pair_cannot_inherit_a_profile_transcript(
    tmp_path, cli_audio, cli_text, expected_audio, expected_text
):
    path = tmp_path / "config.toml"
    path.write_text(
        '[tts.voice_clone]\nenabled=true\nreference_audio="global.wav"\nreference_text_file="global.txt"\n[tts.profiles.Book]\nclone_voice=true\nreference_audio="profile.wav"\nreference_text_file="profile.txt"\n'
    )
    override = {}
    if cli_audio is not None:
        override["reference_audio"] = cli_audio
    if cli_text is not None:
        override["reference_text_file"] = cli_text
    settings, _ = load_settings(
        path,
        environ={
            "PDF2AUDIOBOOK_REFERENCE_AUDIO": "env.wav",
            "PDF2AUDIOBOOK_REFERENCE_TEXT_FILE": "env.txt",
        },
        overrides={"tts": {"voice_clone": override}},
    )
    selected = settings_for_book_tts(settings, "Book")
    assert (
        selected.tts.voice_clone.reference_audio,
        selected.tts.voice_clone.reference_text_file,
    ) == (expected_audio, expected_text)


@pytest.mark.parametrize("data", [b"", b"\xff", b"\x00", b" " * 65537])
def test_transcript_files_are_bounded_utf8_and_nonempty(tmp_path, data):
    settings = settings_for_reference(tmp_path)
    Path(settings.tts.voice_clone.reference_text_file).write_bytes(data)
    with pytest.raises(ConfigError) as error:
        snapshot_reference(settings)
    assert "PRIVATE" not in str(error.value)
    assert not list(private_root().glob("job-*"))


def test_auto_transcript_uses_local_backend_and_only_the_snapshot(tmp_path, monkeypatch):
    settings = settings_for_reference(tmp_path)
    settings.tts.voice_clone.reference_text_file = None
    seen = []

    def transcribe(path):
        assert path != Path(settings.tts.voice_clone.reference_audio)
        assert path.is_file()
        seen.append(path)
        return "Reference words\r\n", {"model": "pinned", "package": "test"}

    monkeypatch.setattr("pdf2audiobook.tts.worker_client.transcribe_reference", transcribe)
    snapshot = snapshot_reference(settings)
    assert snapshot.transcript == "Reference words"
    assert snapshot.identity["transcription"] == {"model": "pinned", "package": "test"}
    snapshot.close()
    assert seen and not seen[0].exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux parent-death signal")
def test_worker_dies_if_cli_parent_is_force_killed(tmp_path):
    import signal

    parent = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            "from pdf2audiobook.tts.worker_client import WorkerClient; import time; c=WorkerClient(); print(c.process.pid, flush=True); time.sleep(30)",
        ],
        stdout=subprocess.PIPE,
    )
    worker_pid = int(parent.stdout.readline())
    try:
        # Allow the worker to arm its death signal before terminating the parent.
        time.sleep(0.5)
        parent.kill()
        parent.wait(timeout=3)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                state = Path(f"/proc/{worker_pid}/stat").read_text().split()[2]
            except (FileNotFoundError, ProcessLookupError):
                break  # Gone, including between finding and reading its /proc entry.
            if state == "Z":
                break
            time.sleep(0.05)
        else:
            pytest.fail("orphaned model worker survived its CLI parent")
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        try:
            os.kill(worker_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        parent.stdout.close()


def test_relative_reference_paths_match_identical_absolute_content(tmp_path, monkeypatch):
    settings = settings_for_reference(tmp_path)
    absolute = snapshot_reference(settings)
    try:
        monkeypatch.chdir(tmp_path)
        settings.tts.voice_clone.reference_audio = Path(
            settings.tts.voice_clone.reference_audio
        ).name
        settings.tts.voice_clone.reference_text_file = Path(
            settings.tts.voice_clone.reference_text_file
        ).name
        relative = snapshot_reference(settings)
        try:
            assert relative.key == absolute.key
        finally:
            relative.close()
    finally:
        absolute.close()


def test_oversized_and_nonfinite_recordings_are_rejected(tmp_path):
    import struct

    settings = settings_for_reference(tmp_path)
    path = Path(settings.tts.voice_clone.reference_audio)
    with path.open("wb") as stream:
        stream.truncate(10 * 1024 * 1024 + 1)
    with pytest.raises(ConfigError):
        snapshot_reference(settings)
    data = np.full(24000 * 6, np.nan, dtype="<f4").tobytes()
    fmt = struct.pack("<HHIIHH", 3, 1, 24000, 24000 * 4, 4, 32)
    path.write_bytes(
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<I", 16)
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )
    with pytest.raises((ConfigError, AudioError)):
        snapshot_reference(settings)


def test_recorded_clone_identity_rejects_opaque_private_metadata(tmp_path):
    from copy import deepcopy

    from pdf2audiobook.tts.cloning import valid_recorded_identity

    reference = snapshot_reference(settings_for_reference(tmp_path))
    try:
        assert valid_recorded_identity(reference.identity)
        for versions in ({"private": "PRIVATE_WORDS"}, {"torch": "/PRIVATE/voice.wav"}):
            identity = deepcopy(reference.identity)
            identity["backend_versions"] = versions
            assert not valid_recorded_identity(identity)
        identity = deepcopy(reference.identity)
        identity["unexpected_transcript"] = "PRIVATE_WORDS"
        assert not valid_recorded_identity(identity)
    finally:
        reference.close()


def test_worker_deadline_includes_a_large_request_to_a_blocked_stdin():
    client = WorkerClient([sys.executable, "-c", "import time; time.sleep(30)"])
    started = time.monotonic()
    with pytest.raises(AudioError) as error:
        client.request({"transcript": "PRIVATE " * 8192}, timeout=0.05)
    assert time.monotonic() - started < 3
    assert "PRIVATE" not in str(error.value)
    assert client.process.poll() is not None


def test_unsupported_worker_platform_preserves_non_clone_configuration(tmp_path, monkeypatch):
    from pdf2audiobook.tts import cloning, private

    monkeypatch.setattr(cloning, "worker_supported", lambda: False)
    monkeypatch.setattr(private, "worker_supported", lambda: False)
    private.cleanup_private_jobs()
    validate_clone_selection(Settings())
    with pytest.raises(ConfigError) as error:
        validate_clone_selection(settings_for_reference(tmp_path))
    assert error.value.error_reason == "voice_clone_unsupported"


def test_stopping_a_worker_cleans_its_private_asr_job_and_preserves_active_jobs():
    code = (
        "import json,time; from pathlib import Path; "
        "from pdf2audiobook.tts.private import PrivateDirectory; "
        "job=PrivateDirectory('transcription'); "
        "(Path(job.name)/'reference.wav').write_bytes(b'PRIVATE_AUDIO'); "
        "print(json.dumps({'ok':True,'directory':job.name}),flush=True); time.sleep(30)"
    )
    with PrivateDirectory("reference") as active:
        client = WorkerClient([sys.executable, "-c", code])
        try:
            result = client.request({"command": "prepare"}, timeout=5)
            child_job = Path(result["directory"])
            assert child_job.is_dir()
        finally:
            client.close()
        assert not child_job.exists()
        assert Path(active).is_dir()
