"""Build a small original demo book for README screenshots."""

import sys

import pymupdf

TITLE = "The Lighthouse at Gull Point"
CHAPTERS = [
    (
        "Chapter 1: The Keeper",
        [
            "Mara Quill had kept the light at Gull Point for eleven winters. Each evening she "
            "climbed the ninety-two steps, trimmed the wick and wound the clockwork that turned "
            "the great lens.",
            "The village below trusted the beam the way it trusted the tide. Fishing boats came "
            "home by it, and children learned to count by its slow, patient flashes.",
            "On the night the storm arrived, the barometer fell faster than she had ever seen. "
            "Mara wrote the reading in her logbook and underlined it twice.",
        ],
    ),
    (
        "Chapter 2: The Storm",
        [
            "By midnight the wind had torn the shutters from the oil store. Rain struck the "
            "lantern glass so hard that the beam seemed to bend.",
            "Then the clockwork stopped. The lens hung still, throwing a single fixed ray across "
            "the water, and a fixed ray tells a sailor nothing at all.",
            "Mara took the crank in both hands and began to turn it herself, counting the "
            "seconds of each flash aloud so that she would not lose the rhythm.",
        ],
    ),
    (
        "Chapter 3: Morning",
        [
            "She turned the crank until her arms shook, and then she turned it some more. "
            "Somewhere past four o'clock the rain thinned to a drizzle.",
            "At dawn the harbour master climbed the steps with bread and a flask of tea. Every "
            "boat, he said, had come home.",
            "Mara opened her logbook, wrote the time, and under it a single word: kept.",
        ],
    ),
]


def build(path: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 260, 540, 330), TITLE, fontsize=26, align=1)
    page.insert_textbox(pymupdf.Rect(72, 340, 540, 370), "A short demo story", fontsize=14, align=1)
    for heading, paragraphs in CHAPTERS:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(72, 90, 540, 130), heading, fontsize=20)
        y = 150
        for paragraph in paragraphs:
            rect = pymupdf.Rect(72, y, 540, y + 90)
            page.insert_textbox(rect, paragraph, fontsize=12, lineheight=1.4)
            y += 100
    # Fixed dates and no new file ID keep the bytes, and so the workspace name, stable.
    fixed = "D:20260101000000Z"
    doc.set_metadata(
        {"title": TITLE, "author": "pdf2audiobook demo", "creationDate": fixed, "modDate": fixed}
    )
    doc.save(path, no_new_id=True, garbage=3, deflate=True)


if __name__ == "__main__":
    build(sys.argv[1])
