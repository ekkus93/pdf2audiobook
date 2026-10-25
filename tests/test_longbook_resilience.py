"""Long-book, provider retry and interrupted resume acceptance without network."""

import json

import fitz
import httpx
import numpy as np
import pytest

from pdf2audiobook.audio import split_sentences, synthesize_chunks
from pdf2audiobook.config import LLM, General, Pdf, Settings
from pdf2audiobook.errors import AudioError, InputError
from pdf2audiobook.llm import OpenAICompatibleProvider
from pdf2audiobook.pdf import extract_pdf
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.workspace import read_manifest


class InterruptibleVoice:
    sample_rate = 24000

    def __init__(self, fail_at=None):
        self.calls = 0
        self.fail_at = fail_at

    def generate(self, text, *, voice, speed):
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError("simulated interrupted conversion")
        return np.full(1200, 0.05, dtype=np.float32)


def test_multi_page_chapter_analysis_exact_coverage_and_repeat_cache(tmp_path):
    source = tmp_path / "long.pdf"
    pdf = fitz.open()
    for number in range(120):
        page = pdf.new_page()
        if number in (0, 60):
            page.insert_text((70, 70), f"Chapter {1 if number == 0 else 2}", fontsize=19)
        page.insert_text(
            (70, 120),
            f"Page {number + 1} has unique narrative material and complete sentences.",
            fontsize=11,
        )
        page.insert_text(
            (70, 142),
            "A second paragraph ensures there are multiple source text spans.",
            fontsize=11,
        )
    pdf.save(source)
    pdf.close()
    settings = Settings(
        general=General(output_dir=str(tmp_path / "audio")),
        pdf=Pdf(ocr="never"),
        llm=LLM(enabled=False),
    )
    output = analyze_book(source, settings)
    original = output.read_bytes()
    manifest = read_manifest(output)
    assert len(manifest.chapters) == 2
    assert len(manifest.spans) >= 240
    assert manifest.chapters[0].end_block == manifest.chapters[1].start_block
    assert manifest.chapters[-1].end_block == len(manifest.blocks)
    report = json.loads((output.parent / "coverage.json").read_text())
    assert report["uncovered_blocks"] == 0
    assert report["duplicate_blocks"] == 0
    assert report["covered_blocks"] == len(manifest.blocks)
    assert analyze_book(source, settings) == output
    assert output.read_bytes() == original  # No needless reanalysis.


def test_many_chunk_interruption_resumes_only_valid_checkpoints(tmp_path):
    narration = " ".join(
        f"Sentence {index} provides unique and complete text." for index in range(300)
    )
    chunk_count = len(split_sentences(narration))
    assert chunk_count >= 20
    args = dict(
        model="mini",
        voice="Jasper",
        speed=1.0,
        pause_ms=30,
        cache=tmp_path / "wav",
        progress_file=tmp_path / "progress.json",
        max_retries=0,
    )
    failed = InterruptibleVoice(fail_at=7)
    with pytest.raises(AudioError, match="TTS synthesis failed"):
        synthesize_chunks(narration, failed, **args)
    state = json.loads(args["progress_file"].read_text())
    assert state["completed_chunks"] == 6
    assert state["status"] == "failed"
    assert len(state["chunks"]) == chunk_count

    restarted = InterruptibleVoice()
    audio = synthesize_chunks(narration, restarted, **args)
    assert audio.size > 0
    assert restarted.calls == chunk_count - 6
    assert json.loads(args["progress_file"].read_text())["status"] == "completed"
    # Even a new process/provider does not re-synthesize completed, valid WAVs.
    third = InterruptibleVoice()
    synthesize_chunks(narration, third, **args)
    assert third.calls == 0


def test_invalid_pdf_fail_closed_and_does_not_emit_manifest(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"Not a real PDF document")
    with pytest.raises(InputError):
        extract_pdf(path, Pdf(ocr="never"))
    settings = Settings(
        general=General(output_dir=str(tmp_path / "output")),
        pdf=Pdf(ocr="never"),
        llm=LLM(enabled=False),
    )
    with pytest.raises(InputError):
        analyze_book(path, settings)
    assert not list((tmp_path / "output").glob("*/manifest.json"))


def test_transient_provider_error_retries_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": "transient"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"headings":[]}'}}],
            },
        )

    with OpenAICompatibleProvider(
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model="fixed",
        allow_remote=False,
        transport=httpx.MockTransport(handler),
        max_retries=2,
    ) as provider:
        assert provider.complete_json(
            instructions="classification task", document_text="Fixture"
        ) == {"headings": []}
    assert len(calls) == 2
