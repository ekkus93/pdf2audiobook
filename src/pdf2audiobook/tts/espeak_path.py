"""Keep espeak-ng's data path short enough for espeak-ng to read it.

espeak-ng (the phonemizer behind Kitten's ONNX voices) copies its data folder's path into a
160-byte buffer on Linux and silently cuts off anything longer. It then falls back to the
folder it was built in, which does not exist on this machine, and speech fails. `kittenml`
takes the path from `espeakng_loader.get_data_path()`; an engine installed or unpacked under a
long folder (an AppImage unpacking itself under a long `$TMPDIR`, say) makes that path too long.
When it is, the path handed out is a short private symbolic link to the same folder instead.
"""

from __future__ import annotations

import atexit
import importlib
import os
import shutil
import tempfile

# espeak-ng's `path_home` buffer (N_PATH_HOME on POSIX), including its terminating NUL.
BUFFER = 160
# espeak tries "<path>/espeak-ng-data" before "<path>", so leave room for that suffix.
LIMIT = BUFFER - len("/espeak-ng-data") - 1


def _fits(path: str) -> bool:
    return len(os.fsencode(path)) <= LIMIT


def shorten_espeak_data_path() -> None:
    """Point `espeakng_loader` at a short link to its data folder if its own path is too long.

    Call before `kittenml` loads its ONNX model, which reads the path once. Does nothing when
    `espeakng_loader` is not installed or its path already fits.
    """
    try:
        loader = importlib.import_module("espeakng_loader")
        data = str(loader.get_data_path())
    except Exception:
        return
    if _fits(data):
        return
    for base in (tempfile.gettempdir(), "/tmp"):
        try:
            folder = tempfile.mkdtemp(prefix="p2a-espeak-", dir=base)
        except OSError:
            continue
        link = os.path.join(folder, "data")
        if not _fits(link):
            shutil.rmtree(folder, ignore_errors=True)
            continue
        try:
            os.symlink(data, link)
        except OSError:
            shutil.rmtree(folder, ignore_errors=True)
            continue
        atexit.register(shutil.rmtree, folder, True)
        setattr(loader, "get_data_path", lambda: link)  # noqa: B010 (an untyped module)
        os.environ["ESPEAK_DATA_PATH"] = link
        return
