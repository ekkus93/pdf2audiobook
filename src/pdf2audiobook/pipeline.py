"""Orchestration stub; no false claims of successful conversion."""
from pathlib import Path

from pdf2audiobook.config import Settings
from pdf2audiobook.errors import ExtractionError


def analyze_book(source: Path, settings: Settings) -> Path:
    raise ExtractionError("PDF analysis is not implemented yet")


def convert_book(source: Path, settings: Settings, chapter: int | None = None) -> list[Path]:
    raise ExtractionError("Audiobook synthesis is not implemented yet")
