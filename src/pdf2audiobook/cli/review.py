"""`review`: the chapter review page."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from pdf2audiobook.cli._core import ClickExit, app, console, fail, fail_interrupted
from pdf2audiobook.errors import (
    ConfigError,
    WorkspaceError,
)
from pdf2audiobook.logging import (
    set_output_mode,
)


@app.command(epilog="Example: pdf2audiobook review ./audiobooks/BOOK/manifest.json")
def review(
    manifest_path: Path = typer.Argument(..., help="A generated manifest.json to review."),
    port: int = typer.Option(8765, "--port", min=0, max=65535),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Open a loopback-only browser editor for chapter titles and boundaries."""
    set_output_mode(json_output)
    try:
        from pdf2audiobook.review_ui import create_review_server

        if not manifest_path.is_file():
            raise WorkspaceError("Cannot create the output workspace")
        try:
            server = create_review_server(manifest_path, port=port)
        except OSError:
            raise ConfigError("Review server port is unavailable; choose another --port") from None
        bound_port = server.server_address[1]
        url = f"http://127.0.0.1:{bound_port}/"
        if json_output:
            # One line, flushed now: a caller reads it while the server keeps running.
            typer.echo(json.dumps({"url": url, "port": bound_port}))
            sys.stdout.flush()
        else:
            console.print(f"Chapter review UI: {url}")
            console.print("Press Ctrl+C to stop the local review server.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            # Stopping the server is how the review session normally ends.
            if not json_output:
                console.print("Review server stopped.")
        finally:
            server.server_close()
    except KeyboardInterrupt:
        fail_interrupted(json_output=json_output)
    except (typer.Exit, ClickExit):
        raise
    except Exception as exc:
        fail(exc, json_output=json_output)
