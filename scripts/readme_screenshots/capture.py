"""Save one pdf2audiobook command and its terminal output as an SVG screenshot.

Usage:
    capture.py OUT.svg BOOKS_DIR PROJECT_DIR [--log FILE] -- ARGS...

Runs ``uv run pdf2audiobook ARGS`` in BOOKS_DIR, or with ``--log`` shows the
contents of FILE as that command's output instead of running it (for the
review server, which keeps running). BOOKS_DIR is shown as ``~/books``.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.text import Text


def main(argv: list[str]) -> int:
    split = argv.index("--")
    options, args = argv[:split], argv[split + 1 :]
    out_svg, books, project = options[0], options[1], options[2]
    log = options[options.index("--log") + 1] if "--log" in options else None
    code = 0
    if log is None:
        env = dict(os.environ, COLUMNS="100", FORCE_COLOR="1", TERM="xterm-256color")
        proc = subprocess.run(
            ["uv", "run", "--project", project, "pdf2audiobook", *args],
            cwd=books,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        output, code = proc.stdout + proc.stderr, proc.returncode
    else:
        output = Path(log).read_text()
    output = output.replace(books, "~/books").rstrip()

    shown = " ".join(f'"{arg}"' if " " in arg else arg for arg in args)
    console = Console(
        file=io.StringIO(), record=True, width=100, force_terminal=True, color_system="truecolor"
    )
    console.print(
        Text("$ ", style="bold green") + Text(f"uv run pdf2audiobook {shown}", style="bold")
    )
    console.print(Text.from_ansi(output))
    if code:
        console.print(Text(f"(exit status {code})", style="dim"))
    console.save_svg(out_svg, title="pdf2audiobook")
    print(f"{Path(out_svg).name}: exit {code}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
