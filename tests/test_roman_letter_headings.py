"""One-letter Roman numerals are headings only beside neighbouring numerals (R66)."""

import pytest

from pdf2audiobook.config import Chapters
from pdf2audiobook.document.structure import is_heading_line, propose_chapters
from pdf2audiobook.models import DocumentBlock


def _blocks(*texts: str) -> list[DocumentBlock]:
    return [
        DocumentBlock(id=f"b{i}", page_index=i, text=text, span_ids=[], order=i, kind="unknown")
        for i, text in enumerate(texts)
    ]


def _chapter_count(*texts: str) -> int:
    chapters, _ = propose_chapters(_blocks(*texts), set(), [], Chapters())
    return len([chapter for chapter in chapters if chapter.title])


BODY = "The story goes on for a while with ordinary prose about the weather."


@pytest.mark.parametrize(
    "attribution", ["C. DICKENS", "M. LEBLANC", "D. H. LAWRENCE", "L. FRANK BAUM", "X. GREY"]
)
def test_epigraph_attribution_is_not_a_heading(attribution):
    assert not is_heading_line(attribution)
    texts = ["I. THE STORM", BODY, attribution, BODY, "II. THE CALM", BODY, "III. THE END", BODY]
    assert _chapter_count(*texts) == 3


def test_i_ii_iii_headings_still_split_three_chapters():
    texts = ["I. THE STORM", BODY, "II. THE CALM", BODY, "III. THE RETURN", BODY]
    assert _chapter_count(*texts) == 3


def test_v_between_iv_and_vi_keeps_its_heading():
    texts = ["IV. THE FIELD", BODY, "V. THE FOREST", BODY, "VI. THE RIVER", BODY]
    chapters, _ = propose_chapters(_blocks(*texts), set(), [], Chapters())
    assert [chapter.title for chapter in chapters if "FOREST" in chapter.title] != []
    assert _chapter_count(*texts) == 3


def test_ambiguous_attribution_beside_numbered_chapters_stays_body_text():
    texts = ["IV. THE FIELD", BODY, "C. DICKENS", BODY, "VI. THE RIVER", BODY]
    assert _chapter_count(*texts) == 2
