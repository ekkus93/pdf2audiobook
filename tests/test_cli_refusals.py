"""CLI refusals and failure paths (coverage round 3, TC4 / R5).

Each test reaches one uncovered branch of the command and checks the exit code, the fixed
wording, and that no path or book text appears in the output. Helpers that a command imports
inside its body are replaced with stand-ins, the same way the existing CLI tests do it.
"""

from __future__ import annotations

import json
import re
import types
from pathlib import Path
from typing import Any

import fitz
import pytest
import typer
from typer.testing import CliRunner

from pdf2audiobook.cli import app

runner = CliRunner()
MARKER = "PRIVATE-PATH-MARKER-4471"


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _output(result: Any) -> str:
    # Colour codes are stripped: CI forces colour, and they split words the tests look for.
    return _ANSI.sub("", result.output + getattr(result, "stderr", ""))


def _interrupt_error(result: Any) -> str:
    """The error type of a JSON-mode command's final stderr line."""
    return json.loads(result.stderr.strip().splitlines()[-1])["error"]["type"]


def _stopped(result: Any) -> dict[str, Any]:
    """The error object of a JSON-mode command's final stderr line."""
    return json.loads(result.stderr.strip().splitlines()[-1])["error"]


def _stopped_message(code: int) -> dict[str, Any]:
    return {
        "type": "Stopped",
        "code": code,
        "message": f"The command stopped with exit code {code}.",
    }


def _pdf(path: Path, pages: int = 1) -> Path:
    document = fitz.open()
    for index in range(pages):
        page = document.new_page()
        page.insert_text((80, 60), f"Chapter {index + 1}")
        page.insert_text((80, 115), f"Sentence {index + 1} of the book.")
    document.save(path)
    document.close()
    return path


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config"))


# --- TC4.01: asr ---------------------------------------------------------------------------


def test_asr_list_interrupted_exits_130_with_a_json_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted() -> dict:
        raise KeyboardInterrupt

    monkeypatch.setattr("pdf2audiobook.verification.models.list_payload", interrupted)
    result = runner.invoke(app, ["asr", "list", "--json"])

    assert result.exit_code == 130
    assert json.loads(result.stderr.strip().splitlines()[-1])["error"]["type"] == "Interrupted"


def test_asr_list_failure_names_no_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> dict:
        raise RuntimeError(f"cannot read {tmp_path / MARKER}")

    monkeypatch.setattr("pdf2audiobook.verification.models.list_payload", broken)
    result = runner.invoke(app, ["asr", "list", "--json"])

    assert result.exit_code != 0
    assert MARKER not in _output(result)
    assert str(tmp_path) not in _output(result)


def test_asr_fetch_prints_the_list_when_nothing_needs_downloading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pdf2audiobook.verification.models.resolve_names", lambda names: ["whisper"]
    )
    monkeypatch.setattr(
        "pdf2audiobook.verification.models.fetch_plan", lambda names: [("whisper", [])]
    )
    monkeypatch.setattr(
        "pdf2audiobook.verification.models.list_payload",
        lambda: {"models": [{"model": "whisper", "ready": True}]},
    )
    monkeypatch.setattr(
        "pdf2audiobook.verification.models.list_text", lambda payload: "whisper: ready"
    )
    result = runner.invoke(app, ["asr", "fetch", "whisper"])

    assert result.exit_code == 0
    assert "whisper: ready" in result.output


def test_asr_fetch_interrupted_exits_130(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pdf2audiobook.verification.models.resolve_names", lambda names: ["whisper"]
    )

    def interrupted(names: list[str]) -> list:
        raise KeyboardInterrupt

    monkeypatch.setattr("pdf2audiobook.verification.models.fetch_plan", interrupted)
    result = runner.invoke(app, ["asr", "fetch", "whisper", "--json"])

    assert result.exit_code == 130
    assert _interrupt_error(result) == "Interrupted"


# --- TC4.02: regenerate-chapter and recover ----------------------------------------------


def _manifest(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    return manifest


def test_regenerate_chapter_refuses_an_unknown_footnote_policy(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "book")
    result = runner.invoke(
        app,
        ["regenerate-chapter", str(manifest), "--chapter", "1", "--footnotes", "bogus", "--json"],
    )

    assert result.exit_code == 2
    assert "--footnotes must be warn, inline, end or omit" in _output(result)


def test_regenerate_chapter_lists_its_backups_in_the_human_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path / "book")
    result_value = types.SimpleNamespace(
        regenerated=["001"], backed_up=["001.txt"], backup_files=["001.txt.bak"]
    )
    monkeypatch.setattr(
        "pdf2audiobook.chapter_recovery.regenerate_chapters", lambda *a, **k: result_value
    )
    result = runner.invoke(app, ["regenerate-chapter", str(manifest), "--chapter", "1"])

    assert result.exit_code == 0
    assert "001.txt.bak" in _output(result)


@pytest.mark.parametrize(
    ("raised", "expected_exit"),
    [(KeyboardInterrupt(), 130), (typer.Exit(3), 3)],
)
def test_regenerate_chapter_passes_interrupts_and_exits_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raised: BaseException, expected_exit: int
) -> None:
    manifest = _manifest(tmp_path / "book")

    def stop(*args: Any, **kwargs: Any) -> None:
        raise raised

    monkeypatch.setattr("pdf2audiobook.chapter_recovery.regenerate_chapters", stop)
    result = runner.invoke(app, ["regenerate-chapter", str(manifest), "--chapter", "1", "--json"])

    assert result.exit_code == expected_exit
    if expected_exit == 130:
        assert _interrupt_error(result) == "Interrupted"
    else:
        assert _stopped(result) == _stopped_message(expected_exit)
        assert str(tmp_path) not in _output(result)


def test_recover_lists_its_backups_in_the_human_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path / "book")
    report = types.SimpleNamespace(
        status="recovered", backed_up=["x.json"], backup_files=["x.json.bak"]
    )
    monkeypatch.setattr(
        "pdf2audiobook.review_transaction.recover_review_transaction", lambda *a, **k: report
    )
    result = runner.invoke(app, ["recover", str(manifest)])

    assert result.exit_code == 0
    assert "x.json.bak" in _output(result)


@pytest.mark.parametrize(
    ("raised", "expected_exit"),
    [(KeyboardInterrupt(), 130), (typer.Exit(4), 4)],
)
def test_recover_passes_interrupts_and_exits_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raised: BaseException, expected_exit: int
) -> None:
    manifest = _manifest(tmp_path / "book")

    def stop(*args: Any, **kwargs: Any) -> None:
        raise raised

    monkeypatch.setattr("pdf2audiobook.review_transaction.recover_review_transaction", stop)
    result = runner.invoke(app, ["recover", str(manifest), "--json"])

    assert result.exit_code == expected_exit
    if expected_exit == 130:
        assert _interrupt_error(result) == "Interrupted"
    else:
        assert _stopped(result) == _stopped_message(expected_exit)
        assert str(tmp_path) not in _output(result)


# --- TC4.03: batch -----------------------------------------------------------------------


def test_batch_refuses_a_source_that_is_not_a_folder(tmp_path: Path) -> None:
    not_a_folder = _pdf(tmp_path / "single.pdf")
    result = runner.invoke(app, ["batch", str(not_a_folder), "--no-config", "--json"])

    assert result.exit_code != 0
    assert "batch source must be a directory" in _output(result)
    assert str(tmp_path) not in _output(result)


def test_batch_refuses_a_folder_without_pdfs(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["batch", str(empty), "--no-config", "--json"])

    assert result.exit_code != 0
    assert "batch source directory contains no PDF files" in _output(result)


def test_batch_applies_the_provider_and_cover_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    books = tmp_path / "books"
    books.mkdir()
    _pdf(books / "one.pdf")
    cover = tmp_path / "cover.png"
    fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False).save(cover)
    seen: list[Any] = []

    def record(source: Path, settings: Any) -> list:
        seen.append(settings)
        return []

    monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", record)
    result = runner.invoke(
        app,
        [
            "batch",
            str(books),
            "--tts-provider",
            "kitten",
            "--cover",
            str(cover),
            "--no-config",
            "--json",
        ],
    )

    assert result.exit_code == 0, _output(result)
    assert seen and str(cover) in str(seen[0].audio.cover_image)


def test_batch_refuses_per_book_tts_settings_that_do_not_validate(tmp_path: Path) -> None:
    books = tmp_path / "books"
    books.mkdir()
    _pdf(books / "one.pdf")
    result = runner.invoke(
        app,
        [
            "batch",
            str(books),
            "--tts-provider",
            "piper",
            "--voice",
            "not-a-number",
            "--no-config",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "Invalid per-book TTS settings for batch conversion" in _output(result)


def test_batch_interrupted_while_converting_exits_130(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    books = tmp_path / "books"
    books.mkdir()
    _pdf(books / "one.pdf")

    def interrupted(source: Path, settings: Any) -> list:
        raise KeyboardInterrupt

    monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", interrupted)
    result = runner.invoke(app, ["batch", str(books), "--no-config", "--json"])

    assert result.exit_code == 130
    assert _interrupt_error(result) == "Interrupted"


def test_batch_interrupted_before_any_book_exits_130(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    books = tmp_path / "books"
    books.mkdir()
    _pdf(books / "one.pdf")

    def interrupted(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("pdf2audiobook.cli.batch.load_settings", interrupted)
    result = runner.invoke(app, ["batch", str(books), "--no-config", "--json"])

    assert result.exit_code == 130
    assert _interrupt_error(result) == "Interrupted"


def test_batch_records_an_os_failure_as_a_failed_book(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    books = tmp_path / "books"
    books.mkdir()
    _pdf(books / "one.pdf")

    def unwritable(source: Path, settings: Any) -> list:
        raise OSError(f"cannot write {tmp_path / MARKER}")

    monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", unwritable)
    result = runner.invoke(app, ["batch", str(books), "--no-config", "--json"])

    assert result.exit_code != 0
    assert MARKER not in _output(result)
    assert str(tmp_path) not in _output(result)


# --- TC4.04: verify-audio, audio-report and the verify hooks ------------------------------


def _stub_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pdf2audiobook.workspace.read_manifest", lambda path: types.SimpleNamespace(chapters=[])
    )
    monkeypatch.setattr(
        "pdf2audiobook.verification.run.select_chapters", lambda manifest, *a, **k: []
    )


def test_verify_audio_interrupted_exits_130(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path / "book")
    _stub_manifest(monkeypatch)
    monkeypatch.setattr(
        "pdf2audiobook.verification.run.verify_book",
        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    result = runner.invoke(app, ["verify-audio", str(manifest), "--json"])

    assert result.exit_code == 130
    assert _interrupt_error(result) == "Interrupted"


def test_verify_audio_passes_an_exit_code_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path / "book")
    _stub_manifest(monkeypatch)

    def stop(*args: Any, **kwargs: Any) -> None:
        raise typer.Exit(4)

    monkeypatch.setattr("pdf2audiobook.verification.run.verify_book", stop)
    result = runner.invoke(app, ["verify-audio", str(manifest), "--json"])

    assert result.exit_code == 4
    assert _stopped(result) == _stopped_message(4)
    assert str(tmp_path) not in _output(result)


def test_a_passthrough_exit_prints_the_fixed_message_in_human_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path / "book")
    _stub_manifest(monkeypatch)

    def stop(*args: Any, **kwargs: Any) -> None:
        raise typer.Exit(4)

    monkeypatch.setattr("pdf2audiobook.verification.run.verify_book", stop)
    result = runner.invoke(app, ["verify-audio", str(manifest)])

    assert result.exit_code == 4
    assert "The command stopped with exit code 4." in _output(result)
    assert str(tmp_path) not in _output(result)


def test_audio_report_says_when_a_book_is_not_verified_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path / "book")
    monkeypatch.setattr(
        "pdf2audiobook.workspace.read_manifest", lambda path: types.SimpleNamespace(chapters=[])
    )
    result = runner.invoke(app, ["audio-report", "show", str(manifest)])

    assert result.exit_code == 0
    assert "This book has not been verified yet." in _output(result)


def test_audio_report_shows_its_out_of_date_chapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path / "book")
    report_dir = tmp_path / "book" / "reports"
    report_dir.mkdir()
    report = {
        "schema_version": 1,
        "chapters": [
            {
                "number": 1,
                "status": "no_mismatch_detected",
                "reason": None,
                "partial": False,
                "models": [],
                "flags": [],
                "audio_sha256": "not-the-real-hash",
            }
        ],
        "models": [],
        "warnings": [],
    }
    (report_dir / "audio_verification.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        "pdf2audiobook.workspace.read_manifest",
        lambda path: types.SimpleNamespace(chapters=[types.SimpleNamespace(number=1)]),
    )
    monkeypatch.setattr("pdf2audiobook.verification.run.stale_chapters", lambda *a, **k: {1})
    result = runner.invoke(app, ["audio-report", "show", str(manifest)])

    assert result.exit_code == 0, _output(result)
    assert "Out of date (verify again): chapter(s) 1" in _output(result)


def test_audio_report_dismiss_confirms_in_the_human_output(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "book")
    report_dir = tmp_path / "book" / "reports"
    report_dir.mkdir()
    report = {"schema_version": 1, "chapters": [{"number": 1, "flags": [{"reviewed": False}]}]}
    (report_dir / "audio_verification.json").write_text(json.dumps(report), encoding="utf-8")
    result = runner.invoke(
        app, ["audio-report", "dismiss", str(manifest), "--chapter", "1", "--flag", "0"]
    )

    assert result.exit_code == 0, _output(result)
    assert "Marked reviewed." in _output(result)


def test_audio_report_dismiss_passes_an_exit_code_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path / "book")

    def stop(*args: Any, **kwargs: Any) -> None:
        raise typer.Exit(5)

    monkeypatch.setattr("pdf2audiobook.verification.run.mark_reviewed", stop)
    result = runner.invoke(
        app, ["audio-report", "dismiss", str(manifest), "--chapter", "1", "--flag", "0", "--json"]
    )

    assert result.exit_code == 5
    assert _stopped(result) == _stopped_message(5)
    assert str(tmp_path) not in _output(result)


def test_the_convert_verify_hook_does_nothing_without_outputs() -> None:
    from pdf2audiobook.cli.verify import _verify_after_convert

    settings = types.SimpleNamespace()
    assert _verify_after_convert([], settings, False) is None  # type: ignore[arg-type]


def _resynthesize_stubs(monkeypatch: pytest.MonkeyPatch, chapter_voice: str | None) -> None:
    monkeypatch.setattr(
        "pdf2audiobook.cli.verify._manifest_chapters",
        lambda path: [types.SimpleNamespace(number=1, voice_id=chapter_voice)],
    )
    monkeypatch.setattr("pdf2audiobook.pipeline.resynthesize_chapters", lambda *a, **k: [])


def test_resynthesize_warns_when_a_chapter_voice_overrides_the_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path / "book")
    _resynthesize_stubs(monkeypatch, chapter_voice="7")
    result = runner.invoke(
        app,
        [
            "resynthesize",
            str(manifest),
            "--chapter",
            "1",
            "--voice",
            "3",
            "--no-verify-audio",
            "--json",
        ],
    )

    assert result.exit_code == 0, _output(result)
    assert "chapter_voice_overrides_option" in result.stdout


def test_resynthesize_prints_the_verification_summary_in_the_human_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path / "book")
    _resynthesize_stubs(monkeypatch, chapter_voice=None)
    monkeypatch.setattr(
        "pdf2audiobook.cli.verify._verify_after_convert",
        lambda outputs, settings, json_output: (
            {"report": "r", "chapters": []},
            [],
            "VERIFICATION SUMMARY",
        ),
    )
    result = runner.invoke(app, ["resynthesize", str(manifest), "--chapter", "1", "--verify-audio"])

    assert result.exit_code == 0, _output(result)
    assert "VERIFICATION SUMMARY" in _output(result)


@pytest.mark.parametrize(
    ("raised", "expected_exit"),
    [(KeyboardInterrupt(), 130), (typer.Exit(6), 6)],
)
def test_resynthesize_passes_interrupts_and_exits_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raised: BaseException, expected_exit: int
) -> None:
    manifest = _manifest(tmp_path / "book")
    _resynthesize_stubs(monkeypatch, chapter_voice=None)

    def stop(*args: Any, **kwargs: Any) -> None:
        raise raised

    monkeypatch.setattr("pdf2audiobook.pipeline.resynthesize_chapters", stop)
    result = runner.invoke(
        app, ["resynthesize", str(manifest), "--chapter", "1", "--no-verify-audio", "--json"]
    )

    assert result.exit_code == expected_exit
    if expected_exit == 130:
        assert _interrupt_error(result) == "Interrupted"
    else:
        assert _stopped(result) == _stopped_message(expected_exit)
        assert str(tmp_path) not in _output(result)


def test_audio_report_show_passes_an_exit_code_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path / "book")
    monkeypatch.setattr(
        "pdf2audiobook.workspace.read_manifest", lambda path: types.SimpleNamespace(chapters=[])
    )

    def stop(*args: Any, **kwargs: Any) -> None:
        raise typer.Exit(7)

    monkeypatch.setattr("pdf2audiobook.verification.run.saved_report", stop)
    result = runner.invoke(app, ["audio-report", "show", str(manifest), "--json"])

    assert result.exit_code == 7
    assert _stopped(result) == _stopped_message(7)
    assert str(tmp_path) not in _output(result)


def test_audio_report_show_failure_names_no_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path / "book")
    monkeypatch.setattr(
        "pdf2audiobook.workspace.read_manifest", lambda path: types.SimpleNamespace(chapters=[])
    )

    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"cannot read {tmp_path / MARKER}")

    monkeypatch.setattr("pdf2audiobook.verification.run.saved_report", broken)
    result = runner.invoke(app, ["audio-report", "show", str(manifest), "--json"])

    assert result.exit_code != 0
    assert MARKER not in _output(result)
    assert str(tmp_path) not in _output(result)


def test_asr_fetch_refuses_an_unknown_model_name() -> None:
    result = runner.invoke(app, ["asr", "fetch", "no-such-model", "--json"])

    assert result.exit_code != 0
    assert "no-such-model" not in _output(result)  # the refusal names the options, not the input


def test_asr_fetch_declined_download_exits_1_and_downloads_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pdf2audiobook.verification.models.resolve_names", lambda names: ["whisper"]
    )
    monkeypatch.setattr(
        "pdf2audiobook.verification.models.fetch_plan",
        lambda names: [("whisper", [types.SimpleNamespace(name="weights.pt")])],
    )
    monkeypatch.setattr(
        "pdf2audiobook.verification.models.plan_text", lambda plan: "whisper: weights.pt"
    )
    fetched: list[str] = []
    monkeypatch.setattr(
        "pdf2audiobook.verification.models.fetch", lambda *a, **k: fetched.append("x")
    )
    result = runner.invoke(app, ["asr", "fetch", "whisper"], input="n\n")

    assert result.exit_code == 1
    assert fetched == []


def test_regenerate_chapter_refuses_a_missing_manifest(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "regenerate-chapter",
            str(tmp_path / "missing" / "manifest.json"),
            "--chapter",
            "1",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert str(tmp_path) not in _output(result)


def test_batch_reports_a_failed_book_and_still_converts_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    books = tmp_path / "books"
    books.mkdir()
    _pdf(books / "a-first.pdf")
    _pdf(books / "b-second.pdf")
    attempted: list[str] = []

    def fail_first(source: Path, settings: Any) -> list:
        attempted.append(source.name)
        if source.name == "a-first.pdf":
            raise OSError(f"cannot write {tmp_path / MARKER}")
        return []

    monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", fail_first)
    result = runner.invoke(app, ["batch", str(books), "--no-config", "--json"])

    assert attempted == ["a-first.pdf", "b-second.pdf"]  # the run did not stop at the failure
    assert result.exit_code != 0
    assert MARKER not in _output(result)


def test_recover_refuses_a_missing_manifest(tmp_path: Path) -> None:
    result = runner.invoke(app, ["recover", str(tmp_path / "missing" / "manifest.json"), "--json"])

    assert result.exit_code != 0
    assert str(tmp_path) not in _output(result)
