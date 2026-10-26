"""Shared character normalization for spoken text and pronunciation keys."""

import re

NARRATION_NORMALIZATION_VERSION = "narration-normalization-v1"
NARRATION_TRANSLATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "…": "...",
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬀ": "ff",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "st",
        "ﬆ": "st",
        "\u00a0": " ",
        "\u00ad": "",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\u2060": "",
        "\ufeff": "",
    }
)
_DASHES = "–—―"
_DASH_RUN = re.compile(rf"\s*[{_DASHES}]+\s*")


def normalize_narration_text(text: str) -> str:
    """Normalize supported typography and dash rewrites before TTS lookup."""
    text = text.translate(NARRATION_TRANSLATION)
    text = re.sub(r"(?<=\d)–(?=\d)", " to ", text)
    return _DASH_RUN.sub(", ", text)
