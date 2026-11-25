"""Isolated KittenTTS 2/Whisper worker. Private JSON pipes only; never a public CLI."""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any


def _offline() -> None:
    # Reap the isolated worker even if a desktop force-stop kills its CLI parent.
    parent = os.environ.get("PDF2AUDIOBOOK_VOICE_PARENT")
    if parent and sys.platform == "linux":
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != int(parent):
            os._exit(1)
    os.environ.update({"OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"})
    os.environ.update(
        {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}
    )
    original = socket.socket.connect

    def connect(connection: socket.socket, address: Any) -> Any:
        if connection.family in {socket.AF_INET, socket.AF_INET6}:
            raise OSError("Model worker is offline")
        return original(connection, address)

    setattr(socket.socket, "connect", connect)


def _model() -> Any:
    import huggingface_hub  # type: ignore[import-not-found]

    from pdf2audiobook.tts.catalog import MANIFEST, artifact_path, model_directory

    def local_artifact(repo_id: str, filename: str, **kwargs: Any) -> str:
        for artifact in MANIFEST["files"]:
            if artifact["repo"] == repo_id and artifact["name"] == filename:
                path = artifact_path(artifact)
                if path.is_file():
                    return str(path)
        raise OSError("Unpinned model artifact")

    huggingface_hub.hf_hub_download = local_artifact
    from kittenml import KittenTTS2  # type: ignore[import-not-found]

    folder = model_directory() / "model"
    return KittenTTS2(
        str(folder),
        json.loads((folder / "config.json").read_text()),
        backend="torch",
        decoder="default",
        weights="emb4",
    )


def _transcribe(reference: str) -> str:
    from pdf2audiobook.tts.private import PrivateDirectory
    from pdf2audiobook.verification.backends import backend

    with PrivateDirectory("transcription") as folder:
        wav = Path(folder) / "reference.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                reference,
                "-ac",
                "1",
                "-ar",
                "16000",
                str(wav),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=20,
        )
        result = backend("whisper", device="cpu").transcribe(wav, should_stop=lambda: False)
        return " ".join(word.text for word in result.words)


def main() -> None:
    output = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    _offline()
    model = None
    with open(os.devnull, "w") as quiet:
        # C/C++ extensions may write directly to descriptors, bypassing redirect_stdout.
        os.dup2(quiet.fileno(), 1)
        os.dup2(quiet.fileno(), 2)
        for line in sys.stdin.buffer:
            phase = "model"
            try:
                request = json.loads(line)
                with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                    if request["command"] == "transcribe":
                        response = {"ok": True, "transcript": _transcribe(request["reference"])}
                    else:
                        if model is None:
                            model = _model()
                        if request["command"] == "load":
                            pass
                        elif request["command"] == "prepare":
                            # The SDK's cache also warms speaker/codec conditioning for this pair.
                            phase = "conditioning"
                            model._speaker(None, request["reference"], request["transcript"])
                        else:
                            import numpy as np

                            speaker = (
                                {"voice": request["voice"]}
                                if request["command"] == "generate_builtin"
                                else {
                                    "reference": request["reference"],
                                    "reference_text": request["transcript"],
                                }
                            )
                            audio = np.asarray(
                                model.generate(
                                    request["text"],
                                    **speaker,
                                    preset="stable",
                                    temperature=float(request["temperature"]),
                                    normalize=False,
                                    max_new_tokens=1000,
                                    advanced={"seed": 0, "use_emotion": False},
                                ),
                                dtype=np.float32,
                            )
                            if (
                                audio.ndim != 1
                                or not 0 < audio.size <= 24000 * 120
                                or not np.isfinite(audio).all()
                            ):
                                raise ValueError("invalid audio")
                            np.save(request["output"], np.clip(audio, -1, 1), allow_pickle=False)
                            Path(request["output"]).chmod(0o600)
                        response = {"ok": True}
                output.write(json.dumps(response, ensure_ascii=False) + "\n")
                output.flush()
            except Exception:
                reason = (
                    "voice_reference_invalid"
                    if phase == "conditioning"
                    else "voice_clone_unavailable"
                )
                output.write(json.dumps({"ok": False, "reason": reason}) + "\n")
                output.flush()


if __name__ == "__main__":
    main()
