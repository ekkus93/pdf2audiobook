"""Audio verification stays optional: separate extras, no ASR import by default (AV2.01, spec §4)."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASR_PACKAGES = ("openai-whisper", "vosk", "transformers", "torch")


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_each_backend_has_its_own_extra_and_asr_has_all_three() -> None:
    extras = _project()["optional-dependencies"]
    assert extras["asr-whisper"] == ["openai-whisper==20250625"]
    assert extras["asr-vosk"] == ["vosk==0.3.45"]
    assert {d.split(">")[0].split("=")[0] for d in extras["asr-wav2vec2"]} == {
        "transformers",
        "torch",
    }
    assert extras["asr"] == ["pdf2audiobook[asr-whisper,asr-wav2vec2,asr-vosk]"]


def test_the_default_install_has_no_asr_package() -> None:
    required = " ".join(_project()["dependencies"]).lower()
    for package in ASR_PACKAGES:
        assert package not in required, package
    # The Kitten extra, which already brings torch and transformers, is unchanged.
    assert _project()["optional-dependencies"]["kitten"] == ["kittenml>=0.9.4,<0.10"]


def test_importing_the_cli_and_verification_loads_no_asr_library() -> None:
    code = (
        "import sys\n"
        "import pdf2audiobook.cli, pdf2audiobook.pipeline\n"
        "import pdf2audiobook.verification.compare, pdf2audiobook.verification.reference\n"
        "import pdf2audiobook.verification.report, pdf2audiobook.verification.contracts\n"
        "print(sorted(m for m in ('whisper', 'vosk', 'transformers') if m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
