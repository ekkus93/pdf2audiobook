"""Render source-aligned chapter narration and footnote placement."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from pdf2audiobook.document.listing import is_list_line
from pdf2audiobook.document.pagination import _valid_bbox
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest, Chapter, CleanupEdit, DocumentBlock

NOTE_MARKER = re.compile(r"^\s*(?P<marker>\d{1,3}|[*†‡§])")


def _anchor_pattern(marker: str) -> re.Pattern[str]:
    """A note anchor glued to a word or its punctuation: "world.5", "secrecy,26"."""
    return re.compile(rf"(?P<lead>[^\W\d_][.,;:!?\"'”’)\]]?){re.escape(marker)}(?!\d)")


def _unique_anchor(
    head: DocumentBlock, body: list[DocumentBlock], position: dict[str, int]
) -> int | None:
    """Index in body of the one line before the note, on its page, holding its anchor."""
    match = NOTE_MARKER.match(head.text)
    if match is None:
        return None
    anchor = _anchor_pattern(match.group("marker"))
    candidates = [
        index
        for index, block in enumerate(body)
        if block.page_index == head.page_index
        and position[block.id] < position[head.id]
        and len(anchor.findall(block.text)) == 1
    ]
    others = [
        block
        for block in body
        if block.page_index == head.page_index
        and position[block.id] < position[head.id]
        and anchor.search(block.text)
    ]
    return candidates[0] if len(candidates) == 1 and len(others) == 1 else None


def footnote_anchor_edits(blocks: list[DocumentBlock], edited: set[str]) -> list[CleanupEdit]:
    """Audited removal of note-anchor digits from narration ("world.5" -> "world.").

    Only an anchor that uniquely matches a classified note on its page is
    removed, only the marker characters are deleted, and blocks that already
    carry an accepted edit are left alone. Source blocks are never changed.
    """
    position = {block.id: index for index, block in enumerate(blocks)}
    body = [block for block in blocks if block.kind != "footnote"]
    markers: dict[int, list[str]] = defaultdict(list)
    for block in blocks:
        if block.kind != "footnote":
            continue
        index = _unique_anchor(block, body, position)
        if index is not None and body[index].id not in edited:
            match = NOTE_MARKER.match(block.text)
            assert match is not None
            markers[index].append(match.group("marker"))
    edits = []
    for index, found in sorted(markers.items()):
        original = body[index].text
        replacement = original
        for marker in found:
            replacement = _anchor_pattern(marker).sub(r"\g<lead>", replacement, count=1)
        if replacement != original:
            edits.append(
                CleanupEdit(
                    block_id=body[index].id,
                    original=original,
                    replacement=replacement,
                    reason="footnote anchor marker " + ", ".join(found) + " (note handled)",
                    confidence=0.9,
                    accepted=True,
                )
            )
    return edits


def footnote_omit_edits(blocks: list[DocumentBlock]) -> list[CleanupEdit]:
    """Create audited exclusions for blocks classified as footnotes."""
    return [
        CleanupEdit(
            block_id=block.id,
            original=block.text,
            replacement="",
            reason="explicit footnotes=omit policy (conservative classification)",
            confidence=0.9,
            accepted=True,
        )
        for block in blocks
        if block.kind == "footnote"
    ]


def place_footnotes(
    blocks: list[DocumentBlock], policy: str
) -> tuple[list[DocumentBlock], int, int]:
    """Reorder a chapter's classified footnotes for narration; never drop any.

    "end" moves every note after the chapter body. "inline" moves a note to
    the end of the paragraph holding its anchor ("world.5" for note "5 ...")
    when exactly one such anchor precedes it on the same page; otherwise the
    note keeps its PDF position. Other policies keep PDF order. Returns the
    narration order and the counts of relocated and kept-in-place notes
    (a note is its marker line plus continuation lines).
    """
    notes = [block for block in blocks if block.kind == "footnote"]
    # Group each numbered note with its unnumbered continuation lines; lines
    # before the first marker continue a note from the previous page.
    items: list[list[DocumentBlock]] = []
    for block in notes:
        if (
            NOTE_MARKER.match(block.text)
            or not items
            or items[-1][0].page_index != block.page_index
        ):
            items.append([block])
        else:
            items[-1].append(block)
    if policy not in {"inline", "end"} or not notes:
        return blocks, 0, len(items)
    body = [block for block in blocks if block.kind != "footnote"]
    if policy == "end":
        return body + notes, len(items), 0
    position = {block.id: index for index, block in enumerate(blocks)}
    after: dict[int, list[DocumentBlock]] = defaultdict(list)  # body index -> notes
    relocated = kept = 0
    for item in items:
        head = item[0]
        anchor_index = _unique_anchor(head, body, position)
        if anchor_index is not None:
            while anchor_index + 1 < len(body) and _is_wrapped_line(
                body[anchor_index],
                body[anchor_index + 1],
                body[anchor_index + 2] if anchor_index + 2 < len(body) else None,
            ):
                anchor_index += 1
            relocated += 1
        else:
            # Keep the PDF position: after the last body line that preceded it.
            anchor_index = max(
                (i for i, block in enumerate(body) if position[block.id] < position[head.id]),
                default=-1,
            )
            kept += 1
        after[anchor_index].extend(item)
    ordered = list(after.get(-1, []))
    for index, block in enumerate(body):
        ordered.append(block)
        ordered.extend(after.get(index, []))
    if sorted(position[block.id] for block in ordered) != list(range(len(blocks))):
        raise ExtractionError("Footnote placement must keep every source block exactly once")
    return ordered, relocated, kept


def render_chapter_narration(
    manifest: BookManifest, chapter: Chapter, footnotes: str = "warn"
) -> str:
    """Narration text of one chapter, rendered in memory from the current manifest."""
    replacements = {edit.block_id: edit.replacement for edit in manifest.edits if edit.accepted}
    chapter_blocks, _, _ = place_footnotes(
        manifest.blocks[chapter.start_block : chapter.end_block], footnotes
    )
    return reflow_narration_lines(
        chapter_blocks,
        replacements,
        supporting_text=" ".join(block.text for block in manifest.blocks),
    )


def render_chapter_texts(
    manifest: BookManifest, folder: Path, footnotes: str = "warn", *, commit_manifest: bool = False
) -> None:
    """Render generated text while preserving identified user edits."""
    from pdf2audiobook.chapter_artifacts import plan_chapter_artifacts
    from pdf2audiobook.review_transaction import commit_artifacts
    from pdf2audiobook.workspace import workspace_lock

    with workspace_lock(folder):
        plan = plan_chapter_artifacts(manifest, folder, footnotes)
        commit_artifacts(folder, plan, manifest=manifest if commit_manifest else None)


def _is_wrapped_line(
    before: DocumentBlock, after: DocumentBlock, after_next: DocumentBlock | None = None
) -> bool:
    """Join nearby consecutive body lines only when geometry supports a soft wrap."""
    if before.kind in {"heading", "table", "footnote", "caption", "equation"}:
        return False
    if after.kind in {"heading", "list", "table", "footnote", "caption", "equation"}:
        return False
    if not before.text.strip() or not after.text.strip():
        return False
    if after.page_index == before.page_index + 1:
        # A sentence running over a page break: no closing punctuation before
        # the break and a lowercase continuation after it (removed running
        # heads and folios between them are already skipped).
        return (
            not before.text.rstrip().endswith((".", "?", "!", ":", ";", '"', "”", "’", ")", "]"))
            and after.text.lstrip()[:1].islower()
        )
    if before.page_index != after.page_index or not before.bbox or not after.bbox:
        return False
    if not _valid_bbox(before.bbox) or not _valid_bbox(after.bbox):
        return False
    next_text = after.text.lstrip()
    markers = ("“", '"', "‘", "'", "—", "–", "•", "*", "§", "#")
    if next_text.startswith(markers) or before.text.strip().startswith(("*", "§", "#")):
        return False
    if before.text.rstrip().endswith(":") and (
        is_list_line(next_text) or re.match(r"^[-–—]\s+", next_text)
    ):
        return False
    # An initial before a name ("J. Smith") and a year before ")" ("1990) was")
    # are prose, which is_list_line already knows; real markers start a new line.
    if is_list_line(
        next_text,
        previous_text=before.text,
        next_text=after_next.text if after_next is not None else None,
    ) or re.match(r"^-\s+", next_text):
        return False
    if next_text.isupper() and len(next_text.split()) <= 8:
        return False
    line_height = max(1.0, before.bbox[3] - before.bbox[1])
    vertical_gap = after.bbox[1] - before.bbox[3]
    left_shift = after.bbox[0] - before.bbox[0]
    if before.kind == "list":
        # A list ends at a font change or at a line outdented from its items;
        # wrapped continuation lines stay at or inside the item's left edge.
        if (
            before.font_size is not None
            and after.font_size is not None
            and abs(float(before.font_size) - float(after.font_size)) > 0.5
        ):
            return False
        if left_shift < -2:
            return False
        # A sentence-final list item followed at the marker margin is followed
        # by a new body paragraph. A hanging continuation can remain flush-left
        # when the list item itself has no sentence-ending punctuation.
        if left_shift <= 2 and before.text.rstrip().endswith((".", "?", "!", ":", ";")):
            return False
    # Preserve indented paragraphs, section breaks and column transitions.
    return -2 <= vertical_gap <= 0.8 * line_height and abs(left_shift) <= max(12.0, line_height)


def reflow_narration_lines(
    blocks: list[DocumentBlock],
    replacements: dict[str, str] | None = None,
    *,
    supporting_text: str | None = None,
) -> str:
    """Preserve headings and breaks while joining clear PDF soft-wrapped body lines.

    No source blocks are mutated. A line-end hyphen is removed only when the
    joined word appears elsewhere without a hyphen in the source document.
    """
    replacements = replacements or {}
    corpus = supporting_text if supporting_text is not None else " ".join(b.text for b in blocks)
    corpus_words = {word.casefold() for word in re.findall(r"[^\W\d_]+", corpus)}
    paragraphs: list[str] = []
    current = ""
    previous: DocumentBlock | None = None
    for block_index, block in enumerate(blocks):
        text = replacements.get(block.id, block.text).strip()
        if not text:
            # An excluded running header/footer should not force a new paragraph.
            if not block.text.strip():
                if current:
                    paragraphs.append(current)
                    current = ""
                previous = None
            continue
        after_next = blocks[block_index + 1] if block_index + 1 < len(blocks) else None
        if current and previous is not None and _is_wrapped_line(previous, block, after_next):
            if current.endswith("\u00ad"):
                current = current[:-1] + text
            elif current.endswith("-") and text[:1].islower():
                match = re.search(r"([^\W\d_]+)-$", current)
                continuation = re.match(r"([^\W\d_]+)", text)
                if match and continuation:
                    if (match.group(1) + continuation.group(1)).casefold() in corpus_words:
                        current = current[:-1] + text
                    else:
                        current += text
                else:
                    current += " " + text
            else:
                current += " " + text
        else:
            if current:
                paragraphs.append(current)
            current = text
        previous = block
    if current:
        paragraphs.append(current)
    return "\n\n".join(paragraphs).strip() + "\n"
