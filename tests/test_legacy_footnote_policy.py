"""Workspaces without a recorded footnote policy resolve it safely (R6)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf2audiobook.chapter_artifacts import STATE_NAME, load_artifact_state
from pdf2audiobook.cli import app
from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import footnote_omit_edits, render_chapter_texts
from pdf2audiobook.errors import FootnotePolicyUnknownError
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.pipeline import prepare_chapter_selection
from pdf2audiobook.review_ui import save_chapter_updates
from pdf2audiobook.workspace import write_manifest

EDIT = "PrivateHandEdit"


def _manifest(policy: str, *, footnote: bool = True) -> BookManifest:
    blocks = [
        DocumentBlock(id="a", page_index=0, text="A sentence.1", kind="paragraph"),
        DocumentBlock(id="b", page_index=0, text="Another paragraph.", kind="paragraph"),
        DocumentBlock(id="c", page_index=0, text="Last paragraph.", kind="paragraph"),
    ]
    if footnote:
        blocks.insert(2, DocumentBlock(id="n", page_index=0, text="1 Footnote.", kind="footnote"))
    blocks.append(DocumentBlock(id="d", page_index=1, text="Closing paragraph.", kind="paragraph"))
    return BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source",
        blocks=blocks,
        edits=footnote_omit_edits(blocks) if policy == "omit" and footnote else [],
        chapters=[
            Chapter(
                id="c1",
                number=1,
                title="One",
                start_block=0,
                end_block=len(blocks) - 1,
                confidence=1,
            ),
            Chapter(
                id="c2",
                number=2,
                title="Two",
                start_block=len(blocks) - 1,
                end_block=len(blocks),
                confidence=1,
            ),
        ],
    )


def _legacy(tmp_path: Path, policy: str, *, footnote: bool = True) -> tuple[Path, BookManifest]:
    manifest = _manifest(policy, footnote=footnote)
    path = tmp_path / "manifest.json"
    write_manifest(path, manifest)
    render_chapter_texts(manifest, tmp_path, policy)
    (tmp_path / STATE_NAME).unlink()  # a workspace written before policies were recorded
    return path, manifest


def _updates(manifest: BookManifest) -> list[dict[str, object]]:
    return [
        {
            "id": chapter.id,
            "title": chapter.title,
            "start_block": chapter.start_block,
            "end_block": chapter.end_block,
        }
        for chapter in manifest.chapters
    ]


def _files(folder: Path) -> dict[str, bytes]:
    return {
        str(item.relative_to(folder)): item.read_bytes()
        for item in sorted(folder.rglob("*"))
        if item.is_file() and item.name != ".convert.lock"
    }


@pytest.mark.parametrize("policy", ["warn", "inline", "end", "omit"])
def test_legacy_review_save_records_the_matching_policy(tmp_path: Path, policy: str) -> None:
    path, manifest = _legacy(tmp_path, policy)
    before = (tmp_path / "chapters" / "001.txt").read_bytes()
    save_chapter_updates(path, _updates(manifest))
    state = load_artifact_state(tmp_path)
    assert state is not None and state["footnotes"] == policy
    assert (tmp_path / "chapters" / "001.txt").read_bytes() == before


def test_footnote_free_legacy_workspace_adopts_warn(tmp_path: Path) -> None:
    path, manifest = _legacy(tmp_path, "inline", footnote=False)
    save_chapter_updates(path, _updates(manifest))
    state = load_artifact_state(tmp_path)
    assert state is not None and state["footnotes"] == "warn"


def test_ambiguous_legacy_workspace_is_refused_with_files_unchanged(tmp_path: Path) -> None:
    path, manifest = _legacy(tmp_path, "inline")
    (tmp_path / "chapters" / "001.txt").unlink()  # only the policy-neutral chapter remains
    before = _files(tmp_path)
    with pytest.raises(FootnotePolicyUnknownError) as raised:
        save_chapter_updates(path, _updates(manifest))
    assert "pdf.footnotes" in str(raised.value)
    assert EDIT not in str(raised.value) and str(tmp_path) not in str(raised.value)
    assert _files(tmp_path) == before


def test_edited_files_do_not_decide_the_policy(tmp_path: Path) -> None:
    path, manifest = _legacy(tmp_path, "end")
    (tmp_path / "chapters" / "001.txt").write_text(EDIT, encoding="utf-8")
    before = _files(tmp_path)
    with pytest.raises(FootnotePolicyUnknownError):
        save_chapter_updates(path, _updates(manifest))
    assert _files(tmp_path) == before


def test_edited_neutral_file_is_preserved_when_another_chapter_pins_the_policy(
    tmp_path: Path,
) -> None:
    from pdf2audiobook.chapter_artifacts import resolve_footnote_policy

    path, manifest = _legacy(tmp_path, "end")
    (tmp_path / "chapters" / "002.txt").write_text(EDIT, encoding="utf-8")
    before = _files(tmp_path)
    assert resolve_footnote_policy(manifest, tmp_path) == "end"
    assert _files(tmp_path) == before


def test_selection_resolves_the_legacy_policy_instead_of_using_settings(tmp_path: Path) -> None:
    path, manifest = _legacy(tmp_path, "inline")
    before = _files(tmp_path)
    prepare_chapter_selection(path, manifest, Settings())  # settings default to warn
    assert _files(tmp_path) == before


def test_regenerate_needs_an_explicit_policy_when_it_cannot_be_resolved(tmp_path: Path) -> None:
    path, manifest = _legacy(tmp_path, "inline")
    (tmp_path / "chapters" / "001.txt").write_text(EDIT, encoding="utf-8")
    runner = CliRunner()
    blocked = runner.invoke(app, ["regenerate-chapter", str(path), "--chapter", "1", "--json"])
    assert blocked.exit_code == 4 and "pdf.footnotes" in blocked.stderr
    assert (tmp_path / "chapters" / "001.txt").read_text() == EDIT
    done = runner.invoke(
        app,
        ["regenerate-chapter", str(path), "--chapter", "1", "--footnotes", "inline", "--json"],
    )
    assert done.exit_code == 0, done.stderr
    assert json.loads(done.stdout)["backed_up"] == [1]
    state = load_artifact_state(tmp_path)
    assert state is not None and state["footnotes"] == "inline"
    assert [item.read_text() for item in (tmp_path / "chapter-backups").iterdir()] == [EDIT]


def test_explicit_policy_cannot_contradict_a_recorded_one(tmp_path: Path) -> None:
    path, _ = _legacy(tmp_path, "inline")
    save_chapter_updates(path, _updates(_manifest("inline")))  # records inline
    result = CliRunner().invoke(
        app, ["regenerate-chapter", str(path), "--chapter", "1", "--footnotes", "end", "--json"]
    )
    assert result.exit_code == 4 and "already recorded" in result.stderr
