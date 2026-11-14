"""The pinned ASR models: where their weights live, whether they are ready, and fetching them.

Weights are fetched only by an explicit `pdf2audiobook asr fetch` (spec §4, §12); nothing here
downloads during conversion or verification. Each file is pinned by URL, size and SHA-256,
checked while downloading, and moved into place only once it matches. A small `.sha256`
stamp beside it records the check, so readiness is quick to report without rehashing
gigabytes.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path

from pdf2audiobook.errors import ConfigError, InputError
from pdf2audiobook.verification.contracts import MODEL_NAMES, ModelName, Readiness

WAV2VEC2_REVISION = "22aad52d435eb6dbaf354bdad9b0da84ce7d6156"
_HF = f"https://huggingface.co/facebook/wav2vec2-base-960h/resolve/{WAV2VEC2_REVISION}"
WHISPER_SHA256 = "d7440d1dc186f76616474e0ff0b3b6b879abc9d1a4926b7adfa41db2d497ab4f"
VOSK_MODEL = "vosk-model-en-us-0.22-lgraph"


class ModelFetchError(InputError):
    """A model download or check failed; the message holds no path or content."""


@dataclass(frozen=True)
class PinnedFile:
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelSpec:
    name: ModelName
    family: str
    model_id: str
    revision: str
    # Distribution names whose presence makes the backend importable.
    packages: tuple[str, ...]
    files: tuple[PinnedFile, ...]
    # A zip archive unpacked into this folder once checked (Vosk).
    unpack_to: str | None = None

    @property
    def size_bytes(self) -> int:
        return sum(f.size for f in self.files)


SPECS: dict[ModelName, ModelSpec] = {
    "whisper": ModelSpec(
        "whisper",
        "OpenAI Whisper",
        "medium.en",
        WHISPER_SHA256,
        ("openai-whisper",),
        (
            PinnedFile(
                "medium.en.pt",
                f"https://openaipublic.azureedge.net/main/whisper/models/{WHISPER_SHA256}/medium.en.pt",
                1_528_006_491,
                WHISPER_SHA256,
            ),
        ),
    ),
    "wav2vec2": ModelSpec(
        "wav2vec2",
        "Meta Wav2Vec2",
        "facebook/wav2vec2-base-960h",
        WAV2VEC2_REVISION,
        ("transformers", "torch"),
        tuple(
            PinnedFile(name, f"{_HF}/{name}", size, sha256)
            for name, size, sha256 in (
                (
                    "config.json",
                    1596,
                    "d3ec255c063d9f95057b553b19c20135b259875834a4fe9deb218a6be25b4cf3",
                ),
                (
                    "feature_extractor_config.json",
                    158,
                    "d3de0c797bf9b65f90bc65c30cb7b303ebeda341f6fc80af33628c4b26b95632",
                ),
                (
                    "preprocessor_config.json",
                    159,
                    "b225d617c025463b9e157e06afea8b90dc7078fc70b013c533328423e0486b4a",
                ),
                (
                    "special_tokens_map.json",
                    85,
                    "bb7068de1150661a10b55f9e4b12a0e77af8bf91f5e45e1b58afaf1d0e17f675",
                ),
                (
                    "tokenizer_config.json",
                    163,
                    "dc790594f5bc351a4311c6624f40acd95850d4aaf2a5cb3c656c9b610720b608",
                ),
                (
                    "vocab.json",
                    291,
                    "19727f8944fe6459fc3f240ae2c198395b740f6a029bd23e06656266b83bcf64",
                ),
                (
                    "model.safetensors",
                    377_607_901,
                    "8aa76ab2243c81747a1f832954586bc566090c83a0ac167df6f31f0fa917d74a",
                ),
            )
        ),  # fmt: skip
    ),
    "vosk": ModelSpec(
        "vosk",
        "Vosk/Kaldi",
        VOSK_MODEL,
        "d9838b4aaa82a75c4a17f5aca300eaca129aaab2a7cbf951bafbb500eb9c4334",
        ("vosk",),
        (
            PinnedFile(
                f"{VOSK_MODEL}.zip",
                f"https://alphacephei.com/vosk/models/{VOSK_MODEL}.zip",
                130_557_655,
                "d9838b4aaa82a75c4a17f5aca300eaca129aaab2a7cbf951bafbb500eb9c4334",
            ),
        ),
        unpack_to=VOSK_MODEL,
    ),
}


def models_dir(environ: dict[str, str] | None = None) -> Path:
    """`PDF2AUDIOBOOK_ASR_DIR`, else `$XDG_CACHE_HOME/pdf2audiobook/asr` (`~/.cache/...`)."""
    env = os.environ if environ is None else environ
    if env.get("PDF2AUDIOBOOK_ASR_DIR"):
        return Path(env["PDF2AUDIOBOOK_ASR_DIR"]).expanduser()
    cache = env.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache).expanduser() / "pdf2audiobook" / "asr"


def model_dir(name: ModelName, root: Path | None = None) -> Path:
    return (root or models_dir()) / name


def _stamp(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def _verified(path: Path, pinned: PinnedFile) -> bool:
    """The file is there, the right size, and was checked against its pinned SHA-256."""
    try:
        return (
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size == pinned.size
            and _stamp(path).read_text(encoding="ascii").strip() == pinned.sha256
        )
    except (OSError, UnicodeError):
        return False


def _installed(spec: ModelSpec) -> str | None:
    """The first package's version if every package is installed, else None."""
    versions = []
    for package in spec.packages:
        try:
            versions.append(package_version(package))
        except PackageNotFoundError:
            return None
    return versions[0]


def weights_ready(spec: ModelSpec, root: Path | None = None) -> bool:
    folder = model_dir(spec.name, root)
    if not all(_verified(folder / f.name, f) for f in spec.files):
        return False
    return spec.unpack_to is None or (folder / spec.unpack_to / ".unpacked").is_file()


def readiness(name: ModelName, root: Path | None = None) -> Readiness:
    """Whether `name` can run here, without importing its package or loading the model."""
    spec = SPECS[name]
    installed = _installed(spec)
    present = weights_ready(spec, root)
    reason = (
        None
        if installed and present
        else ("model_not_installed" if installed is None else "model_not_downloaded")
    )
    return Readiness(
        spec.name, spec.family, spec.model_id, spec.revision, spec.packages[0],
        installed, present, spec.size_bytes, str(model_dir(name, root)), reason,
    )  # fmt: skip


Opener = Callable[[str], object]


def _download(pinned: PinnedFile, destination: Path, opener: Opener) -> None:
    """Stream `pinned` to `destination`, checking size and SHA-256 before it is moved there."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".part-", delete=False) as part:
        temporary = Path(part.name)
        try:
            with opener(pinned.url) as response:  # type: ignore[attr-defined]
                while block := response.read(1 << 20):
                    size += len(block)
                    if size > pinned.size:
                        raise ModelFetchError("Downloaded model file is larger than expected")
                    digest.update(block)
                    part.write(block)
        except ModelFetchError:
            temporary.unlink(missing_ok=True)
            raise
        except Exception:
            temporary.unlink(missing_ok=True)
            raise ModelFetchError(
                "Could not download the model; check the network connection"
            ) from None
    if size != pinned.size or digest.hexdigest() != pinned.sha256:
        temporary.unlink(missing_ok=True)
        raise ModelFetchError("Downloaded model file does not match its pinned checksum")
    os.replace(temporary, destination)
    _stamp(destination).write_text(pinned.sha256 + "\n", encoding="ascii")


def _unpack(archive: Path, folder: Path, target: str) -> None:
    """Unpack a checked zip next to it; refuse members that would land outside the folder."""
    final = folder / target
    staging = Path(tempfile.mkdtemp(dir=folder, prefix=".unpack-"))
    try:
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.namelist():
                resolved = (staging / member).resolve()
                if not resolved.is_relative_to(staging.resolve()):
                    raise ModelFetchError("Model archive has an unsafe file name")
            zipped.extractall(staging)
        unpacked = staging / target
        if not unpacked.is_dir():
            raise ModelFetchError("Model archive does not have the expected layout")
        (unpacked / ".unpacked").write_text("ok\n", encoding="ascii")
        if final.exists():
            shutil.rmtree(final)
        os.replace(unpacked, final)
    except zipfile.BadZipFile:
        raise ModelFetchError("Model archive could not be read") from None
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def fetch(
    name: ModelName,
    root: Path | None = None,
    *,
    opener: Opener | None = None,
    on_file: Callable[[PinnedFile], None] | None = None,
) -> list[PinnedFile]:
    """Download what `name` lacks; return the files downloaded (none if it was ready)."""
    spec = SPECS[name]
    folder = model_dir(name, root)
    fetched = []
    for pinned in spec.files:
        if _verified(folder / pinned.name, pinned):
            continue
        if on_file is not None:
            on_file(pinned)
        _download(pinned, folder / pinned.name, opener or urllib.request.urlopen)
        fetched.append(pinned)
    if spec.unpack_to is not None and (
        fetched or not (folder / spec.unpack_to / ".unpacked").is_file()
    ):
        _unpack(folder / spec.files[0].name, folder, spec.unpack_to)
    return fetched


def resolve_names(names: list[str]) -> list[ModelName]:
    """Model names from the command line; `all` means every model, in the usual order."""
    if not names or "all" in names:
        return list(MODEL_NAMES)
    chosen: list[ModelName] = []
    for name in names:
        if name not in MODEL_NAMES:
            raise ConfigError("Unknown model; choose whisper, wav2vec2, vosk or all")
        if name not in chosen:
            chosen.append(name)
    return chosen


def _size(nbytes: int) -> str:
    return f"{nbytes / 1e9:.1f} GB" if nbytes >= 1e9 else f"{nbytes / 1e6:.0f} MB"


INSTALL_HINT = {
    "whisper": "uv sync --extra asr-whisper",
    "wav2vec2": "uv sync --extra asr-wav2vec2",
    "vosk": "uv sync --extra asr-vosk",
}


def list_payload(root: Path | None = None) -> dict[str, object]:
    """What `asr list --json` prints (desktop/contracts/asr-models.schema.json)."""
    from pdf2audiobook.verification.report import readiness_json

    folder = root or models_dir()
    return {
        "models": [readiness_json(readiness(name, folder)) for name in MODEL_NAMES],
        "directory": str(folder),
        "warnings": [],
    }


def list_text(payload: dict[str, object]) -> str:
    """`asr list` for people: each model's state and the step that makes it ready."""
    lines = [f"Models are kept in {payload['directory']}"]
    for model in payload["models"]:  # type: ignore[attr-defined]
        name = model["model"]
        state = (
            "ready"
            if model["ready"]
            else f"not installed: {INSTALL_HINT[name]}"
            if model["reason"] == "model_not_installed"
            else f"not downloaded ({_size(model['size_bytes'])}): pdf2audiobook asr fetch {name}"
        )
        lines.append(f"  {name:9} {model['family']} {model['model_id']}: {state}")
    return "\n".join(lines)


def fetch_plan(
    names: list[ModelName], root: Path | None = None
) -> list[tuple[ModelName, list[PinnedFile]]]:
    """The files each model still needs, in order; models already ready need none."""
    folder = root or models_dir()
    plan = []
    for name in names:
        spec = SPECS[name]
        missing = [f for f in spec.files if not _verified(model_dir(name, folder) / f.name, f)]
        plan.append((name, missing))
    return plan


def plan_text(plan: list[tuple[ModelName, list[PinnedFile]]], root: Path | None = None) -> str:
    """What will be downloaded, from where, how much and to where (spec §4: say so first)."""
    folder = root or models_dir()
    lines = []
    for name, files in plan:
        for pinned in files:
            host = pinned.url.split("/")[2]
            lines.append(f"  {name}: {pinned.name}, {_size(pinned.size)} from {host}")
    total = sum(f.size for _, files in plan for f in files)
    lines.append(f"Total {_size(total)}, saved under {folder}")
    return "\n".join(lines)
