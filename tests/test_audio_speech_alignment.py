"""Spoken-text rewrites may change token counts without breaking alignment (R64)."""

import pytest

from pdf2audiobook.audio import chunk_source_ranges, normalize_narration_text, split_sentences


def _align(source, **kwargs):
    chunks = split_sentences(source, **kwargs)
    return chunks, chunk_source_ranges(source, chunks, kwargs.get("pronunciations"))


@pytest.mark.parametrize(
    ("source", "spoken"),
    [
        ("Read 10–20 pages today.", "Read 10 to 20 pages today."),
        ("In 1990–91 it rained.", "In 1990 to 91 it rained."),
        ("See pp. 3–4.", "See pp. 3 to 4."),
        ("wait—then go.", "wait, then go."),
        ("wait — then go.", "wait, then go."),
        ("wait —then go.", "wait, then go."),
        ("wait— then go.", "wait, then go."),
        ("a–b and a‒b.", "a, b and a-b."),
    ],
)
def test_dash_rewrites_align_and_read_naturally(source, spoken):
    chunks, ranges = _align(source)
    assert chunks == [spoken]
    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(source)


def test_leading_dash_paragraph_does_not_borrow_a_comma_from_the_previous_one():
    source = "First paragraph.\n\n— Second one."
    chunks, ranges = _align(source)
    assert chunks == ["First paragraph.", "Second one."]
    assert ranges[1][2] is True


def test_dash_only_word_ending_a_chunk_stays_inside_the_source_range():
    source = "Alone —\n\nNext."
    chunks, ranges = _align(source)
    assert chunks == ["Alone,", "Next."]
    assert source[ranges[0][0] : ranges[0][1]] == "Alone —"


def test_every_dash_rule_aligns_in_generated_sentences():
    openers = ["It", "She said", "In 1990"]
    joiners = ["—", " — ", "–", " – ", "‒", "―"]
    middles = ["10–20", "3–4", "go", "1990–91"]
    for opener in openers:
        for joiner in joiners:
            for middle in middles:
                source = f"{opener}{joiner}{middle} done. Then{joiner}stop."
                chunks, ranges = _align(source)
                assert ranges, source
                assert ranges[0][0] == 0 and ranges[-1][1] == len(source)


def test_normalize_text_reads_dash_runs_with_one_following_space():
    assert normalize_narration_text("pages 12–14; a‒b; pause—here") == (
        "pages 12 to 14; a-b; pause, here"
    )
    assert normalize_narration_text("pause —— here") == "pause, here"


def test_normalized_chunks_keep_source_ranges_with_comma_spacing():
    source = "“ﬁrst” line—next…\n\nsoft­hyphen​ end here."
    before = source
    chunks, ranges = _align(source)
    assert chunks == ['"first" line, next...', "softhyphen end here."]
    assert ranges[0][0] == 0
    assert ranges[1][2] is True
    assert source == before


def test_ellipsis_token_still_matches_its_pronunciation_key():
    assert split_sentences("hello...", pronunciations={"hello": "hullo"}) == ["hullo."]
