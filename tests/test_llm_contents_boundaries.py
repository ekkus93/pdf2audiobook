"""TOC entries and chapter boundaries require exact source anchors."""

import json

import fitz

from pdf2audiobook.config import LLM, Chapters, General, Pdf, Settings
from pdf2audiobook.llm import propose_llm_contents_boundaries
from pdf2audiobook.models import DocumentBlock
from pdf2audiobook.pipeline import analyze_book


class Stub:
    def __init__(self, response):
        self.response = response

    def complete_json(self, *, instructions, document_text):
        assert "untrusted data" in instructions
        return self.response


def source_blocks():
    return [
        DocumentBlock(id="contents", page_index=0, text="Contents"),
        DocumentBlock(id="entry", page_index=0, text="Chapter Two ........ 9"),
        DocumentBlock(id="body", page_index=2, text="Chapter Two"),
        DocumentBlock(id="paragraph", page_index=2, text="A real chapter starts here."),
    ]


def test_verified_contents_entry_maps_to_unique_later_heading():
    decisions = []
    ids, warnings = propose_llm_contents_boundaries(
        source_blocks(),
        Stub(
            {
                "entries": [
                    {
                        "block_id": "entry",
                        "title": "Chapter Two",
                        "page_reference": "9",
                        "confidence": 0.95,
                    }
                ],
                "boundaries": [],
            }
        ),
        decisions=decisions,
    )
    assert ids == {"body"}
    assert warnings == []
    assert decisions[0].task == "contents"
    assert decisions[0].status == "accepted"
    assert decisions[0].reason_code == "verified_contents_entry"
    assert decisions[0].source_sha256


def test_verified_boundary_candidates_are_weak_heading_evidence():
    decisions = []
    ids, warnings = propose_llm_contents_boundaries(
        source_blocks(),
        Stub(
            {
                "entries": [],
                "boundaries": [{"block_id": "body", "title": "Chapter Two", "confidence": 0.9}],
            }
        ),
        decisions=decisions,
    )
    assert ids == {"body"}
    assert warnings == []
    assert decisions[0].reason_code == "verified_boundary_candidate"


def test_unknown_ids_and_invented_text_are_rejected():
    decisions = []
    ids, warnings = propose_llm_contents_boundaries(
        source_blocks(),
        Stub(
            {
                "entries": [
                    {
                        "block_id": "PRIVATE_UNKNOWN_ID",
                        "title": "Chapter Two",
                        "page_reference": "9",
                        "confidence": 0.99,
                    },
                    {
                        "block_id": "entry",
                        "title": "Invented Title",
                        "page_reference": "9",
                        "confidence": 0.99,
                    },
                ],
                "boundaries": [
                    {"block_id": "body", "title": "Invented Title", "confidence": 0.99},
                    {
                        "block_id": "PRIVATE_MISSING_ID",
                        "title": "Missing",
                        "confidence": 0.99,
                    },
                ],
            }
        ),
        decisions=decisions,
    )
    assert ids == set()
    for private in ("Invented", "PRIVATE_UNKNOWN_ID", "PRIVATE_MISSING_ID"):
        assert all(private not in warning for warning in warnings)
    assert {decision.status for decision in decisions} == {"rejected"}
    assert {decision.reason_code for decision in decisions} == {
        "unknown_or_duplicate_contents_block",
        "contents_title_mismatch",
        "boundary_text_mismatch",
        "unknown_or_duplicate_boundary_block",
    }
    assert all("Invented" not in decision.model_dump_json() for decision in decisions)


def test_contents_task_runs_independently_and_writes_report(tmp_path, monkeypatch):
    class ContentsOnlyStub:
        calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def complete_json(self, *, instructions, document_text):
            self.calls += 1
            return {"entries": [], "boundaries": []}

    stub = ContentsOnlyStub()
    monkeypatch.setattr("pdf2audiobook.pipeline.create_provider", lambda _settings: stub)
    source = tmp_path / "contents-task.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((60, 80), "Ordinary prose for an isolated contents task.")
    doc.save(source)
    doc.close()
    settings = Settings(
        general=General(output_dir=str(tmp_path / "out")),
        pdf=Pdf(ocr="never"),
        chapters=Chapters(allow_single_chapter=True),
        llm=LLM(
            enabled=True,
            structure=False,
            contents=True,
            cleanup=False,
            classification=False,
            narration=False,
        ),
    )

    manifest_path = analyze_book(source, settings)
    report = json.loads((manifest_path.parent / "reports" / "llm_decisions.json").read_text())

    assert stub.calls == 1
    assert report["decisions"]
    assert {decision["task"] for decision in report["decisions"]} == {"contents"}


def test_contents_toggle_changes_analysis_fingerprint():
    from pdf2audiobook.pipeline import _analysis_stage_fingerprints

    settings = Settings()
    enabled = settings.model_copy(deep=True)
    enabled.llm.contents = True
    assert (
        _analysis_stage_fingerprints("book", settings, None)["llm-analysis"]
        != (_analysis_stage_fingerprints("book", enabled, None)["llm-analysis"])
    )
