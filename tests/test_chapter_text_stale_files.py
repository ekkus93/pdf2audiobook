"""Re-planning with fewer chapters must not leave stale derived chapter text."""

from pdf2audiobook.document import structure
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock


def _manifest(count: int) -> BookManifest:
    blocks = [
        DocumentBlock(id=f"b{n}", page_index=n, text=f"Synthetic prose {n}.", kind="paragraph")
        for n in range(count)
    ]
    chapters = [
        Chapter(
            id=f"c{n}",
            number=n + 1,
            title=f"Chapter {n + 1}",
            start_block=n,
            end_block=n + 1,
            confidence=1.0,
        )
        for n in range(count)
    ]
    return BookManifest(
        input_sha256="synthetic",
        title="Synthetic",
        source_path="synthetic.pdf",
        blocks=blocks,
        chapters=chapters,
    )


def test_fewer_chapters_remove_stale_derived_text_only(tmp_path):
    folder = tmp_path / "chapters"
    structure.render_chapter_texts(_manifest(5), tmp_path)
    assert sorted(p.name for p in folder.iterdir()) == [f"00{n}.txt" for n in range(1, 6)]
    (folder / "notes.txt").write_text("user notes", encoding="utf-8")
    (folder / "002-draft.txt").write_text("user draft", encoding="utf-8")

    structure.render_chapter_texts(_manifest(3), tmp_path)

    assert sorted(p.name for p in folder.iterdir()) == [
        "001.txt",
        "002-draft.txt",
        "002.txt",
        "003.txt",
        "notes.txt",
    ]
