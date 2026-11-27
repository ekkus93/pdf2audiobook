"""Resources shipped inside the desktop app's bundled engine (self-contained app spec SC1, SC4).

The desktop app carries its own Python, FFmpeg, OCR language data and default voice model.
A marker file next to the bundled interpreter says so. Outside a bundle nothing here applies,
so a CLI installed with uv behaves exactly as before.
"""

import os
import re
import sys
from collections.abc import MutableMapping
from pathlib import Path

MARKER = "pdf2audiobook-bundle.json"
_MODEL_FOLDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def bundle_root() -> Path | None:
    """The bundled engine's root (the interpreter's prefix), or None outside a bundle."""
    root = Path(sys.prefix)
    return root if (root / MARKER).is_file() else None


def configure_environment(environ: MutableMapping[str, str] = os.environ) -> None:
    """Put the bundle's tools first on PATH and point OCR at its language data.

    A TESSDATA_PREFIX the user set is kept. Calling this again changes nothing.
    """
    root = bundle_root()
    if root is None:
        return
    tools = str(root / "bin")
    path = environ.get("PATH", "")
    if tools not in path.split(os.pathsep):
        environ["PATH"] = f"{tools}{os.pathsep}{path}" if path else tools
    tessdata = root / "share" / "tessdata"
    if "TESSDATA_PREFIX" not in environ and tessdata.is_dir():
        environ["TESSDATA_PREFIX"] = str(tessdata)
    from pdf2audiobook.addons import activate

    activate(environ)


def bundled_model(model_id: str) -> Path | None:
    """The bundled copy of a Kitten model repository, by its Hugging Face ID, if shipped."""
    root = bundle_root()
    name = model_id.rsplit("/", 1)[-1]
    if root is None or not _MODEL_FOLDER.match(name):
        return None
    folder = root / "share" / "pdf2audiobook" / "models" / name
    return folder if (folder / "config.json").is_file() else None
