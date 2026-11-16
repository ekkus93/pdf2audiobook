"""`edits list`, `accept` and `reject`: pending LLM edits."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape

from pdf2audiobook.cli._core import ClickExit, console, edits_app, emit, fail, fail_interrupted
from pdf2audiobook.logging import (
    set_output_mode,
)


@edits_app.command("list", epilog="Example: pdf2audiobook edits list MANIFEST --status all")
def edits_list(
    manifest_path: Path = typer.Argument(..., help="A generated manifest.json."),
    status: str = typer.Option("pending", "--status", help="pending, accepted, rejected or all."),
    with_text: bool = typer.Option(
        False,
        "--with-text",
        help="With --json, also include each edit's original and proposed text and its reason.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List edits. --json carries IDs and statuses; book text only with --with-text."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.edit_review import list_edits

        rows = list_edits(manifest_path, status=status)
        if json_output:
            emit(
                {
                    "edits": [
                        {
                            "block_id": row.block_id,
                            "chapter": row.chapter,
                            "provider": row.provider,
                            "status": row.status,
                            # Model-written reasons can echo book text; fixed ones cannot.
                            **(
                                {"reason": row.reason}
                                if row.provider == "deterministic" or with_text
                                else {}
                            ),
                            # Book text only when explicitly asked for (the desktop app's
                            # pending-edits screen); never by default.
                            **(
                                {"original": row.original, "replacement": row.replacement}
                                if with_text
                                else {}
                            ),
                        }
                        for row in rows
                    ]
                },
                True,
            )
        else:
            for row in rows:
                # Book text and model-written reasons are data, never Rich markup.
                console.print(
                    f"[bold]{escape(row.block_id)}[/bold] chapter {row.chapter} · "
                    f"{escape(row.provider)} · {row.status}\n"
                    f"  was: {escape(row.original)}\n  now: {escape(row.replacement)}\n"
                    f"  why: {escape(row.reason)}",
                    markup=True,
                    highlight=False,
                )
            console.print(f"{len(rows)} edit(s)")
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


def _edit_decision(
    action: str,
    manifest_path: Path,
    block_ids: list[str] | None,
    all_edits: bool,
    json_output: bool,
) -> None:
    if bool(block_ids) == all_edits:
        raise typer.BadParameter("Name one or more block IDs, or pass --all")
    set_output_mode(json_output)
    try:
        from pdf2audiobook.edit_review import accept_edits, reject_edits

        changed = (accept_edits if action == "accepted" else reject_edits)(
            manifest_path, None if all_edits else block_ids
        )
        key = "accepted" if action == "accepted" else "rejected"
        if json_output:
            emit({key: changed}, True)
        else:
            console.print(f"{key.capitalize()} {len(changed)} edit(s)")
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)


@edits_app.command("accept", epilog="Example: pdf2audiobook edits accept MANIFEST --all")
def edits_accept(
    manifest_path: Path = typer.Argument(..., help="A generated manifest.json."),
    block_ids: list[str] | None = typer.Argument(None, help="Block IDs to accept."),
    all_edits: bool = typer.Option(False, "--all", help="Accept every pending edit."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Accept pending edits; their chapters are regenerated and their audio goes stale."""
    _edit_decision("accepted", manifest_path, block_ids, all_edits, json_output)


@edits_app.command("reject", epilog="Example: pdf2audiobook edits reject MANIFEST BLOCK_ID")
def edits_reject(
    manifest_path: Path = typer.Argument(..., help="A generated manifest.json."),
    block_ids: list[str] | None = typer.Argument(None, help="Block IDs to reject."),
    all_edits: bool = typer.Option(False, "--all", help="Reject every pending edit."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove pending edits. Accepted edits cannot be rejected."""
    _edit_decision("rejected", manifest_path, block_ids, all_edits, json_output)
