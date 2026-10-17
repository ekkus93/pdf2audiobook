"""Doctor reports optional Kitten availability without requiring model assets or type stubs."""

import importlib
import json
from types import ModuleType

from typer.testing import CliRunner

from pdf2audiobook.cli import app


def test_doctor_detects_missing_optional_kitten_without_import_failure(monkeypatch):
    original = importlib.import_module

    def unavailable(name: str, package: str | None = None):
        if name == "kittenml":
            raise ModuleNotFoundError("No module named 'kittenml'")
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", unavailable)
    result = CliRunner().invoke(app, ["doctor", "--no-config", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["kitten_installed"] is False


def test_doctor_reports_importable_optional_kitten_without_loading_a_model(monkeypatch):
    original = importlib.import_module
    imports = []

    def available(name: str, package: str | None = None):
        if name == "kittenml":
            imports.append(name)
            return ModuleType("kittenml")
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", available)
    result = CliRunner().invoke(app, ["doctor", "--no-config", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["kitten_installed"] is True
    assert imports == ["kittenml"]
