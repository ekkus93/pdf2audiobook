"""Offline end-to-end clone conversion: real CLI, cache, MP3 publication and repairs."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import numpy as np
import pytest
from test_voice_cloning import recording
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.errors import AudioError

runner = CliRunner()


@pytest.fixture
def cloned_book(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "book.pdf"
    with fitz.open() as pdf:
        for n in (1, 2):
            page = pdf.new_page()
            page.insert_text((80, 60), f"Chapter {n}")
            page.insert_text(
                (80, 115), f"Book narration for chapter {n}. Another sentence follows."
            )
        pdf.save(source)
    audio = recording(tmp_path / "PRIVATE_RECORDING.wav")
    text = tmp_path / "PRIVATE_TRANSCRIPT.txt"
    text.write_text("These are PRIVATE reference words, never narration.")
    calls, closed = [], []

    class FakeClone:
        sample_rate = 24000
        max_chars_per_chunk = 350
        supports_voice_listing = False

        def __init__(self, reference):
            assert reference.wav.exists()
            self.reference = reference

        def generate(self, narration, *, voice, speed):
            assert voice == self.reference.key
            assert "PRIVATE" not in narration
            calls.append((narration, voice, speed))
            return np.ones(4800, dtype=np.float32) * 0.03

        def close(self):
            closed.append(True)

    monkeypatch.setattr("pdf2audiobook.tts.clone_provider.KittenCloneProvider", FakeClone)
    monkeypatch.setattr("pdf2audiobook.tts.catalog.require_model", lambda: None)
    args = [
        "convert",
        str(source),
        "--no-llm",
        "--ocr",
        "never",
        "--output",
        str(tmp_path / "out"),
        "--tts-model",
        "kitten2",
        "--clone-voice",
        "--reference-audio",
        str(audio),
        "--reference-text-file",
        str(text),
        "--json",
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    manifest = next((tmp_path / "out").glob("*/manifest.json"))
    return {
        "source": source,
        "audio": audio,
        "text": text,
        "calls": calls,
        "closed": closed,
        "args": args,
        "manifest": manifest,
    }


def test_clone_resume_uses_finished_audio_without_reference_or_dependencies(
    cloned_book, monkeypatch
):
    book = cloned_book
    before = len(book["calls"])
    book["audio"].unlink()
    book["text"].unlink()
    monkeypatch.setattr(
        "pdf2audiobook.tts.catalog.require_model",
        lambda: pytest.fail("cached audio needs no model"),
    )
    result = runner.invoke(app, book["args"])
    assert result.exit_code == 0, result.output
    assert len(book["calls"]) == before
    for sidecar in (book["manifest"].parent / "audio").glob("*.cache.json"):
        metadata = json.loads(sidecar.read_text())
        assert "voice_clone" in metadata["rendering_inputs"]
        assert "PRIVATE" not in sidecar.read_text()
    assert book["closed"]


def test_reference_and_transcript_changes_invalidate_audio_without_reanalysis(cloned_book):
    book = cloned_book
    manifest_before = book["manifest"].read_bytes()
    calls = len(book["calls"])
    recording(book["audio"], frequency=660)
    result = runner.invoke(app, book["args"])
    assert result.exit_code == 0, result.output
    assert len(book["calls"]) > calls
    calls = len(book["calls"])
    book["text"].write_text("A different PRIVATE reference transcript.")
    result = runner.invoke(app, book["args"])
    assert result.exit_code == 0, result.output
    assert len(book["calls"]) > calls
    assert book["manifest"].read_bytes() == manifest_before


def test_clone_repair_requires_selection_and_failure_keeps_old_audio(cloned_book, monkeypatch):
    book = cloned_book
    audio_dir = book["manifest"].parent / "audio"
    previous = {p.name: p.read_bytes() for p in audio_dir.glob("*") if p.is_file()}
    request = ["resynthesize", str(book["manifest"]), "--chapter", "1", "--json"]
    result = runner.invoke(app, request)
    assert result.exit_code == 2, result.output
    assert json.loads(result.stderr)["error"]["reason"] == "voice_selection_conflict"

    def fail(_reference):
        raise AudioError("Local model unavailable", error_reason="voice_clone_unavailable")

    monkeypatch.setattr("pdf2audiobook.tts.clone_provider.KittenCloneProvider", fail)
    result = runner.invoke(
        app,
        request
        + [
            "--tts-model",
            "kitten2",
            "--clone-voice",
            "--reference-audio",
            str(book["audio"]),
            "--reference-text-file",
            str(book["text"]),
        ],
    )
    assert result.exit_code == 6, result.output
    assert {p.name: p.read_bytes() for p in audio_dir.glob("*") if p.is_file()} == previous
    assert not list((audio_dir / ".staging").glob("*"))


def test_clone_selective_repair_backs_up_only_chosen_audio(cloned_book):
    book = cloned_book
    audio_dir = book["manifest"].parent / "audio"
    first = next(audio_dir.glob("001 *.mp3")).read_bytes()
    book["calls"].clear()
    result = runner.invoke(
        app,
        [
            "resynthesize",
            str(book["manifest"]),
            "--chapter",
            "2",
            "--tts-model",
            "kitten2",
            "--clone-voice",
            "--reference-audio",
            str(book["audio"]),
            "--reference-text-file",
            str(book["text"]),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert next(audio_dir.glob("001 *.mp3")).read_bytes() == first
    assert len(list((audio_dir / ".backup").glob("002 *.mp3"))) == 1
    assert book["calls"] and not any("chapter 1" in text.lower() for text, _, _ in book["calls"])


def test_only_selected_chapter_overrides_conflict(cloned_book):
    book = cloned_book
    metadata = json.loads(book["manifest"].read_text())
    metadata["chapters"][1]["voice_id"] = "Luna"
    book["manifest"].write_text(json.dumps(metadata))
    result = runner.invoke(app, book["args"] + ["--chapter", "1", "--dry-run"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, book["args"] + ["--chapter", "2", "--dry-run"])
    assert result.exit_code == 2, result.output
    assert "voice_selection_conflict" in result.output


@pytest.mark.parametrize(
    "command",
    [
        ["--help"],
        ["config", "init", "--json"],
        ["doctor", "--no-config", "--json"],
        ["voices", "--no-config", "--json"],
        ["voices", "--tts-model", "kitten2", "--json"],
        ["tts", "models", "--json"],
    ],
)
def test_discovery_does_not_import_ml_or_access_network(command, tmp_path, monkeypatch):
    import builtins
    import importlib.metadata
    import socket

    original_version = importlib.metadata.version
    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda name: "0.9.6" if name == "kittenml" else original_version(name),
    )
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name.split(".")[0] not in {"kittenml", "torch", "transformers", "whisper"}
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("implicit network"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    result = runner.invoke(app, command)
    assert result.exit_code == 0, result.output


def test_model_diagnostics_match_desktop_contracts(tmp_path, monkeypatch):
    import jsonschema

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    root = Path(__file__).resolve().parents[1] / "desktop" / "contracts"
    result = runner.invoke(app, ["tts", "models", "--json"])
    assert result.exit_code == 0, result.output
    jsonschema.validate(
        json.loads(result.stdout), json.loads((root / "tts-models.schema.json").read_text())
    )
    result = runner.invoke(app, ["voices", "--no-config", "--tts-model", "kitten2", "--json"])
    assert result.exit_code == 0, result.output
    jsonschema.validate(
        json.loads(result.stdout), json.loads((root / "voices.schema.json").read_text())
    )


def test_fetch_without_download_and_clone_diagnostics_contract(tmp_path, monkeypatch):
    import jsonschema

    import pdf2audiobook.cli.tts_models as commands
    from pdf2audiobook.config import Settings
    from pdf2audiobook.tts import catalog
    from pdf2audiobook.tts.cloning import clone_diagnostics

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(catalog, "missing_files", lambda *args: [])
    monkeypatch.setattr(commands, "missing_files", lambda *args: [])
    root = Path(__file__).resolve().parents[1] / "desktop" / "contracts"
    result = runner.invoke(app, ["tts", "fetch", "kitten2", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    jsonschema.validate(
        json.loads(result.stdout), json.loads((root / "tts-fetch.schema.json").read_text())
    )
    jsonschema.validate(
        clone_diagnostics(Settings()), json.loads((root / "voice-clone.schema.json").read_text())
    )


def test_batch_clone_profiles_and_partial_failures_are_private(cloned_book, tmp_path):
    book = cloned_book
    books = tmp_path / "batch"
    books.mkdir()
    (books / "Good.pdf").write_bytes(book["source"].read_bytes())
    (books / "Bad.pdf").write_bytes(book["source"].read_bytes())
    config = tmp_path / "batch.toml"
    config.write_text(
        '[llm]\nenabled=false\n[pdf]\nocr="never"\n[tts.kitten]\nmodel="kitten2"\n[tts.profiles.Good]\nclone_voice=true\nreference_audio='
        + json.dumps(str(book["audio"]))
        + "\nreference_text_file="
        + json.dumps(str(book["text"]))
        + '\n[tts.profiles.Bad]\nclone_voice=true\nreference_audio="PRIVATE_missing.wav"\n'
    )
    result = runner.invoke(
        app,
        [
            "batch",
            str(books),
            "--config",
            str(config),
            "--output",
            str(tmp_path / "batch-out"),
            "--json",
        ],
    )
    assert result.exit_code == 7, result.output
    payload = json.loads(result.stdout)
    assert payload["failed"] == 1
    assert {row["book"]: row["ok"] for row in payload["books"]} == {
        "Good.pdf": True,
        "Bad.pdf": False,
    }
    assert "PRIVATE" not in result.output


def test_cancelled_clone_repair_keeps_prior_audio_and_cleans_private_files(
    cloned_book, monkeypatch
):
    import pdf2audiobook.tts.clone_provider as providers
    from pdf2audiobook.tts.private import private_root

    book = cloned_book
    directory = book["manifest"].parent / "audio"
    before = {path.name: path.read_bytes() for path in directory.glob("*") if path.is_file()}
    parent = providers.KittenCloneProvider

    class Cancelled(parent):
        def generate(self, *args, **kwargs):
            raise KeyboardInterrupt

    monkeypatch.setattr(providers, "KittenCloneProvider", Cancelled)
    result = runner.invoke(
        app,
        [
            "resynthesize",
            str(book["manifest"]),
            "--chapter",
            "1",
            "--tts-model",
            "kitten2",
            "--clone-voice",
            "--reference-audio",
            str(book["audio"]),
            "--reference-text-file",
            str(book["text"]),
            "--json",
        ],
    )
    assert result.exit_code == 130, result.output
    assert {
        path.name: path.read_bytes() for path in directory.glob("*") if path.is_file()
    } == before
    assert not list(private_root().glob("job-*"))


def test_finished_clone_packs_and_builds_asr_narration_without_original_or_model(
    cloned_book, tmp_path
):
    from pdf2audiobook.config import Settings
    from pdf2audiobook.verification.reference import Reference, chapter_reference
    from pdf2audiobook.workspace import read_manifest

    book = cloned_book
    book["audio"].unlink()
    book["text"].unlink()
    result = runner.invoke(
        app,
        [
            "pack-m4b",
            str(book["manifest"]),
            "--output",
            str(tmp_path / "book.m4b"),
            "--no-config",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    settings = Settings()
    settings.tts.provider = "piper"
    settings.tts.piper.voice = "de_DE-test"
    manifest = read_manifest(book["manifest"])
    reference = chapter_reference(book["manifest"].parent, manifest, manifest.chapters[0], settings)
    assert isinstance(reference, Reference)
    assert reference.voice == "Cloned voice"
    assert "PRIVATE" not in reference.text and "Book narration" in reference.text


def test_corrupt_cloned_audio_still_requires_explicit_voice_switch(cloned_book):
    book = cloned_book
    audio = next((book["manifest"].parent / "audio").glob("001 *.mp3"))
    audio.write_bytes(b"corrupt")
    result = runner.invoke(app, ["resynthesize", str(book["manifest"]), "--chapter", "1", "--json"])
    assert result.exit_code == 2, result.output
    assert "voice_selection_conflict" in result.output
    assert audio.read_bytes() == b"corrupt"


def test_dry_run_and_config_validation_never_load_or_download_models(
    cloned_book, monkeypatch, tmp_path
):
    import builtins
    import socket

    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name.split(".")[0] not in {"kittenml", "torch", "transformers", "whisper"}
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("implicit network"))
    result = runner.invoke(app, cloned_book["args"] + ["--dry-run"])
    assert result.exit_code == 0, result.output
    config = tmp_path / "valid.toml"
    config.write_text(
        '[tts.kitten]\nmodel="kitten2"\n[tts.voice_clone]\nenabled=true\nreference_audio="PRIVATE_not_present.wav"\n'
    )
    result = runner.invoke(app, ["config", "validate", "--config", str(config), "--json"])
    assert result.exit_code == 0, result.output
    assert "PRIVATE" not in result.output


def test_optional_transcript_uses_only_local_asr_for_the_snapshot(cloned_book, monkeypatch):
    from pdf2audiobook.verification.models import SPECS

    book = cloned_book
    args = book["args"].copy()
    start = args.index("--reference-text-file")
    del args[start : start + 2]
    paths = []

    def transcribe(path):
        paths.append(path)
        assert path.is_file() and path != book["audio"]
        return "Auto reference words.", {"model": SPECS["whisper"].revision, "package": "fake"}

    monkeypatch.setattr("pdf2audiobook.tts.worker_client.transcribe_reference", transcribe)
    result = runner.invoke(app, args + ["--force"])
    assert result.exit_code == 0, result.output
    assert len(paths) == 1 and not paths[0].exists()
    assert "Auto reference words" not in result.output
    assert not any("Auto reference words" in text for text, _, _ in book["calls"])


def test_missing_local_asr_never_falls_back_or_downloads(cloned_book, monkeypatch):
    from types import SimpleNamespace

    book = cloned_book
    args = book["args"].copy()
    start = args.index("--reference-text-file")
    del args[start : start + 2]
    monkeypatch.setattr(
        "pdf2audiobook.verification.models.readiness", lambda *a: SimpleNamespace(ready=False)
    )
    before = len(book["calls"])
    result = runner.invoke(app, args + ["--force"])
    assert result.exit_code == 6, result.output
    assert "voice_clone_unavailable" in result.output and "PRIVATE" not in result.output
    assert len(book["calls"]) == before


def test_selected_paragraph_voice_markers_conflict_before_synthesis(cloned_book, monkeypatch):
    import pdf2audiobook.pipeline as pipeline

    original = pipeline.render_chapter_texts

    def render(manifest, folder, *args, **kwargs):
        result = original(manifest, folder, *args, **kwargs)
        (folder / "chapters" / "002.txt").write_text("Before.\n\n[[voice:Luna]]\n\nAfter.")
        return result

    monkeypatch.setattr(pipeline, "render_chapter_texts", render)
    before = len(cloned_book["calls"])
    result = runner.invoke(app, cloned_book["args"] + ["--chapter", "2", "--force"])
    assert result.exit_code == 2, result.output
    assert "voice_selection_conflict" in result.output
    assert len(cloned_book["calls"]) == before


def test_model_revision_change_invalidates_selected_audio_without_changing_analysis(
    cloned_book, monkeypatch
):
    from pdf2audiobook.tts.cloning import GENERATION

    book = cloned_book
    directory = book["manifest"].parent / "audio"
    second = {path.name: path.read_bytes() for path in directory.glob("002 *") if path.is_file()}
    analysis = book["manifest"].read_bytes()
    book["calls"].clear()
    monkeypatch.setitem(GENERATION, "model_revision", "b" * 40)
    result = runner.invoke(app, book["args"] + ["--chapter", "1"])
    assert result.exit_code == 0, result.output
    assert book["calls"]
    assert not any("chapter 2" in text.lower() for text, _, _ in book["calls"])
    assert {
        path.name: path.read_bytes() for path in directory.glob("002 *") if path.is_file()
    } == second
    assert book["manifest"].read_bytes() == analysis


def test_explicit_disable_repairs_with_a_builtin_and_ignores_retained_paths(
    cloned_book, monkeypatch, tmp_path
):
    book = cloned_book
    calls = []

    class Builtin:
        sample_rate = 24000
        max_chars_per_chunk = 350

        def __init__(self, model):
            assert model == "mini"

        def generate(self, text, *, voice, speed):
            calls.append(voice)
            return np.full(4800, 0.03, dtype=np.float32)

    monkeypatch.setattr("pdf2audiobook.pipeline.KittenProvider", Builtin)
    config = tmp_path / "inherited.toml"
    config.write_text(
        '[tts.kitten]\nmodel="kitten2"\n[tts.voice_clone]\nenabled=true\nreference_audio="PRIVATE_missing.wav"\nreference_text_file="PRIVATE_missing.txt"\n'
    )
    result = runner.invoke(
        app,
        [
            "resynthesize",
            str(book["manifest"]),
            "--chapter",
            "1",
            "--config",
            str(config),
            "--tts-model",
            "mini",
            "--voice",
            "Luna",
            "--no-clone-voice",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls and set(calls) == {"Luna"}
    sidecar = next((book["manifest"].parent / "audio").glob("001 *.cache.json"))
    assert "voice_clone" not in json.loads(sidecar.read_text())["rendering_inputs"]
    assert "PRIVATE" not in result.output


def test_missing_clone_dependencies_stop_before_synthesis(cloned_book, monkeypatch):
    import pdf2audiobook.tts.catalog as catalog
    import pdf2audiobook.tts.clone_provider as providers

    monkeypatch.setattr(catalog, "require_model", providers.require_model)
    monkeypatch.setattr(
        catalog, "model_readiness", lambda: {"ready": False, "reason": "model_not_installed"}
    )
    before = len(cloned_book["calls"])
    result = runner.invoke(app, cloned_book["args"] + ["--force"])
    assert result.exit_code == 6, result.output
    assert "voice_clone_unavailable" in result.output and "PRIVATE" not in result.output
    assert len(cloned_book["calls"]) == before


def test_a_failed_clone_chapter_preserves_its_old_pair_and_other_chapters_finish(
    cloned_book, monkeypatch
):
    import pdf2audiobook.tts.clone_provider as providers

    book = cloned_book
    directory = book["manifest"].parent / "audio"
    old = {path.name: path.read_bytes() for path in directory.glob("002 *") if path.is_file()}
    parent = providers.KittenCloneProvider

    class FailedSecond(parent):
        def generate(self, text, *, voice, speed):
            if "chapter 2" in text.lower() or "chapter two" in text.lower():
                raise AudioError("Local synthesis failed", error_reason="voice_clone_unavailable")
            return super().generate(text, voice=voice, speed=speed)

    monkeypatch.setattr(providers, "KittenCloneProvider", FailedSecond)
    result = runner.invoke(app, book["args"] + ["--force"])
    assert result.exit_code == 7, result.output
    assert {
        path.name: path.read_bytes() for path in directory.glob("002 *") if path.is_file()
    } == old
    rows = json.loads((book["manifest"].parent / "reports/conversion_status.json").read_text())[
        "chapters"
    ]
    assert rows[0]["status"] == "complete" and rows[1]["status"] == "failed"
    assert "PRIVATE" not in result.output


def test_clone_range_selection_only_returns_the_requested_audio(cloned_book):
    result = runner.invoke(app, cloned_book["args"] + ["--chapter-range", "1:1"])
    assert result.exit_code == 0, result.output
    files = json.loads(result.stdout)["mp3_files"]
    assert len(files) == 1 and Path(files[0]).name.startswith("001 ")


@pytest.mark.parametrize("extra", [["--voice", "Luna"], ["--no-clone-voice"]])
def test_conflicting_clone_options_are_rejected_before_synthesis(cloned_book, extra):
    before = len(cloned_book["calls"])
    result = runner.invoke(app, cloned_book["args"] + extra)
    assert result.exit_code == 2, result.output
    assert "PRIVATE" not in result.output
    assert len(cloned_book["calls"]) == before


@pytest.mark.parametrize("command", ["convert", "batch", "resynthesize"])
@pytest.mark.parametrize("option", ["--reference-audio", "--reference-text-file"])
def test_cli_rejects_urls_even_when_a_normalized_local_path_exists(
    cloned_book, tmp_path, monkeypatch, command, option
):
    book = cloned_book
    monkeypatch.chdir(tmp_path)
    url = "https://example.invalid/PRIVATE_input.wav"
    local = Path(url)
    local.parent.mkdir(parents=True, exist_ok=True)
    original = book["audio"] if option == "--reference-audio" else book["text"]
    local.write_bytes(original.read_bytes())
    common = book["args"][book["args"].index("--tts-model") :]
    if command == "convert":
        args = book["args"]
    elif command == "batch":
        args = ["batch", str(book["source"].parent), "--no-llm"] + common
    else:
        args = ["resynthesize", str(book["manifest"]), "--chapter", "1"] + common
    before = len(book["calls"])
    result = runner.invoke(
        app, args + [option, url] + (["--force"] if command == "convert" else [])
    )
    assert result.exit_code == (7 if command == "batch" else 2), result.output
    assert "voice_reference_invalid" in result.output
    assert "PRIVATE" not in result.output
    assert len(book["calls"]) == before
