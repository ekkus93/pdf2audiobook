"""Review-only vision requests are bounded, cached by image identity, and fail closed."""

import json

import httpx
import pymupdf
import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import LLMError
from pdf2audiobook.llm import OpenAICompatibleProvider, vision
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


# --- Page selection for the vision model (test coverage spec T2) ---------------


def _page_document(build):
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    build(page)
    return document, page


def _drawings(count):
    def build(page):
        for index in range(count):
            page.draw_rect(pymupdf.Rect(50 + 30 * index, 50, 70 + 30 * index, 70), color=(0, 0, 0))

    return build


def _columns(left_blocks, right_blocks):
    def build(page):
        for index in range(left_blocks):
            page.insert_text((40, 100 + 120 * index), "Left column paragraph.")
        for index in range(right_blocks):
            page.insert_text((340, 100 + 120 * index), "Right column paragraph.")

    return build


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        (lambda page: page.insert_image(pymupdf.Rect(50, 50, 150, 150), stream=_png()), True),
        (_drawings(3), True),
        (_drawings(2), False),
        (_columns(2, 2), True),
        (_columns(2, 1), False),
        (lambda page: page.insert_text((40, 100), "One column of body text."), False),
    ],
    ids=["image", "three-drawings", "two-drawings", "two-columns", "unbalanced", "one-column"],
)
def test_visual_content_detection(build, expected):
    """T2.a: images, enough drawings or two text columns mark a page for review."""
    document, page = _page_document(build)
    try:
        assert vision._has_visual_content(page) is expected
    finally:
        document.close()


class _FakePage:
    """A page whose PyMuPDF calls return or raise what each case needs."""

    rect = pymupdf.Rect(0, 0, 600, 800)

    def __init__(self, *, images=(), drawings=(), blocks=(), fail=()):
        self._images, self._drawings, self._blocks, self._fail = images, drawings, blocks, fail

    def get_image_info(self, xrefs=False):
        if "images" in self._fail:
            raise RuntimeError("private parser detail")
        return list(self._images)

    def get_drawings(self):
        if "drawings" in self._fail:
            raise RuntimeError("private parser detail")
        return list(self._drawings)

    def get_text(self, kind):
        if "text" in self._fail:
            raise RuntimeError("private parser detail")
        return list(self._blocks)


def _block(x0, x1):
    return (x0, 100.0, x1, 120.0, "text", 0, 0)


_TWO_COLUMNS = [_block(40, 200), _block(40, 200), _block(340, 500), _block(340, 500)]


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        (_FakePage(drawings=[{}] * 3, fail={"images"}), True),
        (_FakePage(blocks=_TWO_COLUMNS, fail={"images", "drawings"}), True),
        (_FakePage(fail={"images", "drawings", "text"}), False),
        (_FakePage(fail={"text"}), False),
    ],
    ids=["images-fail", "images-and-drawings-fail", "everything-fails", "text-fails"],
)
def test_visual_content_detection_falls_back_when_pymupdf_raises(page, expected):
    """T2.b: each failing inventory moves on to the next check; the last one returns False."""
    assert vision._has_visual_content(page) is expected


@pytest.mark.parametrize(
    ("side", "bad_block"),
    [
        ("left", ("40", 100.0, "200", 120.0, "text")),
        ("left", (float("-inf"), 100.0, 200.0, 120.0, "text")),
        ("left", (float("nan"), 100.0, 200.0, 120.0, "text")),
        ("right", (340.0, 100.0, float("inf"), 120.0, "text")),
        ("left", (40.0, 100.0, 200.0, 120.0)),
        ("right", (340.0, 100.0, 500.0, 120.0)),
    ],
    ids=[
        "strings",
        "minus-infinite-left",
        "nan-left",
        "infinite-right",
        "four-fields-left",
        "four-fields-right",
    ],
)
def test_malformed_text_blocks_are_not_counted_as_a_column(side, bad_block):
    """T2.c: one good block plus one malformed block on a side is not a column."""
    left, right = [_block(40, 200)], [_block(340, 500)]
    other = right if side == "left" else left
    good = _block(40, 200) if side == "left" else _block(340, 500)
    other.append(_block(340, 500) if side == "left" else _block(40, 200))
    malformed = [*left, bad_block, *right] if side == "left" else [*left, *right, bad_block]
    complete = [*left, good, *right] if side == "left" else [*left, *right, good]

    assert vision._has_visual_content(_FakePage(blocks=malformed)) is False
    assert vision._has_visual_content(_FakePage(blocks=complete)) is True


class _RecordingVisionProvider:
    def __init__(self, response=None):
        self.pages = []
        self.response = response or {"summary": "Synthetic figure.", "regions": []}

    def complete_json_with_image(self, *, instructions, document_text, image_data):
        self.pages.append(document_text)
        return self.response


def _book_with(tmp_path, builds):
    source = tmp_path / "book.pdf"
    document = pymupdf.open()
    for build in builds:
        build(document.new_page(width=600, height=800))
    document.save(source)
    document.close()
    return source


def _image(page):
    page.insert_image(pymupdf.Rect(50, 50, 150, 150), stream=_png())


def _prose(page):
    page.insert_text((40, 100), "Only body prose on this page.")


def test_pages_without_visual_content_are_never_sent(tmp_path):
    """T2.d: only the image page's rendering reaches the provider."""
    provider = _RecordingVisionProvider()

    report = review_visual_pages(_book_with(tmp_path, [_prose, _image, _prose]), provider)

    assert provider.pages == ["Visual review for source page 2."]
    assert [page["page"] for page in report["pages"]] == [2]


def test_text_only_book_sends_nothing(tmp_path):
    """T2.d: a book with no visual pages makes no provider call at all."""
    provider = _RecordingVisionProvider()

    report = review_visual_pages(_book_with(tmp_path, [_prose, _prose]), provider)

    assert provider.pages == []
    assert report["pages"] == []


def test_page_limit_skips_later_visual_pages_with_a_warning(tmp_path, monkeypatch):
    """T2.d: pages beyond the limit are counted, not sent."""
    monkeypatch.setattr(vision, "MAX_VISUAL_REVIEW_PAGES", 1)
    provider = _RecordingVisionProvider()

    report = review_visual_pages(_book_with(tmp_path, [_image, _image, _image]), provider)

    assert provider.pages == ["Visual review for source page 1."]
    assert report["warnings"] == ["Visual review page limit reached; 2 candidate page(s) skipped"]


def test_invalid_vision_response_is_rejected_with_a_page_warning(tmp_path):
    """T2.d: a response that fails the schema adds a warning and no finding."""
    provider = _RecordingVisionProvider(response={"summary": 5, "regions": "none"})

    report = review_visual_pages(_book_with(tmp_path, [_image]), provider)

    assert report["pages"] == []
    assert report["warnings"] == ["Visual review response rejected for page 1"]


def test_unopenable_book_fails_with_a_fixed_message(tmp_path):
    """T2.d: an unreadable source gives no path or parser detail."""
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"not a pdf")

    with pytest.raises(LLMError, match="^Could not open book for visual review$"):
        review_visual_pages(source, _RecordingVisionProvider())
