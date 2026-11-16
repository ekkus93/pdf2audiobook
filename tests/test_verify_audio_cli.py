"""`verify-audio`: contract, voting, abstention, privacy, paths, cancellation and stale reports
(audio verification AV3.01-AV3.05). Fake backends stand in for the real models."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import fitz
import jsonschema
import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import load_settings
from pdf2audiobook.verification import run as verify_run
from pdf2audiobook.verification.contracts import Readiness, Transcript, Word
from pdf2audiobook.verification.models import SPECS
from pdf2audiobook.verification.reference import Reference, chapter_reference
from pdf2audiobook.workspace import read_manifest

CONTRACT = (
    Path(__file__).resolve().parents[1] / "desktop" / "contracts" / "audio-verification.schema.json"
)
MARKER = "QUILLMARKER"
LINES = [
    f"Mara {MARKER} kept the light at the point for eleven long winters by the sea.",
    "Each evening she climbed the ninety two steps and trimmed the wick of the lamp.",
]
runner = CliRunner()


class _Kitten:
    sample_rate = 24000
    supports_voice_listing = True
    max_chars_per_chunk = 350

    def __init__(self, model: str) -> None:
        pass

    def list_voices(self) -> list[str]:
        return ["Jasper"]

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        return np.ones(4800, dtype=np.float32) * 0.03


class FakeBackend:
    """Hears each chapter's narration, optionally changed, from a script per chapter number."""

    def __init__(
        self,
        name: str,
        script: dict[int, str],
        *,
        ready: bool = True,
        fail: bool = False,
        stop_at: int | None = None,
    ) -> None:
        self.name = name
        self.script = script
        self.ready = ready
        self.fail = fail
        self.stop_at = stop_at
        self.heard: list[int] = []

    def readiness(self) -> Readiness:
        return Readiness(
            self.name,
            "fake",
            f"{self.name}-model",
            SPECS[self.name].revision,  # type: ignore[index]
            "pytest",
            "1" if self.ready else None,
            self.ready,
            1,
            "/models",
            None if self.ready else "model_not_installed",
        )  # type: ignore[arg-type]

    def transcribe(self, wav: Path, *, should_stop: Any) -> Transcript:
        number = int(wav.stem.split("-")[1])
        if self.stop_at == number:
            raise KeyboardInterrupt
        if self.fail:
            raise RuntimeError(f"model crashed reading {MARKER}")
        self.heard.append(number)
        words = self.script[number].split()
        return Transcript(
            self.name, tuple(Word(w, 1.0 + i * 0.5, 1.4 + i * 0.5) for i, w in enumerate(words))
        )  # type: ignore[arg-type]


@pytest.fixture
def book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    monkeypatch.setattr("pdf2audiobook.pipeline.KittenProvider", _Kitten)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config"))
    source = tmp_path / "book.pdf"
    pdf = fitz.open()
    for index, line in enumerate(LINES):
        page = pdf.new_page()
        page.insert_text((80, 60), f"Chapter {index + 1}")
        page.insert_text((80, 115), line)
    pdf.save(source)
    pdf.close()
    out = tmp_path / "out"
    converted = runner.invoke(
        app, ["convert", str(source), "--no-llm", "--ocr", "never", "--output", str(out), "--json"]
    )
    assert converted.exit_code == 0, converted.output
    manifest = next(out.glob("*/manifest.json"))
    settings, _ = load_settings()
    parsed = read_manifest(manifest)
    narration = {}
    for chapter in parsed.chapters:
        reference = chapter_reference(manifest.parent, parsed, chapter, settings)
        assert isinstance(reference, Reference)
        narration[chapter.number] = reference.text
    return {"manifest": manifest, "workspace": manifest.parent, "narration": narration}


def _use(monkeypatch: pytest.MonkeyPatch, backends: dict[str, FakeBackend]) -> None:
    monkeypatch.setattr(verify_run, "make_backend", lambda name, **options: backends[name])


def _scripts(book: dict[str, Any], insert_into: int | None = None) -> dict[int, str]:
    script = dict(book["narration"])
    if insert_into is not None:
        words = script[insert_into].split()
        script[insert_into] = " ".join(
            [*words[:6], "and the old ferry bell rang twice", *words[6:]]
        )
    return script


def _verify(book: dict[str, Any], *args: str) -> Any:
    return runner.invoke(app, ["verify-audio", str(book["manifest"]), *args])


def test_json_follows_the_contract_and_votes(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    changed, clean = _scripts(book, insert_into=2), _scripts(book)
    _use(
        monkeypatch,
        {
            "whisper": FakeBackend("whisper", changed),
            "wav2vec2": FakeBackend("wav2vec2", clean),
            "vosk": FakeBackend("vosk", changed),
        },
    )
    result = _verify(book, "--json")
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    jsonschema.validate(report, json.loads(CONTRACT.read_text(encoding="utf-8")))
    statuses = {c["number"]: c["status"] for c in report["chapters"]}
    assert statuses[2] == "possible_mismatch"
    assert {statuses[n] for n in statuses if n != 2} == {"no_mismatch_detected"}
    flag = next(c for c in report["chapters"] if c["number"] == 2)["flags"][0]
    assert flag["models"] == ["whisper", "vosk"] and flag["kind"] == "insertion"
    assert not any(c["partial"] for c in report["chapters"])
    # The report on disk is the same document.
    assert json.loads((book["workspace"] / "reports" / "audio_verification.json").read_text()) == {
        **report,
        "warnings": [],
    }


def test_a_model_subset_is_partial(book: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    clean = _scripts(book)
    backends = {"whisper": FakeBackend("whisper", clean), "vosk": FakeBackend("vosk", clean)}
    _use(monkeypatch, backends)
    report = json.loads(_verify(book, "--models", "whisper,vosk", "--json").stdout)
    assert all(c["partial"] for c in report["chapters"])
    assert [m["model"] for m in report["chapters"][0]["models"]] == ["whisper", "vosk"]


def test_unavailable_and_failed_models_abstain(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    changed = _scripts(book, insert_into=1)
    _use(monkeypatch, {
        "whisper": FakeBackend("whisper", changed),
        "wav2vec2": FakeBackend("wav2vec2", changed, ready=False),
        "vosk": FakeBackend("vosk", changed, fail=True),
    })  # fmt: skip
    result = _verify(book, "--json")
    assert result.exit_code == 0
    chapter = json.loads(result.stdout)["chapters"][0]
    outcomes = {m["model"]: (m["outcome"], m["reason"]) for m in chapter["models"]}
    assert outcomes == {
        "whisper": ("ok", None),
        "wav2vec2": ("unavailable", "model_not_installed"),
        "vosk": ("failed", "model_failed"),
    }
    # One voting model alone can't confirm the insertion.
    assert chapter["status"] == "model_disagreement" and chapter["partial"]
    assert MARKER not in result.stderr


def test_human_output_keeps_book_text_out_unless_asked(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _scripts(book)
    script[1] = script[1].replace("kept the light", "lost the kitchen door")
    _use(monkeypatch, {m: FakeBackend(m, script) for m in ("whisper", "wav2vec2", "vosk")})
    # --verbose adds debug events on stderr; they must hold no book text either.
    plain = runner.invoke(app, ["--verbose", "verify-audio", str(book["manifest"])])
    assert plain.exit_code == 0, plain.output
    assert "Chapter 1: possible mismatch" in plain.stdout
    assert MARKER not in plain.stdout and "kitchen" not in plain.stdout
    assert MARKER not in plain.stderr and "kitchen" not in plain.stderr
    detailed = _verify(book, "--details")
    assert "kitchen" in detailed.stdout


def test_a_symlinked_mp3_is_not_read(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mp3 = next((book["workspace"] / "audio").glob("001 *.mp3"))
    moved = tmp_path / "elsewhere.mp3"
    shutil.move(mp3, moved)
    mp3.symlink_to(moved)
    backends = {m: FakeBackend(m, _scripts(book)) for m in ("whisper", "wav2vec2", "vosk")}
    _use(monkeypatch, backends)
    report = json.loads(_verify(book, "--json").stdout)
    first = report["chapters"][0]
    assert (first["status"], first["reason"]) == ("verification_unavailable", "audio_missing")
    assert all(1 not in b.heard for b in backends.values())


def test_an_audio_folder_linked_outside_the_workspace_is_not_read(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = book["workspace"] / "audio"
    outside = tmp_path / "outside-audio"
    shutil.move(audio, outside)
    audio.symlink_to(outside, target_is_directory=True)
    backends = {m: FakeBackend(m, _scripts(book)) for m in ("whisper", "wav2vec2", "vosk")}
    _use(monkeypatch, backends)
    result = _verify(book, "--json")
    assert str(outside) not in result.output
    report = json.loads(result.stdout)
    assert {c["reason"] for c in report["chapters"]} == {"audio_missing"}
    assert all(not b.heard for b in backends.values())


def test_a_chapter_title_cannot_lead_outside_the_audio_folder(book: dict[str, Any]) -> None:
    from pdf2audiobook.audio import audio_output_path
    from pdf2audiobook.verification.reference import Unavailable

    manifest = read_manifest(book["manifest"])
    chapter = manifest.chapters[0].model_copy(update={"title": "../../../etc/passwd"})
    target = audio_output_path(manifest, chapter, book["workspace"])
    assert target.parent == book["workspace"] / "audio"
    settings, _ = load_settings()
    result = chapter_reference(book["workspace"], manifest, chapter, settings)
    assert isinstance(result, Unavailable) and result.reason == "audio_missing"


def test_unknown_chapters_and_bad_ranges_are_refused(book: dict[str, Any]) -> None:
    for args in (
        ["--chapter", "9"],
        ["--chapter-range", "2:1"],
        ["--chapter-range", "x"],
        ["--models", "deepspeech"],
        ["--device", "tpu"],
    ):
        result = _verify(book, *args, "--json")
        assert result.exit_code == 2, args


def test_interrupting_keeps_what_finished(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = _scripts(book)
    _use(monkeypatch, {
        "whisper": FakeBackend("whisper", clean),
        "wav2vec2": FakeBackend("wav2vec2", clean, stop_at=2),
        "vosk": FakeBackend("vosk", clean),
    })  # fmt: skip
    result = _verify(book, "--json")
    assert result.exit_code == 130
    assert json.loads(result.stderr)["error"]["type"] == "Interrupted"
    report = json.loads((book["workspace"] / "reports" / "audio_verification.json").read_text())
    assert report["completed_at"] is None
    first, second = report["chapters"]

    def outcomes(chapter: dict) -> dict:
        return {m["model"]: (m["outcome"], m["reason"]) for m in chapter["models"]}

    # Whisper heard both chapters; wav2vec2 was stopped on chapter 2; vosk never ran.
    assert outcomes(first) == {
        "whisper": ("ok", None),
        "wav2vec2": ("ok", None),
        "vosk": ("failed", "cancelled"),
    }
    assert outcomes(second) == {
        "whisper": ("ok", None),
        "wav2vec2": ("failed", "cancelled"),
        "vosk": ("failed", "cancelled"),
    }
    assert first["partial"] and second["partial"]
    assert (first["status"], second["status"]) == ("no_mismatch_detected", "no_mismatch_detected")
    # The chapter MP3s are untouched.
    assert all(mp3.stat().st_size > 0 for mp3 in (book["workspace"] / "audio").glob("*.mp3"))


def test_a_malformed_report_is_replaced_and_others_are_kept(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = book["workspace"] / "reports" / "audio_verification.json"
    report_path.write_text("{not json", encoding="utf-8")
    clean = _scripts(book)
    _use(monkeypatch, {m: FakeBackend(m, clean) for m in ("whisper", "wav2vec2", "vosk")})
    assert _verify(book, "--chapter", "1", "--json").exit_code == 0
    assert [c["number"] for c in json.loads(report_path.read_text())["chapters"]] == [1]
    # Verifying chapter 2 later keeps chapter 1's result.
    assert _verify(book, "--chapter", "2", "--json").exit_code == 0
    assert [c["number"] for c in json.loads(report_path.read_text())["chapters"]] == [1, 2]


def test_results_go_stale_when_audio_or_narration_change(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = _scripts(book)
    _use(monkeypatch, {m: FakeBackend(m, clean) for m in ("whisper", "wav2vec2", "vosk")})
    report = json.loads(_verify(book, "--json").stdout)
    settings, _ = load_settings()
    manifest = read_manifest(book["manifest"])
    assert verify_run.stale_chapters(book["workspace"], manifest, settings, report) == set()
    # New pronunciations change what chapter 2 ("...of the lamp") should sound like.
    tts = settings.tts.model_copy(update={"pronunciations": {"lamp": "lantern"}})
    changed = settings.model_copy(update={"tts": tts})
    assert verify_run.stale_chapters(book["workspace"], manifest, changed, report) == {2}
    # Changed audio makes chapter 1 stale under the original settings.
    mp3 = next((book["workspace"] / "audio").glob("001 *.mp3"))
    mp3.write_bytes(mp3.read_bytes() + b"\0")
    assert verify_run.stale_chapters(book["workspace"], manifest, settings, report) == {1}


def test_transcripts_are_kept_only_on_request(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = _scripts(book)
    _use(monkeypatch, {m: FakeBackend(m, clean) for m in ("whisper", "wav2vec2", "vosk")})
    assert "transcripts" not in json.loads(_verify(book, "--json").stdout)["chapters"][0]
    kept = json.loads(_verify(book, "--keep-transcripts", "--json").stdout)
    assert kept["keep_transcripts"] and len(kept["chapters"][0]["transcripts"]["whisper"]) > 5


def _convert(book: dict[str, Any], *args: str) -> Any:
    manifest = read_manifest(book["manifest"])
    source = book["manifest"].parent.parent.parent / Path(manifest.source_path).name
    return runner.invoke(
        app,
        [
            "convert",
            str(source),
            "--no-llm",
            "--ocr",
            "never",
            "--output",
            str(book["workspace"].parent),
            *args,
            "--json",
        ],
    )


def test_convert_verify_audio_adds_a_summary_and_a_warning(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    changed, clean = _scripts(book, insert_into=2), _scripts(book)
    _use(
        monkeypatch,
        {
            "whisper": FakeBackend("whisper", changed),
            "wav2vec2": FakeBackend("wav2vec2", changed),
            "vosk": FakeBackend("vosk", clean),
        },
    )
    result = _convert(book, "--verify-audio")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    jsonschema.validate(payload, _schema("convert"))
    assert len(payload["mp3_files"]) == 2
    summary = payload["audio_verification"]
    assert summary["report"] == "reports/audio_verification.json"
    assert [(c["number"], c["status"], c["flags"]) for c in summary["chapters"]] == [
        (1, "no_mismatch_detected", 0),
        (2, "possible_mismatch", 1),
    ]
    assert "audio_possible_mismatch" in payload["warnings"]


def test_convert_verify_audio_checks_only_the_converted_chapters(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = _scripts(book)
    backends = {m: FakeBackend(m, clean) for m in ("whisper", "wav2vec2", "vosk")}
    _use(monkeypatch, backends)
    result = _convert(book, "--chapter", "2", "--force", "--verify-audio")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [c["number"] for c in payload["audio_verification"]["chapters"]] == [2]
    assert all(b.heard == [2] for b in backends.values())
    assert "audio_possible_mismatch" not in payload["warnings"]


def test_convert_verify_audio_needs_real_audio(book: dict[str, Any]) -> None:
    result = _convert(book, "--dry-run", "--verify-audio")
    assert result.exit_code == 2
    assert "--dry-run" in json.loads(result.stderr)["error"]["message"]


def test_ordinary_and_dry_run_conversions_load_no_asr_library(
    book: dict[str, Any], tmp_path: Path
) -> None:
    import subprocess
    import sys

    manifest = read_manifest(book["manifest"])
    source = book["manifest"].parent.parent.parent / Path(manifest.source_path).name
    code = f"""
import sys, urllib.request
import numpy as np
import pdf2audiobook.pipeline as pipeline
from typer.testing import CliRunner
from pdf2audiobook.cli import app
class Kitten:
    sample_rate = 24000
    supports_voice_listing = True
    max_chars_per_chunk = 350
    def __init__(self, model): pass
    def list_voices(self): return ["Jasper"]
    def generate(self, text, *, voice, speed): return np.ones(4800, dtype=np.float32) * 0.03
pipeline.KittenProvider = Kitten
def no_network(*args, **kwargs): raise AssertionError("no download during conversion")
urllib.request.urlopen = no_network
base = ["convert", {str(source)!r}, "--no-llm", "--ocr", "never", "--output", {str(tmp_path / "fresh")!r}, "--json"]
for extra in ([], ["--dry-run"], ["--force"]):
    result = CliRunner().invoke(app, base + extra)
    assert result.exit_code == 0, result.output
print(sorted(m for m in ("whisper", "vosk", "transformers") if m in sys.modules))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**__import__("os").environ},
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().splitlines()[-1] == "[]"


# audio-report show / dismiss: the saved report for the desktop app (AV5.01, AV5.04).
_CONTRACTS = Path(__file__).parent.parent / "desktop" / "contracts"


def _schema(name: str) -> dict[str, Any]:
    return json.loads((_CONTRACTS / f"{name}.schema.json").read_text())


def _show(book: dict[str, Any]) -> dict[str, Any]:
    result = runner.invoke(app, ["audio-report", "show", str(book["manifest"]), "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _dismiss(book: dict[str, Any], *args: str) -> Any:
    return runner.invoke(app, ["audio-report", "dismiss", str(book["manifest"]), *args, "--json"])


def _flagged(book: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeBackend]:
    inserted = _scripts(book, insert_into=2)
    backends = {m: FakeBackend(m, inserted) for m in ("whisper", "wav2vec2", "vosk")}
    _use(monkeypatch, backends)
    assert _verify(book, "--json").exit_code == 0
    return backends


def test_an_unverified_book_shows_no_report(book: dict[str, Any]) -> None:
    payload = _show(book)
    jsonschema.validate(payload, _schema("audio-report"))
    assert payload["report"] is None and payload["stale"] == []


def test_show_follows_the_contracts_and_loads_no_model(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    backends = _flagged(book, monkeypatch)
    heard = [list(b.heard) for b in backends.values()]
    payload = _show(book)
    jsonschema.validate(payload, _schema("audio-report"))
    jsonschema.validate(payload["report"], _schema("audio-verification"))
    assert [list(b.heard) for b in backends.values()] == heard
    assert payload["stale"] == []
    chapter = next(c for c in payload["report"]["chapters"] if c["number"] == 2)
    assert chapter["status"] == "possible_mismatch"


def test_show_imports_no_asr_library(book: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    import sys

    _flagged(book, monkeypatch)
    code = f"""
import sys
from typer.testing import CliRunner
from pdf2audiobook.cli import app
result = CliRunner().invoke(app, ["audio-report", "show", {str(book["manifest"])!r}, "--json"])
assert result.exit_code == 0, result.output
print(sorted(m for m in ("torch", "whisper", "vosk", "transformers") if m in sys.modules))
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().splitlines()[-1] == "[]"


def test_show_names_stale_chapters(book: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    _flagged(book, monkeypatch)
    mp3 = next((book["workspace"] / "audio").glob("001 *.mp3"))
    mp3.write_bytes(mp3.read_bytes() + b"\0")
    assert _show(book)["stale"] == [1]


def test_dismissing_marks_one_flag_reviewed_and_changes_no_audio(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _flagged(book, monkeypatch)
    audio = {p.name: p.read_bytes() for p in (book["workspace"] / "audio").glob("*.mp3")}
    result = _dismiss(book, "--chapter", "2", "--flag", "0")
    assert result.exit_code == 0, result.output
    jsonschema.validate(json.loads(result.stdout), _schema("audio-dismiss"))
    assert json.loads(result.stdout)["reviewed"] is True
    chapter = next(c for c in _show(book)["report"]["chapters"] if c["number"] == 2)
    assert chapter["flags"][0]["reviewed"] is True
    assert {p.name: p.read_bytes() for p in (book["workspace"] / "audio").glob("*.mp3")} == audio
    assert _dismiss(book, "--chapter", "2", "--flag", "0", "--undo").exit_code == 0
    chapter = next(c for c in _show(book)["report"]["chapters"] if c["number"] == 2)
    assert chapter["flags"][0]["reviewed"] is False


def test_a_reviewed_flag_stays_reviewed_when_the_same_audio_is_verified_again(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _flagged(book, monkeypatch)
    assert _dismiss(book, "--chapter", "2", "--flag", "0").exit_code == 0
    assert _verify(book, "--chapter", "2", "--json").exit_code == 0
    chapter = next(c for c in _show(book)["report"]["chapters"] if c["number"] == 2)
    assert chapter["flags"][0]["reviewed"] is True


@pytest.mark.parametrize(
    "args", [["--chapter", "1", "--flag", "0"], ["--chapter", "2", "--flag", "9"]]
)
def test_dismissing_a_flag_that_does_not_exist_is_refused(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    _flagged(book, monkeypatch)
    result = _dismiss(book, *args)
    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["message"]


def test_dismissing_without_a_report_is_refused(book: dict[str, Any]) -> None:
    assert _dismiss(book, "--chapter", "1", "--flag", "0").exit_code == 2


def test_changed_pronunciations_are_not_compared_with_the_audio(
    book: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The audio was spoken with "lamp"; the configuration now says "lantern": the chapter's
    # narration is no longer what was spoken, so no model may listen to it (AVF1.02).
    config = tmp_path / "changed.toml"
    config.write_text('[tts.pronunciations]\n"lamp" = "lantern"\n', encoding="utf-8")
    backends = {m: FakeBackend(m, _scripts(book)) for m in ("whisper", "wav2vec2", "vosk")}
    _use(monkeypatch, backends)
    result = _verify(book, "--config", str(config), "--json")
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    second = next(c for c in report["chapters"] if c["number"] == 2)
    assert (second["status"], second["reason"]) == (
        "verification_unavailable",
        "narration_not_spoken",
    )
    assert all(2 not in b.heard for b in backends.values())
    # Chapter 1 is unchanged and still verified normally.
    first = next(c for c in report["chapters"] if c["number"] == 1)
    assert first["status"] == "no_mismatch_detected"
    # The check says why, in the human output too.
    text = _verify(book, "--config", str(config)).output
    assert "narration not spoken" in text
    # With the original settings the spoken narration matches again and it verifies normally.
    _use(monkeypatch, {m: FakeBackend(m, _scripts(book)) for m in ("whisper", "wav2vec2", "vosk")})
    again = json.loads(_verify(book, "--json").stdout)
    assert (
        next(c for c in again["chapters"] if c["number"] == 2)["status"] == "no_mismatch_detected"
    )
