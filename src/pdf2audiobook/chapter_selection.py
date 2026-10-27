"""Chapter selection and review gates shared by conversion and packaging."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pdf2audiobook.config import Settings
from pdf2audiobook.document.structure import chapter_has_speakable_text
from pdf2audiobook.errors import AudioError
from pdf2audiobook.logging import log_event
from pdf2audiobook.models import BookManifest, Chapter
from pdf2audiobook.review_reasons import BOOK_WIDE_REVIEW_REASON_CODES
from pdf2audiobook.workspace import write_manifest


def refresh_empty_chapter_reason(
    manifest_path: Path,
    manifest: BookManifest,
    *,
    persist: bool = True,
    speakability: dict[str, bool] | None = None,
) -> None:
    """Recompute the empty-chapter review reason from the manifest as it is now.

    Analysis only knew the chapters it proposed; a hand edit or a review-UI save
    can empty a chapter later, or fix one that was empty.
    """
    if "empty_chapter" in manifest.review_acknowledged:
        log_event(
            "review_warning",
            level=logging.WARNING,
            reason="empty_chapter_requires_approval",
        )
    if not manifest.blocks:
        return  # No source blocks to judge; coverage validation reports this elsewhere.
    replacements = {edit.block_id: edit.replacement for edit in manifest.edits if edit.accepted}
    has_empty = any(
        not (
            speakability[chapter.id]
            if speakability is not None
            else chapter_has_speakable_text(
                manifest.blocks, chapter.start_block, chapter.end_block, replacements
            )
        )
        for chapter in manifest.chapters
    )
    needed = has_empty
    required = [code for code in manifest.review_required if code != "empty_chapter"]
    if needed:
        required = manifest.review_required + (
            [] if "empty_chapter" in manifest.review_required else ["empty_chapter"]
        )
    if persist and required != manifest.review_required:
        manifest.review_required = required
        write_manifest(manifest_path, manifest)
    else:
        manifest.review_required = required


def select_chapters(
    manifest: BookManifest,
    settings: Settings,
    *,
    chapter: int | None = None,
    chapter_range: tuple[int, int] | None = None,
    speakability: dict[str, bool] | None = None,
) -> list:
    """Validate chosen chapters before loading or downloading a speech model."""
    if chapter is not None and chapter_range is not None:
        raise AudioError("--chapter and --chapter-range cannot be combined")
    count = len(manifest.chapters)
    if chapter_range is not None:
        first, last = chapter_range
        if first < 1 or last < first or last > count:
            raise AudioError(
                f"Chapter range {first}:{last} is outside the book's 1:{count} chapters"
            )
        chosen = [c for c in manifest.chapters if first <= c.number <= last]
    elif chapter is not None:
        chosen = [c for c in manifest.chapters if c.number == chapter]
    else:
        chosen = list(manifest.chapters)
    if not chosen:
        raise AudioError(f"Chapter {chapter} does not exist")
    for item in chosen:
        if (
            "empty_chapter" in manifest.review_required
            and not (
                speakability[item.id]
                if speakability is not None
                else chapter_has_speakable_text(
                    manifest.blocks,
                    item.start_block,
                    item.end_block,
                    {edit.block_id: edit.replacement for edit in manifest.edits if edit.accepted},
                )
            )
            and not item.manually_approved
        ):
            raise AudioError(
                f"Chapter {item.number} has no speakable text; review and approve it before synthesis"
            )
        if (
            "damaged_source" in manifest.review_required
            and "damaged_source" not in manifest.review_acknowledged
        ):
            raise AudioError(
                f"Chapter {item.number} comes from a damaged source; "
                "review and approve it before synthesis"
            )
        if (
            "ambiguous_page_numbers" in manifest.review_required
            and "ambiguous_page_numbers" not in manifest.review_acknowledged
        ):
            raise AudioError(
                f"Chapter {item.number} has ambiguous page-number cleanup; review and approve it"
            )
        if item.confidence < settings.chapters.min_boundary_confidence and not (
            item.manually_approved or settings.chapters.allow_single_chapter
        ):
            raise AudioError(
                f"Chapter {item.number} has low boundary confidence; "
                "review the manifest before synthesis"
            )
    return chosen


@dataclass(frozen=True)
class ChapterSelection:
    """Chapters approved for conversion and empty chapters intentionally skipped."""

    chapters: list[Chapter]
    skipped: list[Chapter]
    acknowledged: list[str]
    would_acknowledge: list[str]


def prepare_chapter_selection(
    manifest_path: Path,
    manifest: BookManifest,
    settings: Settings,
    *,
    chapter: int | None = None,
    chapter_range: tuple[int, int] | None = None,
    acknowledge: tuple[str, ...] = (),
    persist: bool = False,
    footnotes: str | None = None,
    selector: Callable[..., list[Chapter]] = select_chapters,
) -> ChapterSelection:
    """Refresh review gates and select converted, skipped and refused chapters."""
    previous_review_required = list(manifest.review_required)
    previous_acknowledged = list(manifest.review_acknowledged)
    from pdf2audiobook.audio import has_speakable_chapter_narration
    from pdf2audiobook.chapter_artifacts import (
        load_artifact_state,
        plan_chapter_artifacts,
        resolve_footnote_policy,
    )

    state = load_artifact_state(manifest_path.parent)
    speakability: dict[str, bool] | None = None
    if state is not None or (
        manifest_path.is_file() and manifest.blocks and (manifest_path.parent / "chapters").is_dir()
    ):
        if footnotes is not None:
            policy = footnotes
        elif state is not None:
            policy = settings.pdf.footnotes
        else:
            policy = resolve_footnote_policy(manifest, manifest_path.parent)
        plan = plan_chapter_artifacts(manifest, manifest_path.parent, policy)
        speakability = {}
        for item in manifest.chapters:
            name = f"{item.number:03d}.txt"
            try:
                text = (
                    plan.writes[name].decode("utf-8")
                    if name in plan.writes
                    else (manifest_path.parent / "chapters" / name).read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError):
                raise AudioError(
                    "Cannot read approved chapter text; check workspace files"
                ) from None
            try:
                speakability[item.id] = has_speakable_chapter_narration(text)
            except AudioError:
                # Leave invalid markers to per-chapter voice preflight.
                speakability[item.id] = True
    refresh_empty_chapter_reason(manifest_path, manifest, persist=False, speakability=speakability)
    requested_acknowledgements = set(acknowledge)
    if not requested_acknowledgements <= set(BOOK_WIDE_REVIEW_REASON_CODES):
        raise AudioError("Unknown review reason code")
    acknowledged = sorted(requested_acknowledgements)
    would_acknowledge = sorted(requested_acknowledgements & set(manifest.review_required))
    for code in acknowledged:
        log_event("review_acknowledged", level=logging.INFO, status=code)
    if acknowledged:
        manifest.review_acknowledged = sorted(set(manifest.review_acknowledged) | set(acknowledged))
        manifest.review_required = [
            code for code in manifest.review_required if code not in set(acknowledged)
        ]
    if persist and (
        manifest.review_required != previous_review_required
        or manifest.review_acknowledged != previous_acknowledged
    ):
        write_manifest(manifest_path, manifest)

    chosen = selector(
        manifest, settings, chapter=chapter, chapter_range=chapter_range, speakability=speakability
    )
    replacements = {edit.block_id: edit.replacement for edit in manifest.edits if edit.accepted}
    skipped = [
        item
        for item in chosen
        if (
            "empty_chapter" in manifest.review_required
            and item.manually_approved
            and not (
                speakability[item.id]
                if speakability is not None
                else chapter_has_speakable_text(
                    manifest.blocks, item.start_block, item.end_block, replacements
                )
            )
        )
    ]
    return ChapterSelection(chosen, skipped, acknowledged, would_acknowledge)
