"""Characterization of branches no other test reaches (long function split spec S11).

Each test pins today's behaviour of one branch inside a function that the split
TODO restructures, so the split cannot change it unnoticed.
"""

import contextlib
import hashlib
import json

import numpy as np
import pytest
from typer.testing import CliRunner

from pdf2audiobook import pipeline
from pdf2audiobook.audio import audio_output_path, synthesize_chunks
from pdf2audiobook.config import Pdf, Settings
from pdf2audiobook.conversion import _rendering_inputs
from pdf2audiobook.document.structure import pagination_cleanup
from pdf2audiobook.errors import AudioError, ExtractionError, LLMError
from pdf2audiobook.llm.cache import CachedLLMProvider
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.workspace import digest_bytes


def test_pagination_tie_within_one_margin_band_is_ambiguous():
    """S1: two equally placed folios in one band keep both and flag review."""

    def block(page, ident, text, box):
        return DocumentBlock(
            id=ident, text=text, page_index=page, bbox=box, font_size=10, order=page * 10
        )

    blocks = []
    for page in range(4):
        blocks += [
            block(page, f"body-{page}", "Text in the body of the page.", (70, 150, 500, 170)),
            block(page, f"left-{page}", str(page + 1), (70, 768, 90, 782)),
            block(page, f"right-{page}", str(page + 40), (500, 768, 520, 782)),
        ]
    warnings: list[str] = []
    reasons: set[str] = set()

    edits = pagination_cleanup(
        blocks, [(600.0, 800.0)] * 4, Pdf(), warnings=warnings, review_reasons=reasons
    )

    assert edits == []
    assert warnings == [
        "Equally positioned margin numerals retained; verify page-number candidates"
    ]
    assert reasons == {"ambiguous_page_numbers"}


def test_resume_regenerates_an_unreadable_mp3_behind_a_valid_sidecar(tmp_path, monkeypatch):
    """S4: a current-format sidecar can't vouch for an MP3 whose tags can't be read."""
    settings = Settings()
    settings.general.resume = True
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic placeholder")
    root = tmp_path / "book-output"
    manifest_path = root / "manifest.json"
    chapter = Chapter(
        id="chapter-1",
        number=1,
        title="Synthetic Chapter",
        start_block=0,
        end_block=1,
        confidence=1.0,
    )
    manifest = BookManifest(
        schema_version=3,
        input_sha256="synthetic-sha",
        title="Synthetic Book",
        source_path=str(source),
        blocks=[DocumentBlock(id="paragraph", text="Synthetic text.", span_ids=[], page_index=0)],
        chapters=[chapter],
    )
    (root / "chapters").mkdir(parents=True)
    text = "Synthetic text."
    (root / "chapters" / "001.txt").write_text(text, encoding="utf-8")
    output = audio_output_path(manifest, chapter, root)
    output.parent.mkdir(parents=True)
    invalid_mp3 = b"not an MPEG audio frame"
    output.write_bytes(invalid_mp3)
    output.with_suffix(".cache.json").write_text(
        json.dumps(
            {
                "chapter_id": chapter.id,
                "sidecar_version": 3,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "fingerprint": pipeline.chapter_audio_fingerprint(
                    text, settings, manifest, chapter
                ),
                "bytes": len(invalid_mp3),
                "sha256": digest_bytes(invalid_mp3),
                "rendering_inputs": _rendering_inputs(settings),
            }
        ),
        encoding="utf-8",
    )

    class StubKitten:
        sample_rate = 24000

        def __init__(self, _model):
            pass

    regenerated = []
    monkeypatch.setattr(pipeline, "analyze_book", lambda *_, **_kw: manifest_path)
    monkeypatch.setattr(pipeline, "read_manifest", lambda *_: manifest)
    monkeypatch.setattr(pipeline, "render_chapter_texts", lambda *_: None)
    monkeypatch.setattr(pipeline, "KittenProvider", StubKitten)
    monkeypatch.setattr(
        pipeline, "synthesize_chunks", lambda *_a, **_k: np.full(2400, 0.01, dtype=np.float32)
    )

    def publish(_audio, _rate, target, **_metadata):
        regenerated.append(target)
        target.write_bytes(b"new verified audio placeholder")
        return target

    monkeypatch.setattr(pipeline, "encode_mp3", publish)

    assert pipeline.convert_book(source, settings) == [output]
    assert regenerated == [output]


@pytest.mark.parametrize("max_retries", [True, -1, 11, "2", 2.0])
def test_synthesis_rejects_an_invalid_retry_count(max_retries, tmp_path):
    """S5: argument validation runs before any engine call."""

    class NeverCalled:
        sample_rate = 24000

        def generate(self, *_args, **_kwargs):
            raise AssertionError("the engine must not be called")

    with pytest.raises(AudioError, match="TTS max_retries must be an integer from 0 to 10"):
        synthesize_chunks(
            "Some text.",
            NeverCalled(),
            model="m",
            voice="v",
            speed=1.0,
            pause_ms=0,
            max_retries=max_retries,
            cache=tmp_path,
        )


def test_cost_budget_without_prices_refuses_before_sending(tmp_path):
    """S6: a cost budget needs a price-derived bound before any request is sent."""
    sent = []

    class Provider:
        model = "stub"
        total_usage: dict = {}

        def complete_json(self, *, instructions, document_text):
            sent.append(document_text)
            return {}

    cached = CachedLLMProvider(
        Provider(), cache_dir=tmp_path, identity="stub", max_estimated_cost_usd=1.0
    )

    with pytest.raises(
        LLMError, match="A bounded output token cap is required under an LLM budget"
    ):
        cached.complete_json(instructions="Return JSON.", document_text="Synthetic.")
    assert sent == []


class _CapacityProvider:
    """A provider whose request and served-context checks can be made to fail."""

    model = "stub"
    max_output_tokens = 64
    max_context_tokens = 4096

    def __init__(self):
        self.total_usage: dict = {}
        self.request_limit: int | None = None
        self.served_error = False
        self.sent: list[str] = []

    def validate_request_capacity(self, *, instructions, document_text):
        if self.request_limit is not None and len(document_text) > self.request_limit:
            raise LLMError("LLM request exceeds the context window")

    def validate_served_capacity(self, *, instructions, document_text):
        if self.served_error:
            raise LLMError("Served context window is too small")

    def complete_json(self, *, instructions, document_text):
        self.sent.append(document_text)
        return {"answer": "synthetic"}


def test_oversized_request_is_rejected_even_when_its_reply_is_cached(tmp_path):
    """S6: the oversized-request check runs before the cache lookup."""
    provider = _CapacityProvider()
    cached = CachedLLMProvider(provider, cache_dir=tmp_path, identity="stub")
    request = {"instructions": "Return JSON.", "document_text": "Synthetic text."}
    assert cached.complete_json(**request) == {"answer": "synthetic"}

    provider.request_limit = 3
    with pytest.raises(LLMError, match="LLM request exceeds the context window"):
        cached.complete_json(**request)

    assert cached.hits == 0
    assert provider.sent == ["Synthetic text."]


def test_served_capacity_is_checked_before_the_budget_is_reserved(tmp_path):
    """S6: a served-context rejection on a miss leaves no ledger reservation."""
    from pdf2audiobook.llm.budget import BookLLMBudgetLedger

    provider = _CapacityProvider()
    provider.served_error = True
    ledger_path = tmp_path / "llm_budget.sqlite3"
    cached = CachedLLMProvider(
        provider,
        cache_dir=tmp_path / "cache",
        identity="stub",
        max_requests=5,
        ledger_path=ledger_path,
    )

    with pytest.raises(LLMError, match="Served context window is too small"):
        cached.complete_json(instructions="Return JSON.", document_text="Synthetic text.")

    assert cached.requests_started == 0
    assert provider.sent == []
    assert BookLLMBudgetLedger(ledger_path).rows() == []


def test_extraction_of_a_book_with_no_pages_is_refused(tmp_path, monkeypatch):
    """S8: an empty document stops before any page work."""
    from pdf2audiobook import pdf

    class Empty:
        def __len__(self):
            return 0

    @contextlib.contextmanager
    def empty_open(*_args, **_kwargs):
        yield Empty()

    monkeypatch.setattr(pdf, "_open", empty_open)
    source = tmp_path / "empty.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    with pytest.raises(ExtractionError, match="Book has no extractable pages"):
        pdf.extract_pdf(source, Pdf())


def test_convert_cli_routes_model_and_password_overrides(tmp_path, monkeypatch):
    """S9: `--llm-model` follows the configured provider; `--pdf-password-env` is passed on."""
    from pdf2audiobook.cli import app

    config = tmp_path / "config.toml"
    config.write_text('[llm]\nprovider = "openai"\n', encoding="utf-8")
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    captured = {}

    def fake_convert(_source, settings, **_kwargs):
        captured["settings"] = settings
        return []

    monkeypatch.setattr("pdf2audiobook.pipeline.convert_book", fake_convert)

    result = CliRunner().invoke(
        app,
        [
            "convert",
            str(source),
            "--config",
            str(config),
            "--output",
            str(tmp_path / "out"),
            "--llm-model",
            "synthetic-model",
            "--pdf-password-env",
            "BOOK_PASSWORD",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stderr
    settings = captured["settings"]
    assert settings.llm.openai.model == "synthetic-model"
    assert settings.pdf.password_env == "BOOK_PASSWORD"


class _ContentsStub:
    """Returns one fixed contents/boundary response for every window."""

    model = "stub"

    def __init__(self, response):
        self.response = response

    def complete_json(self, *, instructions, document_text):
        return self.response


def _entry(block_id, title="Chapter Two", page="9"):
    return {"block_id": block_id, "title": title, "page_reference": page, "confidence": 0.9}


def test_contents_entry_maps_only_to_a_unique_later_title():
    """Contents: only later blocks count, and a title that appears twice maps to neither."""
    from pdf2audiobook.llm import propose_llm_contents_boundaries

    blocks = [
        DocumentBlock(id="preface-heading", page_index=0, text="Chapter One"),
        DocumentBlock(id="unique", page_index=0, text="Chapter One ..... 3"),
        DocumentBlock(id="twice", page_index=0, text="Chapter Two ..... 9"),
        DocumentBlock(id="one", page_index=1, text="Chapter One"),
        DocumentBlock(id="two-a", page_index=2, text="Chapter Two"),
        DocumentBlock(id="two-b", page_index=3, text="Chapter Two"),
    ]
    response = {"entries": [_entry("unique", "Chapter One", "3"), _entry("twice")]}

    ids, warnings = propose_llm_contents_boundaries(blocks, _ContentsStub(response))

    assert ids == {"one"}
    assert warnings == []


def test_repeated_contents_entry_and_boundary_are_rejected_as_duplicates():
    """Contents: a block proposed twice is verified once, then rejected."""
    from pdf2audiobook.llm import propose_llm_contents_boundaries

    blocks = [
        DocumentBlock(id="entry", page_index=0, text="Chapter Two ..... 9"),
        DocumentBlock(id="body", page_index=2, text="Chapter Two"),
    ]
    boundary = {"block_id": "body", "title": "Chapter Two", "confidence": 0.9}
    response = {"entries": [_entry("entry")] * 2, "boundaries": [boundary] * 2}
    decisions = []

    ids, warnings = propose_llm_contents_boundaries(
        blocks, _ContentsStub(response), decisions=decisions
    )

    assert ids == {"body"}
    assert [(d.block_id, d.status, d.reason_code) for d in decisions] == [
        ("entry", "accepted", "verified_contents_entry"),
        ("entry", "rejected", "unknown_or_duplicate_contents_block"),
        ("body", "accepted", "verified_boundary_candidate"),
        ("body", "rejected", "unknown_or_duplicate_boundary_block"),
    ]
    assert warnings == [
        "LLM contents entry references an unknown/duplicate block entry",
        "LLM boundary references an unknown/duplicate block body",
    ]


def test_cost_budget_with_an_output_cap_but_no_prices_refuses_before_sending(tmp_path):
    """Cache: a cost budget cannot bound a request without prices, even with an output cap."""
    provider = _CapacityProvider()
    cached = CachedLLMProvider(
        provider, cache_dir=tmp_path, identity="stub", max_estimated_cost_usd=1.0
    )

    with pytest.raises(
        LLMError, match="A bounded output token cap is required under an LLM budget"
    ):
        cached.complete_json(instructions="Return JSON.", document_text="Synthetic.")

    assert provider.sent == []
    assert cached.requests_started == 0
