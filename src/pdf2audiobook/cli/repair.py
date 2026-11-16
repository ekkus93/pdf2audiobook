"""Chapter repair: `resynthesize`, `regenerate-chapter` and `recover`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from pdf2audiobook.cli._core import (
    ClickExit,
    app,
    emit,
    fail,
    fail_interrupted,
)
from pdf2audiobook.logging import (
    set_output_mode,
)


@app.command(
    "regenerate-chapter",
    epilog="Example: pdf2audiobook regenerate-chapter ./audiobooks/BOOK/manifest.json --chapter 3",
)
def regenerate_chapter(
    manifest_path: Path = typer.Argument(..., help="A generated manifest.json."),
    chapter: list[int] | None = typer.Option(
        None, "--chapter", min=1, help="Chapter number to regenerate (repeatable)."
    ),
    all_conflicts: bool = typer.Option(
        False, "--all-conflicts", help="Regenerate every chapter that currently blocks planning."
    ),
    footnotes: str | None = typer.Option(
        None,
        "--footnotes",
        help="warn, inline, end or omit: policy for a legacy workspace that cannot be inferred.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Replace a chapter file with generated text, keeping a backup of any differing file."""
    if bool(chapter) == all_conflicts:
        raise typer.BadParameter("Use either --chapter (repeatable) or --all-conflicts")
    if footnotes is not None and footnotes not in {"warn", "inline", "end", "omit"}:
        raise typer.BadParameter("--footnotes must be warn, inline, end or omit")
    set_output_mode(json_output)
    try:
        from pdf2audiobook.chapter_recovery import regenerate_chapters

        result = regenerate_chapters(
            manifest_path, chapter or [], all_conflicts=all_conflicts, footnotes=footnotes
        )
        payload: dict[str, Any] = {
            "regenerated": list(result.regenerated),
            "backed_up": list(result.backed_up),
        }
        if not json_output:
            payload["backup_files"] = list(result.backup_files)
        emit(payload, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@app.command(epilog="Example: pdf2audiobook recover ./audiobooks/BOOK/manifest.json")
def recover(
    manifest_path: Path = typer.Argument(..., help="A generated manifest.json."),
    back_up_changed: bool = typer.Option(
        False,
        "--back-up-changed",
        help="Keep copies of files changed after an interrupted update, then finish it.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Complete an interrupted workspace update."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.review_transaction import recover_review_transaction
        from pdf2audiobook.workspace import workspace_lock

        with workspace_lock(manifest_path.parent, recover=False):
            report = recover_review_transaction(
                manifest_path.parent, back_up_changed=back_up_changed
            )
        payload = {"status": report.status, "backed_up": list(report.backed_up)}
        if not json_output:
            payload["backup_files"] = list(report.backup_files)
        emit(payload, json_output)
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
