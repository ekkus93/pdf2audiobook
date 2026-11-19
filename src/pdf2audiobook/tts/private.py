"""Private voice jobs, with ownership markers and locks for safe crash cleanup."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from pathlib import Path
from types import TracebackType
from typing import IO

MARKER = "pdf2audiobook-private-voice-v1\n"


def private_root() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME", "")
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    if not base.is_absolute():
        base = Path.home() / ".cache"
    return base / "pdf2audiobook" / "private-voice"


def worker_supported() -> bool:
    return os.name == "posix"


def cleanup_private_jobs() -> None:
    if not worker_supported():
        return
    import fcntl

    root = private_root()
    try:
        if root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.getuid():
            return
        for path in root.glob("job-*"):
            if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid():
                continue
            marker = path / ".owner"
            if marker.is_symlink() or not marker.is_file():
                continue
            with os.fdopen(os.open(marker, os.O_RDWR | os.O_NOFOLLOW), "r+") as stream:
                if stream.read(128) != MARKER:
                    continue
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                shutil.rmtree(path)
    except OSError:
        # Never turn an ordinary read-only CLI command into a cache-permissions failure.
        return


class PrivateDirectory:
    def __init__(self, prefix: str = "voice") -> None:
        if not worker_supported():
            raise OSError("Local voice workers require POSIX process and file-lock support")
        import fcntl

        root = private_root()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink() or root.stat().st_uid != os.getuid():
            raise OSError("Unsafe private voice cache")
        root.chmod(0o700)
        cleanup_private_jobs()
        self.temporary = tempfile.TemporaryDirectory(prefix=f"job-{prefix}-", dir=root)
        self.name = self.temporary.name
        self.lock: IO[str] = (Path(self.name) / ".owner").open("w+")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.lock.write(MARKER)
        self.lock.flush()
        (Path(self.name) / ".owner").chmod(0o600)

    def cleanup(self) -> None:
        self.temporary.cleanup()
        self.lock.close()

    def __enter__(self) -> str:
        return self.name

    def __exit__(
        self,
        exc: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        with contextlib.suppress(OSError):
            self.cleanup()
