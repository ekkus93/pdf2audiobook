"""Review-only LLM classification with independent task switches."""

import json

import fitz

from pdf2audiobook.config import LLM, Chapters, General, Pdf, Settings
from pdf2audiobook.llm import propose_llm_classification
from pdf2audiobook.models import DocumentBlock
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest


class Stub:
    calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def complete_json(self, *, instructions, document_text):
        Stub.calls += 1
        first_id = json.loads(document_text)[0]["id"]
        return {"labels": [
            {"block_id": first_id, "category": "running_header",
             "confidence": 0.95, "reason": "repeated margin text"},
        ]}


def test_source_anchored_classifications_preserve_all_source_text():
    items = [DocumentBlock(id="b1", page_index=0, text="Header"),
             DocumentBlock(id="b2", page_index=0, text="Normal paragraph text.")]
    labels, warnings = propose_llm_classification(items, Stub())
    assert not warnings and len(labels) == 1
    assert labels[0].block_id == "b1"
    assert [block.text for block in items] == ["Header", "Normal paragraph text."]


def test_invalid_and_unknown_ids_fail_closed():
    class Invalid:
        def complete_json(self, *, instructions, document_text):
            return {"labels": [
                {"block_id": "invented", "category": "page_number",
                 "confidence": 0.99, "reason": "not present"},
                {"block_id": "b1", "category": "nonsense",
                 "confidence": 1, "reason": "unsupported"},
            ]}

    labels, warnings = propose_llm_classification(
        [DocumentBlock(id="b1", page_index=0, text="Source")], Invalid()
    )
    assert not labels and warnings


def test_classification_only_writes_advisory_report(tmp_path, monkeypatch):
    import pdf2audiobook.pipeline as pipeline

    monkeypatch.setattr(pipeline, "create_provider", lambda _: Stub())
    Stub.calls = 0
    pdf_path = tmp_path / "sample.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (70, 90), "This is the first paragraph of a synthetic example.", fontsize=11
    )
    document.save(pdf_path)
    document.close()
    settings = Settings(
        general=General(output_dir=str(tmp_path / "out")),
        pdf=Pdf(ocr="never"),
        chapters=Chapters(allow_single_chapter=True),
        llm=LLM(enabled=True, structure=False, cleanup=False,
                classification=True, narration=False),
    )
    manifest_path = analyze_book(pdf_path, settings)
    manifest = read_manifest(manifest_path)
    report = json.loads(
        (manifest_path.parent / "reports" / "classification_suggestions.json").read_text()
    )
    assert Stub.calls == 1
    assert report["requires_manual_review"] is True
    assert report["labels"][0]["category"] == "running_header"
    assert manifest.edits == []
    assert manifest.blocks[0].text.startswith("This is the first paragraph")
