"""Workspace locks cover analysis, conversion and review saves (R85)."""

import fcntl
import json
import threading
import urllib.error
import urllib.request

import fitz
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import LLM, General, Settings
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.review_ui import create_review_server
from pdf2audiobook.workspace import read_manifest


def _source(path):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 80), "Chapter 1")
    page.insert_text((72, 120), "A first chapter with enough text for review.")
    page.insert_text((72, 180), "Chapter 2")
    page.insert_text((72, 220), "A second chapter with enough text for review.")
    document.save(path)
    document.close()


def _workspace(tmp_path):
    source = tmp_path / "book.pdf"
    _source(source)
    output = tmp_path / "output"
    settings = Settings(general=General(output_dir=str(output)), llm=LLM(enabled=False))
    manifest_path = analyze_book(source, settings)
    return source, output, manifest_path


def _hold_lock(manifest_path):
    handle = (manifest_path.parent / ".convert.lock").open("a+")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def _workspace_bytes(manifest_path):
    folder = manifest_path.parent
    return {
        path.relative_to(folder): path.read_bytes()
        for path in [manifest_path, *sorted((folder / "chapters").glob("*.txt"))]
    }


def test_convert_no_resume_refuses_locked_workspace_without_rewriting(tmp_path, monkeypatch):
    import pdf2audiobook.pipeline as pipeline

    source, output, manifest_path = _workspace(tmp_path)
    before = _workspace_bytes(manifest_path)
    analyzed_without_lock = []
    original_analyze = pipeline.analyze_book

    def record_analysis(*args, **kwargs):
        probe = (manifest_path.parent / ".convert.lock").open("a+")
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            pass
        else:
            analyzed_without_lock.append(True)
            fcntl.flock(probe, fcntl.LOCK_UN)
        finally:
            probe.close()
        return original_analyze(*args, **kwargs)

    monkeypatch.setattr(pipeline, "analyze_book", record_analysis)
    lock = _hold_lock(manifest_path)
    try:
        result = CliRunner().invoke(
            app,
            [
                "convert",
                str(source),
                "--output",
                str(output),
                "--no-llm",
                "--no-resume",
                "--allow-single-chapter",
            ],
        )
    finally:
        lock.close()
    assert result.exit_code != 0
    assert "already running" in result.output
    assert not analyzed_without_lock
    assert _workspace_bytes(manifest_path) == before


def test_analyze_refuses_locked_workspace(tmp_path):
    source, output, manifest_path = _workspace(tmp_path)
    before = _workspace_bytes(manifest_path)
    lock = _hold_lock(manifest_path)
    try:
        result = CliRunner().invoke(
            app, ["analyze", str(source), "--output", str(output), "--no-llm"]
        )
    finally:
        lock.close()
    assert result.exit_code != 0
    assert "already running" in result.output
    assert _workspace_bytes(manifest_path) == before


def test_review_save_returns_409_without_writing_when_workspace_is_locked(tmp_path):
    _source_path, _output, manifest_path = _workspace(tmp_path)
    manifest = read_manifest(manifest_path)
    before = manifest_path.read_bytes()
    chapters = [
        {
            "id": chapter.id,
            "title": chapter.title,
            "start_block": chapter.start_block,
            "end_block": chapter.end_block,
            "voice_id": chapter.voice_id,
        }
        for chapter in manifest.chapters
    ]
    server = create_review_server(manifest_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    lock = _hold_lock(manifest_path)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    request = urllib.request.Request(
        url + "/api/chapters",
        data=json.dumps({"chapters": chapters, "acknowledge": []}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {server.review_token}",
            "Origin": url,
            "Content-Type": "application/json",
        },
    )
    try:
        try:
            urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            assert error.code == 409
            assert error.read() == b'{"error": "Workspace is locked"}'
        else:
            raise AssertionError("review save must be refused while workspace is locked")
    finally:
        lock.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert manifest_path.read_bytes() == before
