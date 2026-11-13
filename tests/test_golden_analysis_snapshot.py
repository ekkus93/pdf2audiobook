"""Characterization snapshot of `analyze` output (long function split spec S11).

The fixtures in tests/fixtures/golden/ are committed bytes, so the input hash and
every fingerprint derived from it are stable. The snapshot records a digest of each
workspace file and manifest section, plus a readable summary, so a mismatch names
exactly what changed. It was written once at the split baseline and must not be
updated while the long-function split is in progress.

To regenerate it outside that work, run with PDF2AUDIOBOOK_WRITE_GOLDEN=1.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from pdf2audiobook import pipeline
from pdf2audiobook.config import LLM, General, Pdf, Settings
from pdf2audiobook.errors import AudiobookError

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT = FIXTURES / "golden" / "analysis_snapshot.json"
BOOKS = {
    "golden_book.pdf": (FIXTURES / "golden" / "golden_book.pdf", "auto"),
    "novel.epub": (FIXTURES / "golden" / "novel.epub", "auto"),
    # OCR output depends on the Tesseract version, so this page is pinned on
    # its deterministic no-OCR path.
    "outlined_text.pdf": (FIXTURES / "outlined_text.pdf", "never"),
}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _analyze(name: str, tmp_path: Path) -> dict:
    source, ocr = BOOKS[name]
    out = tmp_path / name
    settings = Settings(
        general=General(output_dir=str(out)), llm=LLM(enabled=False), pdf=Pdf(ocr=ocr)
    )
    try:
        manifest_path = pipeline.analyze_book(source, settings)
    except AudiobookError as exc:
        return {"error": {"type": type(exc).__name__, "message": str(exc)}}
    workspace = manifest_path.parent
    placeholders = {str(source.resolve()): "<source>", str(source): "<source>"}
    placeholders[str(workspace)] = "<workspace>"

    def normalized(path: Path) -> bytes:
        text = path.read_bytes().decode("utf-8")
        for value, placeholder in sorted(placeholders.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(json.dumps(value)[1:-1], placeholder).replace(value, placeholder)
        return text.encode("utf-8")

    files = {
        path.relative_to(workspace).as_posix(): _digest(normalized(path))
        for path in sorted(workspace.rglob("*"))
        if path.is_file() and path.name != ".convert.lock"
    }
    manifest = json.loads(normalized(manifest_path))
    return {
        "files": files,
        "manifest_sections": {
            key: _digest(json.dumps(value, sort_keys=True).encode("utf-8"))
            for key, value in sorted(manifest.items())
        },
        "summary": {
            "chapters": [
                [c["number"], c["title"], c["start_block"], c["end_block"], c["confidence"]]
                for c in manifest["chapters"]
            ],
            "block_kinds": sorted({b["kind"] for b in manifest["blocks"]}),
            "edit_count": len(manifest["edits"]),
            "warnings": manifest["warnings"],
            "review_required": manifest["review_required"],
            "analysis_fingerprint": manifest["analysis_fingerprint"],
        },
    }


def test_analysis_output_matches_the_committed_snapshot(tmp_path):
    actual = {name: _analyze(name, tmp_path) for name in BOOKS}
    if os.environ.get("PDF2AUDIOBOOK_WRITE_GOLDEN") == "1":
        SNAPSHOT.write_text(json.dumps(actual, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("golden snapshot written")
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for name in BOOKS:
        assert actual[name].get("summary") == expected[name].get("summary"), name
        assert actual[name].get("error") == expected[name].get("error"), name
        assert actual[name].get("manifest_sections") == expected[name].get("manifest_sections"), (
            name
        )
        assert actual[name].get("files") == expected[name].get("files"), name
    assert actual == expected
