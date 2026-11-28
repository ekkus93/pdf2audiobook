"""The `pdf2audiobook` command line, split by command family.

`pdf2audiobook.cli:main` is the entry point. The Typer apps and the shared output and error
helpers live in `_core`; each command module adds its commands to those apps when it is
imported. Typer lists commands in registration order, which is the order `--help` shows, so
the registration imports below are kept in that order and exempt from import sorting.

Only the names the rest of the code and the tests use are re-exported. Code that patches a
helper must patch the module where the command looks it up (for example
`pdf2audiobook.cli.info.load_settings`), not this package.
"""

# isort: off
from pdf2audiobook.cli import verify  # noqa: F401  (registration order, see above)
from pdf2audiobook.cli import info  # noqa: F401
from pdf2audiobook.cli import configuration  # noqa: F401
from pdf2audiobook.cli import tts_models  # noqa: F401
from pdf2audiobook.cli import llm_models  # noqa: F401
from pdf2audiobook.cli import analyze  # noqa: F401
from pdf2audiobook.cli import convert  # noqa: F401
from pdf2audiobook.cli import batch  # noqa: F401
from pdf2audiobook.cli import pack  # noqa: F401
from pdf2audiobook.cli import repair  # noqa: F401
from pdf2audiobook.cli import review  # noqa: F401
from pdf2audiobook.cli import asr  # noqa: F401
from pdf2audiobook.cli import budget  # noqa: F401
from pdf2audiobook.cli import edits  # noqa: F401
from pdf2audiobook.cli import addons  # noqa: F401

# isort: on
from pdf2audiobook.cli._core import CONVERSION_STATUS_MAX_BYTES, app, fail, main
from pdf2audiobook.cli.info import LLM_INSTRUCTIONS_ALLOWANCE
from pdf2audiobook.cli.options import parse_chapter_range

__all__ = [
    "CONVERSION_STATUS_MAX_BYTES",
    "LLM_INSTRUCTIONS_ALLOWANCE",
    "app",
    "fail",
    "main",
    "parse_chapter_range",
]
