"""Compare ASR transcripts with the expected narration and vote across model families.

Normalization keeps only safe presentation differences out of the comparison (spec §5):
case, punctuation, hyphens, apostrophes, British and American spelling, compounds written as
one word or two, and number formatting. A run of digits or number words is one token whose
possible values are compared, so "1987" matches "nineteen eighty seven" but not "nineteen
seventy eight". Alignment is a word-level edit distance, vectorized per row so whole chapters
stay fast; very long chapters are split at a long exact match first. Thresholds come from the
AV0.03 benchmark (spec §13).
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from pdf2audiobook.verification.contracts import (
    MODEL_NAMES,
    ChapterStatus,
    Difference,
    DifferenceKind,
    Flag,
    ModelName,
    ModelRun,
    Word,
)

# A difference shorter than this many words is ignored as noise (spec §5, §13)...
MIN_WORDS = 2
# ...except a one-word substitution by a clearly different word of four letters or more,
# such as "kitchen" for "harbour".
MIN_LETTERS = 4
# A substitution whose letters are this similar or more is a near-miss of the transcriber
# ("boat" for "boats", "goal" for "Gull", "goals work" for "Gulls worked"), not a mismatch.
DISSIMILAR = 0.5
# Differences from two models count as the same place if their reference spans come within
# this many words of each other (word boundaries and timings differ slightly between models).
SLACK_WORDS = 2

_SMALL = {
    word: value
    for value, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen".split()
    )
}
_SMALL["oh"] = 0
_TENS = {
    word: 10 * value
    for value, word in enumerate(
        "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
    )
    if word != "_"
}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_ORDINALS = {
    "first": "one", "second": "two", "third": "three", "fourth": "four", "fifth": "five",
    "sixth": "six", "seventh": "seven", "eighth": "eight", "ninth": "nine", "tenth": "ten",
    "eleventh": "eleven", "twelfth": "twelve", "twentieth": "twenty", "thirtieth": "thirty",
    "hundredth": "hundred", "thousandth": "thousand",
}  # fmt: skip
_NUMBER_WORDS = set(_SMALL) | set(_TENS) | set(_SCALES) | set(_ORDINALS)
_DIGITS = re.compile(r"\d+(?:\.\d+)?(?:st|nd|rd|th|s)?")


@dataclass(frozen=True)
class Token:
    """A normalized word. Number runs have `key == "#"` and their possible values."""

    key: str
    display: str
    start: float | None = None
    end: float | None = None
    values: frozenset[float] = frozenset()


# British spellings folded to American ones, so neither side is "wrong" for its spelling.
_SPELLING = {
    "grey": "gray",
    "programme": "program",
    "cheque": "check",
    "tyre": "tire",
    "kerb": "curb",
}
_NOT_OUR = {
    "four",
    "your",
    "hour",
    "pour",
    "tour",
    "sour",
    "flour",
    "devour",
    "detour",
    "contour",
    "amour",
}
_NOT_TRE = {"genre", "acre", "massacre", "ogre", "mediocre", "lucre", "padre"}


def _spelling(word: str) -> str:
    word = _SPELLING.get(word, word)
    root, suffix = re.fullmatch(r"(.*?)(s|ed|ing|)", word).groups()  # type: ignore[union-attr]
    if len(root) >= 5 and root.endswith("our") and root not in _NOT_OUR:
        root = root[:-3] + "or"  # harbour, colour, neighbour
    elif len(root) >= 4 and root.endswith("tre") and root not in _NOT_TRE:
        root = root[:-3] + "ter"  # metre, centre, theatre
    elif root.endswith("ise") and len(root) >= 6:
        root = root[:-3] + "ize"  # realise, organise
    return root + suffix


def _words(text: str) -> list[str]:
    text = text.lower().replace("’", "'").replace("&", " and ")
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 1,250 -> 1250
    text = re.sub(r"[-–—/_]", " ", text)
    stripped = (re.sub(r"^[^\w']+|[^\w']+$", "", word) for word in text.split())
    return [word for word in stripped if word]


def _cardinal(words: Sequence[str]) -> float | None:
    """The value of a spelled cardinal such as "one thousand two hundred fifty"."""
    total = current = 0.0
    seen = False
    for word in words:
        word = _ORDINALS.get(word, word)
        if word in _SMALL:
            current += _SMALL[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == "hundred":
            current = (current or 1) * 100
        elif word in _SCALES:
            total += (current or 1) * _SCALES[word]
            current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


def _values(words: Sequence[str]) -> frozenset[float]:
    """Every value a run of number words or digits may mean."""
    values: set[float] = set()
    digits = [re.sub(r"(st|nd|rd|th|s)$", "", w) for w in words if _DIGITS.fullmatch(w)]
    if digits:
        values.update(float(word) for word in digits)
        # A number a transcriber wrote in pieces: "1, 250" or "3 .5".
        if len(digits) > 1 and all(d.isdigit() for d in digits):
            values.add(float("".join(digits)))
            if len(digits) == 2:
                values.add(float(".".join(digits)))
        return frozenset(values)
    spoken = [w for w in words if w not in {"and", "point"}]
    if "point" in words:
        index = words.index("point")
        whole = _cardinal([w for w in words[:index] if w != "and"])
        fraction = "".join(str(_SMALL.get(w, "")) for w in words[index + 1 :])
        if whole is not None and fraction.isdigit():
            values.add(float(f"{int(whole)}.{fraction}"))
    cardinal = _cardinal(spoken)
    if cardinal is not None:
        values.add(cardinal)
    # A year said in pairs: "nineteen eighty seven", "twenty twelve".
    for split in range(1, len(spoken)):
        high, low = _cardinal(spoken[:split]), _cardinal(spoken[split:])
        # Also "three sixty five" (365) and "nine eleven" (911).
        if high is not None and low is not None and 1 <= high < 100 and low < 100:
            values.add(high * 100 + low)
    return frozenset(values)


def tokenize(words: Iterable[Word]) -> list[Token]:
    """Normalize timed words; adjacent number words or digits become one number token."""
    tokens: list[Token] = []
    pending: list[tuple[str, Word]] = []

    def flush() -> None:
        # Joiners ("and", "point") that end a run belong to the text after it.
        trailing: list[tuple[str, Word]] = []
        while pending and pending[-1][0] in {"and", "point"}:
            trailing.insert(0, pending.pop())
        if pending:
            raw = [word for word, _ in pending]
            tokens.append(
                Token(
                    "#",
                    " ".join(dict.fromkeys(source.text for _, source in pending)),
                    pending[0][1].start,
                    pending[-1][1].end,
                    _values(raw),
                )
            )
            pending.clear()
        for word, source in trailing:
            tokens.append(Token(word, source.text, source.start, source.end))

    for source in words:
        for word in _words(source.text):
            numeric = bool(_DIGITS.fullmatch(word)) or word in _NUMBER_WORDS
            joiner = word in {"and", "point"} and bool(pending)
            if numeric or joiner:
                pending.append((word, source))
                continue
            flush()
            tokens.append(
                Token(_spelling(word.replace("'", "")), source.text, source.start, source.end)
            )
    flush()
    return tokens


def tokenize_text(text: str) -> list[Token]:
    """Normalize reference text (no timings)."""
    return tokenize(Word(word) for word in text.split())


def _dissimilar(expected: Sequence[Token], spoken: Sequence[Token]) -> bool:
    """Whether a substitution's words differ by more than a transcriber's near-miss."""
    if any(t.key == "#" for t in (*expected, *spoken)):
        return True
    a = "".join(t.key for t in expected)
    b = "".join(t.key for t in spoken)
    return difflib.SequenceMatcher(a=a, b=b, autojunk=False).ratio() < DISSIMILAR


def _same_number(a: Token, b: Token) -> bool:
    return not a.values or not b.values or bool(a.values & b.values)


def differences(
    model: ModelName, reference: Sequence[Token], heard: Sequence[Token]
) -> list[Difference]:
    """Where `heard` differs from `reference`, at least `MIN_WORDS` long."""
    found: list[Difference] = []

    def add(
        kind: DifferenceKind, i1: int, i2: int, j1: int, j2: int, *, force: bool = False
    ) -> None:
        if not force and kind == "substitution" and not _dissimilar(reference[i1:i2], heard[j1:j2]):
            return
        if not force and max(i2 - i1, j2 - j1) < MIN_WORDS:
            one_word = kind == "substitution" and i2 - i1 == 1 and j2 - j1 == 1
            if not (one_word and len(reference[i1].key) >= MIN_LETTERS):
                return
        # A compound written as one word or two ("logbook", "log book") is the same speech.
        if (
            not force
            and i2 > i1
            and j2 > j1
            and "".join(t.key for t in reference[i1:i2]) == "".join(t.key for t in heard[j1:j2])
        ):
            return
        spoken = heard[j1:j2]
        if spoken:
            start, end = spoken[0].start, spoken[-1].end
        else:
            # An omission sits between the words around it.
            start = heard[j1 - 1].end if 0 < j1 <= len(heard) else None
            end = heard[j1].start if j1 < len(heard) else start
        found.append(
            Difference(
                model,
                kind,
                i1,
                i2,
                " ".join(t.display for t in reference[i1:i2]),
                " ".join(t.display for t in spoken),
                start,
                end,
            )
        )

    for tag, i1, i2, j1, j2 in opcodes([t.key for t in reference], [t.key for t in heard]):
        if tag == "equal":
            # Numbers align by their placeholder; a different value is a substitution.
            for offset in range(i2 - i1):
                ref, hyp = reference[i1 + offset], heard[j1 + offset]
                if ref.key == "#" and not _same_number(ref, hyp):
                    add(
                        "substitution",
                        i1 + offset,
                        i1 + offset + 1,
                        j1 + offset,
                        j1 + offset + 1,
                        force=True,
                    )
            continue
        kind: DifferenceKind = {
            "insert": "insertion",
            "delete": "omission",
            "replace": "substitution",
        }[tag]  # type: ignore[assignment]
        add(kind, i1, i2, j1, j2)
    return found


# Above this many alignment cells (reference words x heard words), split at an anchor first.
_MAX_CELLS = 40_000_000
_ANCHOR_WORDS = 8


def _edit_steps(ref: Sequence[str], hyp: Sequence[str]) -> list[str]:
    """Word edit-distance alignment as steps: "=" match, "s" substitute, "d" omit, "i" insert."""
    ids: dict[str, int] = {}
    a = np.array([ids.setdefault(w, len(ids)) for w in ref], dtype=np.int64)
    b = np.array([ids.setdefault(w, len(ids)) for w in hyp], dtype=np.int64)
    n, m = len(a), len(b)
    columns = np.arange(m + 1)
    previous = columns.astype(np.int64)
    # 0 diagonal, 1 from above (omission), 2 from the left (insertion).
    moves = np.zeros((n + 1, m + 1), dtype=np.uint8)
    moves[0, 1:] = 2
    for i in range(1, n + 1):
        diagonal = previous[:-1] + (b != a[i - 1])
        above = previous[1:] + 1
        row = np.empty(m + 1, dtype=np.int64)
        row[0] = i
        row[1:] = np.minimum(diagonal, above)
        step = np.where(diagonal <= above, 0, 1).astype(np.uint8)
        # Insertions run along the row: row[j] = min(row[j], row[j-1] + 1).
        best = np.minimum.accumulate(row - columns) + columns
        moves[i, 0] = 1
        moves[i, 1:] = np.where(best[1:] < row[1:], 2, step)
        previous = best
    steps: list[str] = []
    i, j = n, m
    while i or j:
        move = moves[i, j]
        if move == 0:
            steps.append("=" if a[i - 1] == b[j - 1] else "s")
            i, j = i - 1, j - 1
        elif move == 1:
            steps.append("d")
            i -= 1
        else:
            steps.append("i")
            j -= 1
    steps.reverse()
    return steps


def _anchor(ref: Sequence[str], hyp: Sequence[str]) -> tuple[int, int, int] | None:
    """A long exact match near the middle of `ref` to split a very long alignment at."""
    matcher = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size >= _ANCHOR_WORDS]
    if not blocks:
        return None
    middle = len(ref) / 2
    block = min(blocks, key=lambda b: abs(b.a + b.size / 2 - middle))
    return block.a, block.b, block.size


def opcodes(ref: Sequence[str], hyp: Sequence[str]) -> list[tuple[str, int, int, int, int]]:
    """`difflib`-style opcodes from an edit-distance alignment.

    Differences separated by a single matching word are merged, so an inserted phrase that
    happens to contain a word like "the" stays one difference.
    """
    if len(ref) * len(hyp) > _MAX_CELLS:
        anchor = _anchor(ref, hyp)
        if anchor is not None:
            i, j, size = anchor
            head = opcodes(ref[:i], hyp[:j])
            tail = [
                (tag, a1 + i + size, a2 + i + size, b1 + j + size, b2 + j + size)
                for tag, a1, a2, b1, b2 in opcodes(ref[i + size :], hyp[j + size :])
            ]
            return [*head, ("equal", i, i + size, j, j + size), *tail]
    steps = _edit_steps(ref, hyp)
    # Merge a lone match between two differences into one difference.
    for k in range(1, len(steps) - 1):
        if steps[k] == "=" and steps[k - 1] != "=" and steps[k + 1] != "=":
            steps[k] = "s"
    codes: list[tuple[str, int, int, int, int]] = []
    i = j = 0
    k = 0
    while k < len(steps):
        start_i, start_j = i, j
        if steps[k] == "=":
            while k < len(steps) and steps[k] == "=":
                i, j, k = i + 1, j + 1, k + 1
            codes.append(("equal", start_i, i, start_j, j))
            continue
        while k < len(steps) and steps[k] != "=":
            i += steps[k] in "sd"
            j += steps[k] in "si"
            k += 1
        tag = "replace" if i > start_i and j > start_j else "delete" if i > start_i else "insert"
        codes.append((tag, start_i, i, start_j, j))
    return codes


def _near(a: Difference | Flag, b: Difference) -> bool:
    return a.ref_start - SLACK_WORDS <= b.ref_end and b.ref_start - SLACK_WORDS <= a.ref_end


def vote(reference: Sequence[Token], found: Mapping[ModelName, Sequence[Difference]]) -> list[Flag]:
    """Group differences by place; two or more model families make a confirmed flag.

    Only models in `found` voted; a failed or unavailable model is simply absent (spec §5).

    Grouping is anchored (AVF3): differences are taken in position order, and a difference
    joins a group only if it is within `SLACK_WORDS` of the group's first difference (the
    anchor), never merely of a later member. So a chain of nearby differences can't join into
    one place: with differences at 0, 2 and 4 and a tolerance of 2, the 0 and 2 may agree, and
    the one at 4 stands alone. Ties in position are broken by model order, so the result is
    deterministic.
    """
    order = {name: index for index, name in enumerate(found)}
    pool = sorted(
        (d for diffs in found.values() for d in diffs),
        key=lambda d: (d.ref_start, d.ref_end, order[d.model]),
    )
    groups: list[list[Difference]] = []
    for difference in pool:
        for group in groups:
            if _near(group[0], difference):
                group.append(difference)
                break
        else:
            groups.append([difference])
    flags: list[Flag] = []
    for group in groups:
        models = tuple(sorted({d.model for d in group}, key=("whisper", "wav2vec2", "vosk").index))
        start = min(d.ref_start for d in group)
        end = max(d.ref_end for d in group)
        kinds = {d.kind for d in group}
        kind: DifferenceKind = kinds.pop() if len(kinds) == 1 else "substitution"
        times = [t for d in group for t in (d.start, d.end) if t is not None]
        flags.append(
            Flag(
                kind,
                start,
                end,
                " ".join(t.display for t in reference[start:end]),
                {d.model: d.heard for d in group},
                models,
                min(times) if times else None,
                max(times) if times else None,
                confirmed=len(models) >= 2,
            )
        )
    return flags


def chapter_outcome(
    runs: Sequence[ModelRun], flags: Sequence[Flag]
) -> tuple[ChapterStatus, str | None, bool]:
    """A chapter's status, reason and whether it is partial, from its model runs and flags.

    Models that failed or were unavailable abstain (spec §5). With fewer than three voting
    families the result is partial and never a three-way majority (spec §3); with none, the
    chapter is `verification_unavailable`.
    """
    voted = [run for run in runs if run.outcome == "ok"]
    if not voted:
        reasons = {run.reason for run in runs}
        reason = "cancelled" if "cancelled" in reasons else "no_models"
        return "verification_unavailable", reason, True
    partial = len({run.model for run in voted}) < len(MODEL_NAMES)
    if any(flag.confirmed for flag in flags):
        return "possible_mismatch", None, partial
    if flags:
        return "model_disagreement", None, partial
    return "no_mismatch_detected", None, partial
