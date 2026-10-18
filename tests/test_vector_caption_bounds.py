"""Bounded vector-artwork caption detection on complex PDF drawing lists."""

from types import SimpleNamespace

import pdf2audiobook.special_material as special


class DenseVectorPage:
    cropbox = SimpleNamespace(width=1000, height=1000)

    def get_drawings(self):
        # Many sizable but horizontally disjoint paths; without a bound the
        # pairwise region scan would grow quadratically with page complexity.
        return [
            {"rect": (i * 100.0, 10.0, i * 100.0 + 40.0, 50.0)}
            for i in range(3000)
        ]


def test_complex_vector_page_caps_caption_candidates_but_flags_review(monkeypatch):
    calls = 0
    original = special._valid_box

    def counted(box):
        nonlocal calls
        calls += 1
        return original(box)

    monkeypatch.setattr(special, "_valid_box", counted)
    page = DenseVectorPage()
    assert special._vector_caption_regions(page) == []
    assert calls <= 256
    assert any("review" in warning.lower() for warning in
               special.vector_artwork_warnings(page, page_number=1))
