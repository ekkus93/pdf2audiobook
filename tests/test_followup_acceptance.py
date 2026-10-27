"""End-to-end acceptance cases for edited narration, legacy workspaces and recovery (R8)."""

import json
from pathlib import Path

import fitz
import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook import review_transaction
from pdf2audiobook.chapter_artifacts import STATE_NAME, load_artifact_state
from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.errors import ChapterConflictError
from pdf2audiobook.pipeline import analyze_book, convert_book
from pdf2audiobook.review_transaction import JOURNAL, ReviewRecoveryRequired
from pdf2audiobook.review_ui import save_chapter_updates
from pdf2audiobook.workspace import read_manifest, write_manifest

EDITED = "Corrected narration.\n\n[[voice:Bella]]\n\nSpoken dialogue.\n"
ORIGINAL = "Original narration."


class _Provider:
    sample_rate = 24000
    max_chars_per_chunk = 350

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def list_voices(self) -> list[str]:
        return ["Jasper", "Bella"]

    def generate(self, text: str, *, voice: str, speed: float) -> np.ndarray:
        self.calls.append((text, voice))
        return np.ones(240, dtype=np.float32) * 0.1


def _encode(_samples, _rate, target: Path, **_kwargs) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"synthetic audio")


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.general.output_dir = str(tmp_path / "out")
    settings.llm.enabled = False
    settings.pdf.ocr = "never"
    return settings


def _book(tmp_path: Path) -> tuple[Path, Settings, Path]:
    source = tmp_path / "book.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 1")
    page.insert_text((72, 120), ORIGINAL)
    doc.save(source)
    doc.close()
    settings = _settings(tmp_path)
    manifest_path = analyze_book(source, settings)
    manifest = read_manifest(manifest_path)
    manifest.chapters[0].manually_approved = True
    write_manifest(manifest_path, manifest)
    return source, settings, manifest_path


def _dry_run(source: Path, tmp_path: Path) -> tuple[int, dict, str]:
    result = CliRunner().invoke(
        app,
        [
            "convert",
            str(source),
            "--dry-run",
            "--json",
            "--no-config",
            "--no-llm",
            "--ocr",
            "never",
            "--output",
            str(tmp_path / "out"),
        ],
    )
    payload = json.loads(result.stdout) if result.stdout.strip() else {}
    return result.exit_code, payload, result.stderr


def _artifacts(folder: Path) -> list[str]:
    return sorted(
        str(item.relative_to(folder))
        for item in folder.rglob("*")
        if item.suffix in {".mp3", ".wav"} or item.name.endswith(".cache.json")
    )


def test_dry_run_plans_from_the_edited_text_and_writes_no_audio(tmp_path: Path) -> None:
    source, _, manifest_path = _book(tmp_path)
    chapter = manifest_path.parent / "chapters" / "001.txt"
    chapter.write_text(EDITED, encoding="utf-8")
    code, payload, err = _dry_run(source, tmp_path)
    assert code == 0, err
    assert payload["dry_run"] is True and payload["chapters"] == 1
    assert payload["skipped_chapters"] == []
    assert chapter.read_text(encoding="utf-8") == EDITED
    assert _artifacts(manifest_path.parent) == []


def test_dry_run_skips_a_chapter_whose_edited_text_is_not_speakable(tmp_path: Path) -> None:
    source, _, manifest_path = _book(tmp_path)
    chapter = manifest_path.parent / "chapters" / "001.txt"
    chapter.write_text("[[voice:Bella]]\n", encoding="utf-8")
    code, payload, err = _dry_run(source, tmp_path)
    assert code == 0, err
    assert payload["chapters"] == 0 and payload["skipped_chapters"] == [1]
    assert chapter.read_text(encoding="utf-8") == "[[voice:Bella]]\n"
    assert _artifacts(manifest_path.parent) == []


def test_legacy_workspace_adopts_a_matching_file_through_the_whole_workflow(
    tmp_path: Path,
) -> None:
    source, settings, manifest_path = _book(tmp_path)
    folder = manifest_path.parent
    chapter = folder / "chapters" / "001.txt"
    generated = chapter.read_bytes()
    (folder / STATE_NAME).unlink()  # a workspace written before artifacts were tracked
    analyze_book(source, settings)
    assert chapter.read_bytes() == generated
    state = load_artifact_state(folder)
    assert state is not None and state["chapters"][next(iter(state["chapters"]))]["edited"] is False
    manifest = read_manifest(manifest_path)
    updates = [
        {
            "id": item.id,
            "title": "Renamed",
            "start_block": item.start_block,
            "end_block": item.end_block,
        }
        for item in manifest.chapters
    ]
    save_chapter_updates(manifest_path, updates)
    assert chapter.read_bytes() == generated
    provider = _Provider()
    convert_book(source, settings, tts_provider=provider, encoder=_encode)
    assert any(ORIGINAL in text for text, _ in provider.calls)


def test_legacy_workspace_preserves_a_differing_file_until_it_is_regenerated(
    tmp_path: Path,
) -> None:
    source, settings, manifest_path = _book(tmp_path)
    folder = manifest_path.parent
    chapter = folder / "chapters" / "001.txt"
    chapter.write_text(EDITED, encoding="utf-8")
    (folder / STATE_NAME).unlink()
    with pytest.raises(ChapterConflictError):
        analyze_book(source, settings)
    assert chapter.read_text(encoding="utf-8") == EDITED
    result = CliRunner().invoke(
        app, ["regenerate-chapter", str(manifest_path), "--chapter", "1", "--json"]
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["backed_up"] == [1]
    backups = list((folder / "chapter-backups").iterdir())
    assert [item.read_text(encoding="utf-8") for item in backups] == [EDITED]
    provider = _Provider()
    convert_book(source, settings, tts_provider=provider, encoder=_encode)
    assert any(ORIGINAL in text for text, _ in provider.calls)
    assert all("Spoken dialogue" not in text for text, _ in provider.calls)


def test_conversion_recovers_a_committed_review_before_selecting_chapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, settings, manifest_path = _book(tmp_path)
    folder = manifest_path.parent
    manifest = read_manifest(manifest_path)
    updates = [
        {
            "id": item.id,
            "title": item.title,
            "start_block": item.start_block,
            "end_block": item.end_block,
            "voice_id": "Bella",
        }
        for item in manifest.chapters
    ]
    original = review_transaction.atomic_write

    def fail_manifest(target: Path, data: bytes) -> None:
        if target == manifest_path:
            raise OSError("failure")
        original(target, data)

    with monkeypatch.context() as patch:
        patch.setattr(review_transaction, "atomic_write", fail_manifest)
        with pytest.raises(ReviewRecoveryRequired):
            save_chapter_updates(manifest_path, updates)
    assert (folder / JOURNAL).exists()
    published = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert published["chapters"][0].get("voice_id") != "Bella"  # committed, not yet published
    provider = _Provider()
    convert_book(source, settings, tts_provider=provider, encoder=_encode)
    assert not (folder / JOURNAL).exists()
    assert provider.calls and all(voice == "Bella" for _, voice in provider.calls)
