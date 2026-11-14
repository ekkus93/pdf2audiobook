"""Comparison core for audio verification: normalization, alignment and 2-of-3 voting (AV1.03, AV1.04)."""

from __future__ import annotations

from pdf2audiobook.verification.compare import (
    MIN_WORDS,
    chapter_outcome,
    differences,
    tokenize,
    tokenize_text,
    vote,
)
from pdf2audiobook.verification.contracts import Difference, ModelRun, Word

REFERENCE = (
    "Mara Quill had kept the light at Gull Point for eleven winters. Each evening she climbed "
    "the ninety-two steps, trimmed the wick and wound the clockwork that turned the great lens."
)


def timed(text: str, start: float = 0.0, step: float = 0.4) -> list[Word]:
    """Words of `text` with evenly spaced times, as a backend would return them."""
    return [
        Word(word, round(start + i * step, 2), round(start + i * step + step * 0.8, 2))
        for i, word in enumerate(text.split())
    ]


def heard(text: str) -> list:
    return tokenize(timed(text))


def ref() -> list:
    return tokenize_text(REFERENCE)


def test_matching_speech_has_no_differences() -> None:
    spoken = (
        "mara quill had kept the light at gull point for 11 winters each evening she climbed "
        "the 92 steps trimmed the wick and wound the clockwork that turned the great lens"
    )
    assert differences("whisper", ref(), heard(spoken)) == []


def test_presentation_differences_are_normalized() -> None:
    # Case, punctuation, hyphens, apostrophes and number formats don't count.
    reference = tokenize_text("It's 1,250 metres — a well-known figure, isn't it?")
    spoken = heard("its one thousand two hundred fifty metres a well known figure isnt it")
    assert differences("vosk", reference, spoken) == []


INSERTED = (
    "mara quill had kept the light at gull point for eleven winters each evening she climbed "
    "the ninety two steps and the old ferry bell rang twice trimmed the wick and wound the "
    "clockwork that turned the great lens"
)


def test_an_insertion_heard_by_two_models_is_a_possible_mismatch() -> None:
    reference = ref()
    found = {
        "whisper": differences("whisper", reference, heard(INSERTED)),
        "vosk": differences("vosk", reference, heard(INSERTED)),
    }
    flags = vote(reference, found)
    assert len(flags) == 1
    flag = flags[0]
    assert flag.confirmed and flag.models == ("whisper", "vosk")
    assert flag.kind == "insertion"
    assert flag.heard["whisper"] == "and the old ferry bell rang twice"
    assert flag.expected == ""
    # It sits between "steps," and "trimmed" in the reference.
    words = [t.display for t in reference]
    assert words[flag.ref_start - 1] == "steps," and words[flag.ref_start] == "trimmed"


def test_one_model_hallucination_is_disagreement_not_a_defect() -> None:
    reference = ref()
    clean = REFERENCE.lower().replace(",", "").replace(".", "")
    found = {
        "whisper": differences("whisper", reference, heard(INSERTED)),
        "wav2vec2": differences("wav2vec2", reference, heard(clean)),
        "vosk": differences("vosk", reference, heard(clean)),
    }
    flags = vote(reference, found)
    assert len(flags) == 1
    assert not flags[0].confirmed and flags[0].models == ("whisper",)


def test_omission_is_found_with_its_place_in_time() -> None:
    reference = ref()
    spoken = (
        "mara quill had kept the light at gull point for eleven winters "
        "trimmed the wick and wound the clockwork that turned the great lens"
    )
    found = differences("wav2vec2", reference, heard(spoken))
    assert len(found) == 1
    omission = found[0]
    assert omission.kind == "omission"
    assert omission.expected == "Each evening she climbed the ninety-two steps,"
    assert omission.heard == ""
    words = timed(spoken)
    # Between "winters" (word 11, counting from 0) and "trimmed" (word 12).
    assert (words[11].text, words[12].text) == ("winters", "trimmed")
    assert omission.start == words[11].end and omission.end == words[12].start


def test_substitution_of_a_phrase() -> None:
    reference = ref()
    spoken = INSERTED.replace(" and the old ferry bell rang twice", "").replace(
        "the great lens", "the kitchen door"
    )
    found = differences("vosk", reference, heard(spoken))
    assert [(d.kind, d.expected, d.heard) for d in found] == [
        ("substitution", "great lens.", "kitchen door")
    ]


def test_a_wrong_number_is_a_substitution_even_one_word_long() -> None:
    reference = tokenize_text("In 1987 the gauge recorded rain.")
    assert (
        differences("whisper", reference, heard("in nineteen eighty seven the gauge recorded rain"))
        == []
    )
    wrong = differences(
        "whisper", reference, heard("in nineteen seventy eight the gauge recorded rain")
    )
    assert [(d.kind, d.expected, d.heard) for d in wrong] == [
        ("substitution", "1987", "nineteen seventy eight")
    ]


def test_number_values_cover_years_decimals_and_cardinals() -> None:
    reference = tokenize_text("By 2004 it was 3.5 metres on the 12th, about 40 boats.")
    spoken = heard(
        "by twenty oh four it was three point five metres on the twelfth about forty boats"
    )
    assert differences("vosk", reference, spoken) == []


def test_single_word_slips_are_below_the_threshold() -> None:
    assert MIN_WORDS == 2
    reference = ref()
    spoken = REFERENCE.lower().replace("quill", "quil").replace("winters", "winter")
    assert differences("whisper", reference, heard(spoken)) == []


def test_compounds_and_spelling_variants_are_the_same_speech() -> None:
    reference = tokenize_text("The harbour logbook was grey at six o'clock, 365 metres out.")
    spoken = heard("the harbor log book was gray at six o clock three sixty five meters out")
    assert differences("vosk", reference, spoken) == []


def test_a_number_written_in_pieces_still_matches() -> None:
    reference = tokenize_text("It rained 1,250 millimetres, or 3.5 more.")
    assert (
        differences("whisper", reference, heard("it rained 1, 250 millimeters or 3 .5 more")) == []
    )


def test_short_clips_compare_cleanly() -> None:
    reference = tokenize_text("Chapter 2: The Storm")
    assert differences("vosk", reference, heard("chapter two the storm")) == []
    assert differences("vosk", reference, heard("chapter")) == [
        Difference("vosk", "omission", 1, 4, "2: The Storm", "", 0.32, 0.32)
    ]
    assert differences("vosk", reference, heard("")) == [
        Difference("vosk", "omission", 0, 4, "Chapter 2: The Storm", "", None, None)
    ]


def test_timestamps_stay_within_the_heard_words() -> None:
    reference = ref()
    words = timed(INSERTED, start=12.0)
    found = differences("whisper", reference, tokenize(words))
    assert len(found) == 1
    inserted = found[0]
    first = next(w for w in words if w.text == "old")
    last = next(w for w in words if w.text == "twice")
    assert inserted.start is not None and inserted.end is not None
    assert words[0].start <= inserted.start <= first.start
    assert last.end <= inserted.end <= words[-1].end


def test_failed_models_abstain() -> None:
    # Only models that produced a transcript are in the vote; one alone can't confirm.
    reference = ref()
    flags = vote(reference, {"vosk": differences("vosk", reference, heard(INSERTED))})
    assert len(flags) == 1 and not flags[0].confirmed


def test_disagreement_on_different_places_is_not_combined() -> None:
    reference = ref()
    early = INSERTED.replace(" and the old ferry bell rang twice", "").replace(
        "had kept", "had always quietly kept"
    )
    found = {
        "whisper": differences("whisper", reference, heard(INSERTED)),
        "wav2vec2": differences("wav2vec2", reference, heard(early)),
    }
    flags = vote(reference, found)
    assert len(flags) == 2
    assert all(not flag.confirmed for flag in flags)


def _flags(*sets: str) -> list:
    reference = ref()
    texts = {"inserted": INSERTED, "clean": REFERENCE.lower().replace(",", "").replace(".", "")}
    found = {
        model: differences(model, reference, heard(texts[kind]))
        for model, kind in zip(("whisper", "wav2vec2", "vosk"), sets)
    }
    return vote(reference, found)


OK = [ModelRun("whisper", "ok"), ModelRun("wav2vec2", "ok"), ModelRun("vosk", "ok")]


def test_outcome_of_three_agreeing_models() -> None:
    assert chapter_outcome(OK, _flags("clean", "clean", "clean")) == (
        "no_mismatch_detected",
        None,
        False,
    )
    assert chapter_outcome(OK, _flags("inserted", "inserted", "clean")) == (
        "possible_mismatch",
        None,
        False,
    )
    assert chapter_outcome(OK, _flags("inserted", "clean", "clean")) == (
        "model_disagreement",
        None,
        False,
    )


def test_a_failed_model_abstains_and_the_result_is_partial() -> None:
    runs = [
        ModelRun("whisper", "ok"),
        ModelRun("wav2vec2", "failed", "model_failed"),
        ModelRun("vosk", "ok"),
    ]
    reference = ref()
    flags = vote(
        reference,
        {
            "whisper": differences("whisper", reference, heard(INSERTED)),
            "vosk": differences("vosk", reference, heard(INSERTED)),
        },
    )
    assert chapter_outcome(runs, flags) == ("possible_mismatch", None, True)


def test_one_model_alone_can_only_disagree() -> None:
    runs = [
        ModelRun("whisper", "ok"),
        ModelRun("wav2vec2", "unavailable", "model_not_installed"),
        ModelRun("vosk", "unavailable", "model_not_downloaded"),
    ]
    reference = ref()
    flags = vote(reference, {"whisper": differences("whisper", reference, heard(INSERTED))})
    assert chapter_outcome(runs, flags) == ("model_disagreement", None, True)
    assert chapter_outcome(runs, []) == ("no_mismatch_detected", None, True)


def test_no_voting_model_means_unavailable() -> None:
    runs = [
        ModelRun(m, "unavailable", "model_not_installed") for m in ("whisper", "wav2vec2", "vosk")
    ]
    assert chapter_outcome(runs, []) == ("verification_unavailable", "no_models", True)
    cancelled = [ModelRun("whisper", "failed", "cancelled")]
    assert chapter_outcome(cancelled, []) == ("verification_unavailable", "cancelled", True)
