"""Pinned KittenTTS 2 artifacts and explicit downloads; no ML imports or implicit network."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from pdf2audiobook.errors import AudioError, ConfigError

MANIFEST_PATH = Path(__file__).with_name("kitten2_manifest.json")
MANIFEST: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
MODEL_ID: str = MANIFEST["model"]
MODEL_REVISION: str = MANIFEST["revision"]
SDK_VERSION: str = MANIFEST["sdk_version"]
MANIFEST_SHA256 = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
REQUIRED_PACKAGES = (
    "kittenml",
    "torch",
    "torchaudio",
    "transformers",
    "safetensors",
    "soundfile",
    "librosa",
    "diffusers",
    "s3tokenizer",
    "omegaconf",
    "hydra-core",
)


def package_versions() -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for package in REQUIRED_PACKAGES:
        try:
            found[package] = version(package)
        except PackageNotFoundError:
            found[package] = None
    return found


def model_directory() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME")
    base = (
        Path(cache).expanduser()
        if cache and Path(cache).expanduser().is_absolute()
        else (Path.home() / ".cache")
    )
    return base / "pdf2audiobook" / "tts" / "kitten2" / MODEL_REVISION


def artifact_path(artifact: dict[str, Any], root: Path | None = None) -> Path:
    folder = "model" if artifact["repo"] == MODEL_ID else "decoder"
    return (root or model_directory()) / folder / artifact["name"]


def _stamp(path: Path) -> Path:
    return path.with_name(path.name + ".verified.json")


def _identity(path: Path, sha256: str) -> dict[str, Any]:
    status = path.stat()
    return {
        "sha256": sha256,
        "size": status.st_size,
        "mtime_ns": status.st_mtime_ns,
        "ctime_ns": status.st_ctime_ns,
        "dev": status.st_dev,
        "ino": status.st_ino,
    }


def verified(artifact: dict[str, Any], root: Path | None = None) -> bool:
    path = artifact_path(artifact, root)
    try:
        metadata_matches = (
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size == artifact["size"]
            and json.loads(_stamp(path).read_text()) == _identity(path, artifact["sha256"])
        )
        if not metadata_matches:
            return False
        # Some filesystems expose coarse or preserved change timestamps. A stamp is
        # provenance, not proof that the bytes still match the pinned model.
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == artifact["sha256"]
    except (OSError, UnicodeError, ValueError):
        return False


def missing_files(root: Path | None = None) -> list[dict[str, Any]]:
    return [artifact for artifact in MANIFEST["files"] if not verified(artifact, root)]


def model_readiness(root: Path | None = None) -> dict[str, Any]:
    from pdf2audiobook.tts.private import worker_supported
    from pdf2audiobook.verification.models import readiness

    packages = package_versions()
    packages_ready = all(packages.values()) and packages["kittenml"] == SDK_VERSION
    missing = missing_files(root)
    transcription = readiness("whisper")
    return {
        "name": "kitten2",
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "cloning": True,
        "backend": "torch",
        "device": "auto",
        "detected_device": "cuda" if Path("/dev/nvidia0").exists() else "cpu",
        "packages": packages,
        "required_sdk_version": SDK_VERSION,
        "package_installed": bool(packages_ready),
        "weights_present": not missing,
        "ready": bool(worker_supported() and packages_ready and not missing),
        "size_bytes": sum(artifact["size"] for artifact in MANIFEST["files"]),
        "download_bytes": sum(artifact["size"] for artifact in missing),
        "directory": str(root or model_directory()),
        "transcription_ready": transcription.ready,
        "transcription_model": transcription.revision,
        "files": [
            {
                "name": item["name"],
                "source": f"https://huggingface.co/{item['repo']}/resolve/{item['revision']}/{item['name']}",
                "size_bytes": item["size"],
                "sha256": item["sha256"],
                "cached": item not in missing,
            }
            for item in MANIFEST["files"]
        ],
        "reason": "unsupported_platform"
        if not worker_supported()
        else "model_not_installed"
        if not packages_ready
        else ("model_not_downloaded" if missing else None),
    }


def require_model() -> None:
    state = model_readiness()
    if state["reason"] == "unsupported_platform":
        raise AudioError(
            "Full KittenTTS 2 currently requires POSIX process and file-lock support",
            error_reason="voice_clone_unsupported",
        )
    if not state["ready"]:
        raise AudioError(
            "Voice cloning needs kittenml 0.9.6 and its optional dependencies, then "
            "'pdf2audiobook tts fetch kitten2'; no model was downloaded",
            error_reason="voice_clone_unavailable",
        )


def fetch_model(
    root: Path | None = None,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    on_file: Callable[[dict[str, Any]], None] | None = None,
) -> list[str]:
    """Download only pinned missing artifacts and publish verified files atomically."""
    fetched = []
    base = (root or model_directory()).resolve()
    for artifact in missing_files(base):
        destination = artifact_path(artifact, base)
        # Resolve existing ancestors and any symlinks before creating a missing suffix.
        if not destination.parent.resolve(strict=False).is_relative_to(base):
            raise ConfigError("The model cache contains an unsafe directory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if on_file:
            on_file(artifact)
        url = (
            f"https://huggingface.co/{artifact['repo']}/resolve/"
            f"{artifact['revision']}/{artifact['name']}"
        )
        temporary: Path | None = None
        try:
            digest, size = hashlib.sha256(), 0
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".part-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                with opener(url, timeout=30) as response:
                    while block := response.read(1 << 20):
                        size += len(block)
                        if size > artifact["size"]:
                            raise ValueError("size")
                        digest.update(block)
                        stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
            if size != artifact["size"] or digest.hexdigest() != artifact["sha256"]:
                raise ValueError("checksum")
            os.replace(temporary, destination)
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, mode="w", delete=False
            ) as stamp:
                temporary = Path(stamp.name)
                json.dump(_identity(destination, artifact["sha256"]), stamp)
            os.replace(temporary, _stamp(destination))
            fetched.append(artifact["name"])
        except (OSError, ValueError):
            raise AudioError(
                "Could not fetch a verified voice model; check network, storage and retry",
                error_reason="voice_clone_unavailable",
            ) from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return fetched
