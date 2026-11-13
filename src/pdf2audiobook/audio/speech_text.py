"""What narration text is spoken: speakability, voice markers, and sentence chunks
mapped back to their source ranges."""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping

from pdf2audiobook.audio.citations import mask_citations
from pdf2audiobook.errors import AudioError
from pdf2audiobook.narration import (
    _DASHES,
    NARRATION_TRANSLATION,
    normalize_narration_text,
)

_NARRATION_TRANSLATION = NARRATION_TRANSLATION


# Match pairs of logical line endings (CRLF, LF, or CR) with optional
# indentation between them. The same rule controls chunking and source spans.
_PARAGRAPH_BREAK = re.compile(r"(?>\r\n|\r|\n)[ \t]*(?>\r\n|\r|\n)+")


_VOICE_MARKER = re.compile(
    r"(?m)^\[\[voice:([A-Za-z0-9][A-Za-z0-9_.-]{0,127})\]\][ \t]*(?:\r?\n|$)"
)


_PRONUNCIATION_EDGE = {'"', "'", "(", ")", "[", "]", "{", "}", "<", ">"}


_PRONUNCIATION_TRAILING = {",", ";", ":", "!", "?", "…"}


_INVISIBLE = re.compile("[\u00ad\u200b\u200c\u200d\u2060\ufeff]")


def _droppable_word(word: str) -> bool:
    """Source words that legitimately produce no spoken token of their own."""
    return not _INVISIBLE.sub("", word).strip(_DASHES)


def _spoken_sequence(words: list[str], pronunciations: Mapping[str, str] | None) -> list[str]:
    """Spoken text for each source word of one paragraph.

    A word may speak as several tokens ("10–20" becomes "10 to 20") or as none
    (a bare dash only moves a comma onto the previous spoken word), so callers
    align on source words, never on token counts.
    """
    spoken: list[str] = []

    def attach_comma() -> None:
        for index in range(len(spoken) - 1, -1, -1):
            if spoken[index]:
                if not spoken[index].endswith((",", ";", ":", ".", "!", "?")):
                    spoken[index] += ","
                return

    for index, word in enumerate(words):
        core = word.strip(_DASHES)
        if not core:
            attach_comma()
            spoken.append("")
            continue
        if word[0] in _DASHES:
            attach_comma()
        text = _spoken_token(core, pronunciations, ends_paragraph=index == len(words) - 1)
        if word[-1] in _DASHES and text and not text.endswith((",", ";", ":", ".", "!", "?")):
            text += ","
        spoken.append(text)
    return spoken


def _unspeakable_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for match in _PARAGRAPH_BREAK.finditer(text):
        paragraph = text[cursor : match.start()]
        if paragraph.strip() and not has_speakable_narration(paragraph):
            ranges.append((cursor, match.start()))
        cursor = match.end()
    paragraph = text[cursor:]
    if paragraph.strip() and not has_speakable_narration(paragraph):
        ranges.append((cursor, len(text)))
    return ranges


def unspeakable_pause_ranges(
    chapter_text: str, *, skip_citations: bool = False
) -> list[tuple[int, int]]:
    """Source ranges of nonempty paragraphs without spoken letters or digits.

    With ``skip_citations`` a paragraph holding only citations counts as one.
    """
    masked = _voice_markers(chapter_text, "")[0]
    if skip_citations:
        masked = mask_citations(masked)
    return _unspeakable_ranges(masked)


def has_speakable_narration(text: str) -> bool:
    """Return whether the normalized spoken form contains a letter or digit."""
    normalized = normalize_narration_text(text)
    return any(char.isalnum() for char in normalized)


def _spoken_token(
    token: str,
    pronunciations: Mapping[str, str] | None = None,
    *,
    ends_paragraph: bool = True,
) -> str:
    normalized = normalize_narration_text(token)
    if not pronunciations:
        return normalized
    if any(dash in token for dash in "–—―") and ", " in normalized:
        pieces = re.split(r"(,\s*)", normalized)
        return "".join(
            piece
            if index % 2
            else _spoken_token(piece, pronunciations, ends_paragraph=ends_paragraph)
            for index, piece in enumerate(pieces)
        )
    start = 0
    end = len(normalized)
    while start < end and (
        normalized[start] in _PRONUNCIATION_EDGE
        or unicodedata.category(normalized[start]).startswith("Ps")
    ):
        start += 1
    while end > start and (
        normalized[end - 1] in _PRONUNCIATION_EDGE
        or normalized[end - 1] in _PRONUNCIATION_TRAILING
        or unicodedata.category(normalized[end - 1]).startswith("Pe")
    ):
        end -= 1
    core = normalized[start:end]
    # "..." and "…" are stripped before lookup and restored unchanged.
    ellipsis_match = re.search(r"\.{3,}$", core)
    ellipsis = ellipsis_match.group() if ellipsis_match else ""
    if ellipsis:
        core = core[: -len(ellipsis)]
    terminal_period = not ellipsis and core.endswith(".") and not normalized[end:].startswith(",")
    pronunciation_core = (core[:-1] if terminal_period else core).rstrip(".")
    spoken = pronunciations.get(core.casefold())
    # A key that includes the period owns it (an abbreviation's dot); otherwise
    # the period is the token's own sentence punctuation and is always kept.
    period_owned_by_key = spoken is not None and terminal_period
    if spoken is None:
        spoken = pronunciations.get(pronunciation_core.casefold())
    if spoken is None:
        return normalized
    if pronunciation_core.isalpha() and pronunciation_core.isupper():
        spoken = spoken.upper()
    elif pronunciation_core.isalpha() and pronunciation_core.istitle():
        spoken = spoken.capitalize()
    if ellipsis:
        suffix = ellipsis
    elif terminal_period and (ends_paragraph or not period_owned_by_key):
        suffix = "" if normalized[end:].startswith(("?", "!")) else "."
    else:
        suffix = ""
    return f"{normalized[:start]}{spoken}{suffix}{normalized[end:]}"


def _voice_markers(text: str, default_voice: str) -> tuple[str, list[tuple[int, str]]]:
    """Mask paragraph-level ``[[voice:ID]]`` markers and return source offsets."""
    changes: list[tuple[int, str]] = []
    masked = list(text)
    for match in _VOICE_MARKER.finditer(text):
        start, end = match.span()
        before = text[:start]
        after = text[end:]
        if before.strip() and not _PARAGRAPH_BREAK.search(before[-16:]):
            raise AudioError("Speaker markers must start a new paragraph")
        if after.strip() and not after.startswith(("\n", "\r")):
            raise AudioError("Speaker markers must end before a blank line")
        # Keep newlines and character offsets intact for source-range records.
        for index in range(start, end):
            if masked[index] not in "\r\n":
                masked[index] = " "
        changes.append((end, match.group(1)))
    voices = [(0, default_voice), *changes]
    return "".join(masked), voices


def voice_marker_ids(text: str) -> list[str]:
    """Validate marker placement and return explicit voice IDs in source order."""
    return [voice for _, voice in _voice_markers(text, "")[1][1:]]


def has_speakable_chapter_narration(text: str) -> bool:
    """Ignore voice control paragraphs when checking chapter narration."""
    return has_speakable_narration(_voice_markers(text, "")[0])


def split_sentences(
    text: str,
    max_chars: int = 350,
    pronunciations: Mapping[str, str] | None = None,
) -> list[str]:
    """Split at sentence/word boundaries without crossing source paragraphs."""
    if max_chars < 20:
        raise ValueError("max_chars must be at least 20")
    chunks: list[str] = []
    # Blank lines are semantic paragraph boundaries, including PDF-derived
    # CR-only line endings; a single soft wrap is not a paragraph break.
    for paragraph in _PARAGRAPH_BREAK.split(text.strip()):
        if not has_speakable_narration(paragraph):
            continue
        current = ""
        for word in _spoken_sequence(paragraph.split(), pronunciations):
            if len(word) > max_chars:
                raise AudioError("A single narration token exceeds the chunk limit")
            if current and len(current) + len(word) + 1 > max_chars:
                chunks.append(current)
                current = ""
            current = f"{current} {word}".strip()
            if word.endswith((".", "!", "?")) and len(current) >= max_chars // 2:
                chunks.append(current)
                current = ""
        if current:
            chunks.append(current)
    return chunks


def chunk_source_ranges(
    chapter_text: str,
    chunks: list[str],
    pronunciations: Mapping[str, str] | None = None,
) -> list[tuple[int, int, bool]]:
    """Map normalized spoken chunks to exact source character ranges, in order."""
    scene_ranges = _unspeakable_ranges(chapter_text)
    words = [
        match
        for match in re.finditer(r"\S+", chapter_text)
        if not any(start <= match.start() and match.end() <= end for start, end in scene_ranges)
    ]
    spoken: list[list[str]] = []
    group: list[re.Match[str]] = []
    for match in words:
        if group and _PARAGRAPH_BREAK.search(chapter_text[group[-1].end() : match.start()]):
            spoken.extend(
                part.split()
                for part in _spoken_sequence([item.group() for item in group], pronunciations)
            )
            group = []
        group.append(match)
    if group:
        spoken.extend(
            part.split()
            for part in _spoken_sequence([item.group() for item in group], pronunciations)
        )
    positions: list[tuple[int, int, bool]] = []
    cursor = 0
    previous_end = 0
    failure = "Narration chunk source alignment failed"
    for chunk in chunks:
        parts = chunk.split()
        if not parts:
            raise AudioError(failure)
        while cursor < len(words) and not spoken[cursor] and _droppable_word(words[cursor].group()):
            cursor += 1
        first = last = cursor
        index = 0
        while index < len(parts):
            if cursor >= len(words):
                raise AudioError(failure)
            tokens = spoken[cursor]
            if not tokens:
                if not _droppable_word(words[cursor].group()):
                    raise AudioError(failure)
            elif parts[index : index + len(tokens)] != tokens:
                raise AudioError(failure)
            else:
                index += len(tokens)
                last = cursor
            cursor += 1
        while (
            cursor < len(words)
            and not spoken[cursor]
            and _droppable_word(words[cursor].group())
            and not _PARAGRAPH_BREAK.search(chapter_text[words[last].end() : words[cursor].start()])
        ):
            last = cursor
            cursor += 1
        start, end = words[first].start(), words[last].end()
        paragraph_boundary = bool(_PARAGRAPH_BREAK.search(chapter_text[previous_end:start]))
        positions.append((start, end, paragraph_boundary))
        previous_end = end
    if any(
        spoken[rest] or not _droppable_word(words[rest].group())
        for rest in range(cursor, len(words))
    ):
        raise AudioError("Narration chunks do not cover all source words")
    return positions
