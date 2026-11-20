"""Doctor reports optional Kitten availability without requiring model assets or type stubs."""

import importlib.metadata
import json

from typer.testing import CliRunner

from pdf2audiobook.cli import app


def test_doctor_detects_missing_optional_kitten_without_import_failure(monkeypatch):
    original = importlib.metadata.version

    def unavailable(name: str):
        if name == "kittenml":
            raise importlib.metadata.PackageNotFoundError(name)
        return original(name)

    monkeypatch.setattr(importlib.metadata, "version", unavailable)
    result = CliRunner().invoke(app, ["doctor", "--no-config", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["kitten_installed"] is False


def test_doctor_reports_optional_package_metadata_without_importing_ml(monkeypatch):
    import builtins

    original_version = importlib.metadata.version
    original_import = builtins.__import__

    def version(name: str):
        return "0.9.6" if name == "kittenml" else original_version(name)

    def guarded(name, *args, **kwargs):
        assert name.split(".")[0] not in {"kittenml", "torch", "transformers"}
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib.metadata, "version", version)
    monkeypatch.setattr(builtins, "__import__", guarded)
    result = CliRunner().invoke(app, ["doctor", "--no-config", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["kitten_installed"] is True
