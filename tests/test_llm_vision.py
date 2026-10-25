"""Review-only vision requests are bounded, cached by image identity, and fail closed."""

import json

import httpx
import pymupdf

from pdf2audiobook.config import Settings
from pdf2audiobook.llm import OpenAICompatibleProvider
from pdf2audiobook.llm.cache import CachedLLMProvider
from pdf2audiobook.llm.vision import review_visual_pages
from pdf2audiobook.pipeline import analyze_book


def _png(value=255):
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32), False)
    pixmap.clear_with(value)
    return pixmap.tobytes("png")


def test_provider_sends_image_in_openai_compatible_content_list():
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"summary":"A diagram","regions":[]}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    with OpenAICompatibleProvider(
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model="vision-model",
        allow_remote=False,
        transport=httpx.MockTransport(respond),
        max_context_tokens=4096,
        max_output_tokens=512,
    ) as provider:
        result = provider.complete_json_with_image(
            instructions="Inspect only the image.",
            document_text="Page 1 visual review.",
            image_data=_png(),
        )

    assert result == {"summary": "A diagram", "regions": []}
    content = calls[0]["messages"][1]["content"]
    assert content[0]["text"] == "Page 1 visual review."
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert calls[0]["max_tokens"] == 512


def test_cached_vision_requests_use_the_image_digest_and_do_not_store_image(tmp_path):
    class FakeVisionProvider:
        def __init__(self):
            self.calls = 0

        def complete_json_with_image(self, *, instructions, document_text, image_data):
            self.calls += 1
            return {"call": self.calls}

    provider = FakeVisionProvider()
    cached = CachedLLMProvider(provider, cache_dir=tmp_path, identity="vision-v1")

    assert cached.complete_json_with_image(
        instructions="prompt", document_text="page 1", image_data=_png()
    ) == {"call": 1}
    assert cached.complete_json_with_image(
        instructions="prompt", document_text="page 1", image_data=_png()
    ) == {"call": 1}
    assert cached.complete_json_with_image(
        instructions="prompt", document_text="page 1", image_data=_png(0)
    ) == {"call": 2}
    assert provider.calls == 2
    assert all(b"data:image" not in path.read_bytes() for path in tmp_path.glob("*.json"))


def test_review_visual_pages_returns_review_only_findings_for_image_page(tmp_path):
    source = tmp_path / "figure.pdf"
    document = pymupdf.open()
    page = document.new_page(width=300, height=300)
    page.insert_text((20, 30), "Synthetic body text")
    page.insert_image(pymupdf.Rect(40, 60, 250, 260), stream=_png())
    document.save(source)
    document.close()

    class FakeVisionProvider:
        def __init__(self):
            self.calls = 0

        def complete_json_with_image(self, *, instructions, document_text, image_data):
            self.calls += 1
            assert "untrusted" in instructions
            assert document_text == "Visual review for source page 1."
            assert image_data.startswith(b"\x89PNG")
            return {
                "summary": "A synthetic diagram is visible.",
                "regions": [{"kind": "diagram", "description": "Review the labeled arrows."}],
            }

    provider = FakeVisionProvider()
    report = review_visual_pages(source, provider)

    assert provider.calls == 1
    assert report["requires_manual_review"] is True
    assert report["pages"][0]["page"] == 1
    assert report["pages"][0]["regions"][0]["kind"] == "diagram"


def test_vision_analysis_writes_review_report_without_changing_chapter_text(tmp_path, monkeypatch):
    source = tmp_path / "visual.pdf"
    document = pymupdf.open()
    page = document.new_page(width=300, height=300)
    page.insert_text((20, 30), "This is source prose that must remain unchanged.")
    page.insert_image(pymupdf.Rect(40, 60, 250, 260), stream=_png())
    document.save(source)
    document.close()

    class FakeVisionProvider:
        last_usage = {}
        total_usage = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def complete_json_with_image(self, *, instructions, document_text, image_data):
            return {"summary": "A figure requires review.", "regions": []}

    monkeypatch.setattr(
        "pdf2audiobook.pipeline.create_provider", lambda _settings: FakeVisionProvider()
    )
    settings = Settings.model_validate(
        {
            "general": {"output_dir": str(tmp_path / "out")},
            "chapters": {"allow_single_chapter": True},
            "llm": {
                "enabled": True,
                "structure": False,
                "cleanup": False,
                "classification": False,
                "narration": False,
                "vision": True,
            },
        }
    )

    manifest_path = analyze_book(source, settings)
    chapter_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(manifest_path.parent.glob("chapters/*.txt"))
    )
    report = json.loads((manifest_path.parent / "reports" / "vision_review.json").read_text())

    assert "This is source prose that must remain unchanged." in chapter_text
    assert report["requires_manual_review"] is True
    assert report["pages"][0]["summary"] == "A figure requires review."
